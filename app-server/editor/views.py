import json
import hashlib
import re
import secrets
import uuid
from datetime import timedelta
from math import ceil

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
	DocumentComment, DocumentVersion, FileEntry, Notification, UserProfile,
	Workspace, WorkspaceMembership, WorkspaceShareLink,
)
from .models import empty_document
from .ai import ACTION_INSTRUCTIONS, PROVIDERS, available_providers, build_messages, stream_completion


MAX_NAME_LENGTH = 100
MAX_CONTENT_BYTES = 1_000_000
MAX_COMMENT_LENGTH = 4000


def _error(message, status):
	return JsonResponse({"error": message}, status=status)


def _authenticated(request):
	if request.user.is_authenticated:
		return True
	return False


def _workspace_role(workspace, user):
	if workspace.owner_id == user.id:
		return "owner"
	membership = WorkspaceMembership.objects.filter(workspace=workspace, user=user).first()
	if membership:
		return membership.role
	return None


@require_http_methods(["GET"])
def ai_providers(request):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	return JsonResponse({"providers": available_providers()})


@require_http_methods(["POST"])
def ai_completion(request, workspace_id, file_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	try:
		entry = FileEntry.objects.select_related("workspace").get(
			id=file_id, workspace_id=workspace_id, kind=FileEntry.Kind.FILE
		)
	except FileEntry.DoesNotExist:
		return _error("Document was not found.", 404)
	if _workspace_role(entry.workspace, request.user) is None:
		return _error("Document was not found.", 404)

	provider = body.get("provider")
	action = body.get("action")
	document_name = body.get("document_name", entry.name)
	context = body.get("context", "")
	prompt = body.get("prompt", "")
	history = body.get("history", [])
	if not isinstance(provider, str) or provider not in PROVIDERS:
		return _error("AI provider is invalid.", 400)
	if not any(item["id"] == provider for item in available_providers()):
		return _error("Choose an AI provider configured by your workspace administrator.", 503)
	if not isinstance(action, str) or action not in ACTION_INSTRUCTIONS:
		return _error("AI action is invalid.", 400)
	if (
		not isinstance(document_name, str)
		or len(document_name) > MAX_NAME_LENGTH
		or not isinstance(context, str)
		or len(context) > 60000
		or not isinstance(prompt, str)
		or len(prompt) > 4000
		or not isinstance(history, list)
		or len(history) > 12
	):
		return _error("AI request exceeds the supported size.", 400)
	if any(
		not isinstance(message, dict)
		or message.get("role") not in {"user", "assistant"}
		or not isinstance(message.get("content"), str)
		or len(message["content"]) > 4000
		for message in history
	):
		return _error("Conversation history is invalid.", 400)
	if not prompt.strip() and action not in {"summarize", "grammar", "insights"}:
		return _error("Enter an instruction or question.", 400)

	messages = build_messages(action, document_name, context, prompt, history)

	def events():
		try:
			for text in stream_completion(provider, messages):
				yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
			yield "data: {\"done\":true}\n\n"
		except RuntimeError as error:
			yield f"event: error\ndata: {json.dumps({'error': str(error)})}\n\n"

	response = StreamingHttpResponse(events(), content_type="text/event-stream; charset=utf-8")
	response["Cache-Control"] = "no-cache, no-transform"
	response["X-Accel-Buffering"] = "no"
	return response


@require_http_methods(["GET"])
def csrf_token(request):
	return JsonResponse({"csrfToken": get_token(request)})


@require_http_methods(["GET", "POST"])
def auth_session(request):
	if request.method == "GET":
		if not _authenticated(request):
			return _error("Authentication required.", 401)
		return JsonResponse(_user_payload(request.user))
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	user = authenticate(request, username=body.get("username", ""), password=body.get("password", ""))
	if user is None:
		return _error("Username or password is incorrect.", 401)
	login(request, user)
	return JsonResponse(_user_payload(user))


def _user_payload(user):
	profile, _ = UserProfile.objects.get_or_create(user=user)
	return {
		"id": user.id,
		"username": user.get_username(),
		"display_name": profile.display_name or user.get_username(),
		"email": user.email,
	}


def _display_name(user):
	profile = getattr(user, "profile", None)
	return (profile.display_name if profile else "") or user.get_username()


@require_http_methods(["GET", "PATCH"])
def auth_profile(request):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	if request.method == "GET":
		return JsonResponse(_user_payload(request.user))
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	allowed = {"display_name", "email", "current_password", "new_password"}
	if set(body) - allowed:
		return _error("Profile fields are invalid.", 400)
	display_name = body.get("display_name", "")
	email = body.get("email", "")
	if not isinstance(display_name, str) or len(display_name.strip()) > 100:
		return _error("Display name must be 100 characters or fewer.", 400)
	if not isinstance(email, str) or len(email.strip()) > 254:
		return _error("Email must be 254 characters or fewer.", 400)
	try:
		validate_email(email.strip())
	except ValidationError:
		if email.strip():
			return _error("Enter a valid email address.", 400)
	new_password = body.get("new_password")
	if new_password is not None:
		if not isinstance(body.get("current_password"), str) or not request.user.check_password(body["current_password"]):
			return _error("Current password is incorrect.", 400)
		try:
			validate_password(new_password, request.user)
		except ValidationError as error:
			return _error(" ".join(error.messages), 400)
		request.user.set_password(new_password)
	request.user.email = email.strip()
	request.user.save(update_fields=["email", "password"] if new_password is not None else ["email"])
	profile, _ = UserProfile.objects.get_or_create(user=request.user)
	profile.display_name = display_name.strip()
	profile.save(update_fields=["display_name"])
	if new_password is not None:
		update_session_auth_hash(request, request.user)
	return JsonResponse(_user_payload(request.user))


@require_http_methods(["POST"])
def register(request):
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	username = body.get("username")
	password = body.get("password")
	if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,150}", username.strip()):
		return _error("Enter a valid username.", 400)
	if not isinstance(password, str):
		return _error("Password is required.", 400)
	User = get_user_model()
	user = User(username=username.strip())
	try:
		validate_password(password, user)
		user.set_password(password)
		user.save()
	except ValidationError as error:
		return JsonResponse({"error": " ".join(error.messages)}, status=400)
	except IntegrityError:
		return _error("That username is already in use.", 409)
	login(request, user)
	return JsonResponse(_user_payload(user), status=201)


@require_http_methods(["POST"])
def end_session(request):
	logout(request)
	return JsonResponse({})


@require_http_methods(["GET", "POST"])
def workspaces(request):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	if request.method == "GET":
		workspaces = Workspace.objects.filter(owner=request.user) | Workspace.objects.filter(
			memberships__user=request.user
		)
		return JsonResponse([
			{"id": str(workspace.id), "name": workspace.name,
			 "role": _workspace_role(workspace, request.user)}
			for workspace in workspaces.distinct().order_by("created_at")
		], safe=False)
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	name = _validated_name(body.get("name", "Workspace"))
	if name is None:
		return _error("Workspace name is invalid.", 400)
	workspace = Workspace.objects.create(name=name, owner=request.user)
	return JsonResponse({"id": str(workspace.id), "name": workspace.name, "role": "owner"}, status=201)


@require_http_methods(["PATCH"])
def workspace_detail(request, workspace_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		workspace = Workspace.objects.get(id=workspace_id)
	except Workspace.DoesNotExist:
		return _error("Workspace was not found.", 404)
	if workspace.owner_id != request.user.id:
		return _error("Only the workspace owner can change workspace settings.", 403)
	body = _parse_body(request)
	if body is None or set(body) != {"name"}:
		return _error("Provide a valid workspace name.", 400)
	name = _validated_name(body.get("name"))
	if name is None:
		return _error("Workspace name is invalid.", 400)
	workspace.name = name
	workspace.save(update_fields=["name", "updated_at"])
	return JsonResponse({"id": str(workspace.id), "name": workspace.name, "role": "owner"})


@require_http_methods(["GET", "POST"])
def workspace_share_links(request, workspace_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		workspace = Workspace.objects.get(id=workspace_id)
	except Workspace.DoesNotExist:
		return _error("Workspace was not found.", 404)
	if workspace.owner_id != request.user.id:
		return _error("Only the workspace owner can manage sharing links.", 403)
	if request.method == "GET":
		links = WorkspaceShareLink.objects.filter(workspace=workspace, revoked_at__isnull=True)
		return JsonResponse([
			{"id": link.id, "role": link.role, "created_at": link.created_at.isoformat(),
			 "expires_at": link.expires_at.isoformat() if link.expires_at else None}
			for link in links.order_by("-created_at")
		], safe=False)
	body = _parse_body(request)
	if body is None or body.get("role") not in WorkspaceMembership.Role.values:
		return _error("Role must be 'editor' or 'viewer'.", 400)
	expiration = body.get("expires_in_days", 7)
	if expiration not in (1, 7, 30, None):
		return _error("Link expiration must be 1, 7, or 30 days, or null.", 400)
	token = secrets.token_urlsafe(32)
	link = WorkspaceShareLink.objects.create(
		workspace=workspace,
		token_hash=WorkspaceShareLink.digest(token),
		role=body["role"],
		created_by=request.user,
		expires_at=timezone.now() + timedelta(days=expiration) if expiration else None,
	)
	return JsonResponse({
		"id": link.id, "role": link.role, "token": token,
		"expires_at": link.expires_at.isoformat() if link.expires_at else None,
	}, status=201)


@require_http_methods(["DELETE"])
def workspace_share_link(request, workspace_id, link_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		link = WorkspaceShareLink.objects.get(id=link_id, workspace_id=workspace_id)
	except WorkspaceShareLink.DoesNotExist:
		return _error("Sharing link was not found.", 404)
	if link.workspace.owner_id != request.user.id:
		return _error("Only the workspace owner can manage sharing links.", 403)
	link.revoked_at = timezone.now()
	link.save(update_fields=["revoked_at"])
	return JsonResponse({})


@require_http_methods(["POST"])
def accept_share_link(request, token):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	link = WorkspaceShareLink.objects.select_related("workspace").filter(
		token_hash=WorkspaceShareLink.digest(token), revoked_at__isnull=True
	).first()
	if link is None or (link.expires_at and link.expires_at <= timezone.now()):
		return _error("This sharing link is invalid or expired.", 404)
	if link.workspace.owner_id == request.user.id:
		return JsonResponse({"workspace_id": str(link.workspace_id), "role": "owner"})
	WorkspaceMembership.objects.update_or_create(
		workspace=link.workspace, user=request.user, defaults={"role": link.role}
	)
	if link.workspace.owner_id:
		Notification.objects.create(
			user_id=link.workspace.owner_id, workspace=link.workspace, kind="member_joined",
			message=f"{request.user.get_username()} joined {link.workspace.name}.",
		)
	return JsonResponse({"workspace_id": str(link.workspace_id), "role": link.role})


@require_http_methods(["GET"])
def search_documents(request):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	query = request.GET.get("q", "").strip()
	workspace_id = request.GET.get("workspace")
	if len(query) < 2 or len(query) > 100:
		return _error("Search must be between 2 and 100 characters.", 400)
	entries = FileEntry.objects.filter(kind=FileEntry.Kind.FILE).filter(
		Q(workspace__owner=request.user) | Q(workspace__memberships__user=request.user)
	).filter(Q(name__icontains=query) | Q(content__icontains=query)).select_related("workspace")
	if workspace_id:
		entries = entries.filter(workspace_id=workspace_id)
	results = [
		{"id": str(entry.id), "name": entry.name, "workspace_id": str(entry.workspace_id),
		 "workspace_name": entry.workspace.name, "updated_at": entry.updated_at.isoformat()}
		for entry in entries.distinct().order_by("-updated_at")[:50]
	]
	return JsonResponse({"results": results})


@require_http_methods(["GET", "POST"])
def document_comments(request, workspace_id, file_id):
	entry, role, error = _member_document(request, workspace_id, file_id)
	if error:
		return error
	if request.method == "GET":
		comments = entry.comments.select_related("author__profile").all()
		return JsonResponse([
			{"id": comment.id, "body": comment.body,
			 "author": _display_name(comment.author) if comment.author else "Former user",
			 "created_at": comment.created_at.isoformat(),
			 "resolved": comment.resolved_at is not None}
			for comment in comments
		], safe=False)
	body = _parse_body(request)
	text = body.get("body") if body else None
	if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_COMMENT_LENGTH:
		return _error("Comment must be between 1 and 4,000 characters.", 400)
	comment = DocumentComment.objects.create(document=entry, author=request.user, body=text.strip())
	recipients = set(entry.workspace.memberships.values_list("user_id", flat=True))
	if entry.workspace.owner_id:
		recipients.add(entry.workspace.owner_id)
	recipients.discard(request.user.id)
	Notification.objects.bulk_create([
		Notification(
			user_id=user_id, workspace=entry.workspace, document=entry, kind="comment",
			message=f"{request.user.get_username()} commented on {entry.name}.",
		)
		for user_id in recipients
	])
	return JsonResponse({
		"id": comment.id, "body": comment.body, "author": _display_name(request.user),
		"created_at": comment.created_at.isoformat(), "resolved": False,
	}, status=201)


def _member_document(request, workspace_id, file_id):
	if not _authenticated(request):
		return None, None, _error("Authentication required.", 401)
	try:
		entry = FileEntry.objects.select_related("workspace").get(
			id=file_id, workspace_id=workspace_id, kind=FileEntry.Kind.FILE
		)
	except FileEntry.DoesNotExist:
		return None, None, _error("Document was not found.", 404)
	role = _workspace_role(entry.workspace, request.user)
	if role is None:
		return None, None, _error("Document was not found.", 404)
	return entry, role, None


@require_http_methods(["GET", "POST"])
def document_history(request, workspace_id, file_id):
	entry, role, error = _member_document(request, workspace_id, file_id)
	if error:
		return error
	if request.method == "GET":
		versions = entry.versions.select_related("author__profile")[:50]
		return JsonResponse([
			{"id": version.id, "author": _display_name(version.author) if version.author else "Former user",
			 "created_at": version.created_at.isoformat()}
			for version in versions
		], safe=False)
	if role == WorkspaceMembership.Role.VIEWER:
		return _error("Viewer access is read-only.", 403)
	body = _parse_body(request)
	content = body.get("content") if body else None
	if not _valid_content(content):
		return _error("Version content must be valid JSON under 1 MB.", 400)
	digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
	version, created = DocumentVersion.objects.get_or_create(
		document=entry, content_hash=digest,
		defaults={"author": request.user, "content": content},
	)
	return JsonResponse(
		{"id": version.id, "created_at": version.created_at.isoformat()},
		status=201 if created else 200,
	)


@require_http_methods(["GET"])
def document_version(request, workspace_id, file_id, version_id):
	entry, _, error = _member_document(request, workspace_id, file_id)
	if error:
		return error
	try:
		version = entry.versions.get(id=version_id)
	except DocumentVersion.DoesNotExist:
		return _error("Document version was not found.", 404)
	return JsonResponse({"id": version.id, "content": version.content})


@require_http_methods(["GET", "POST"])
def notifications(request):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	if request.method == "POST":
		Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
		return JsonResponse({})
	return JsonResponse([
		{"id": item.id, "kind": item.kind, "message": item.message,
		 "workspace_id": str(item.workspace_id), "document_id": str(item.document_id) if item.document_id else None,
		 "created_at": item.created_at.isoformat(), "read": item.read_at is not None}
		for item in request.user.notifications.select_related("workspace", "document")[:50]
	], safe=False)


@require_http_methods(["GET", "POST"])
def workspace_members(request, workspace_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		workspace = Workspace.objects.select_related("owner__profile").get(id=workspace_id)
	except Workspace.DoesNotExist:
		return _error("Workspace was not found.", 404)
	role = _workspace_role(workspace, request.user)
	if role is None:
		return _error("Workspace was not found.", 404)
	if request.method == "GET":
		if role != "owner":
			return _error("Only the workspace owner can manage members.", 403)
		members = [{
			"id": workspace.owner_id,
			"username": workspace.owner.get_username(),
			"display_name": _display_name(workspace.owner),
			"role": "owner",
		}]
		members.extend(
			{"id": membership.user_id, "username": membership.user.get_username(),
			 "display_name": _display_name(membership.user), "role": membership.role}
			for membership in workspace.memberships.select_related("user__profile").order_by("user__username")
		)
		return JsonResponse(members, safe=False)
	if role != "owner":
		return _error("Only the workspace owner can manage members.", 403)
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	username = body.get("username")
	member_role = body.get("role")
	if member_role not in WorkspaceMembership.Role.values:
		return _error("Role must be 'editor' or 'viewer'.", 400)
	try:
		user = get_user_model().objects.get(username=username)
	except get_user_model().DoesNotExist:
		return _error("User was not found.", 404)
	if user.id == request.user.id:
		return _error("The owner already has full access.", 400)
	previous_role = WorkspaceMembership.objects.filter(workspace=workspace, user=user).values_list(
		"role", flat=True
	).first()
	membership, created = WorkspaceMembership.objects.update_or_create(
		workspace=workspace, user=user, defaults={"role": member_role}
	)
	if previous_role != membership.role:
		Notification.objects.create(
			user=user, workspace=workspace, kind="workspace_access",
			message=f"{workspace.name} shared with you as {membership.role}.",
		)
	if not created:
		async_to_sync(get_channel_layer().group_send)(
			f"editor_user_{user.id}", {"type": "editor_access_changed"}
		)
	return JsonResponse({"id": user.id, "username": user.get_username(), "role": membership.role}, status=201)


@require_http_methods(["DELETE"])
def workspace_member(request, workspace_id, user_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		workspace = Workspace.objects.get(id=workspace_id)
	except Workspace.DoesNotExist:
		return _error("Workspace was not found.", 404)
	if _workspace_role(workspace, request.user) != "owner":
		return _error("Only the workspace owner can manage members.", 403)
	if user_id == workspace.owner_id:
		return _error("The workspace owner cannot be removed.", 400)
	try:
		membership = WorkspaceMembership.objects.get(workspace=workspace, user_id=user_id)
	except WorkspaceMembership.DoesNotExist:
		return _error("Workspace member was not found.", 404)
	membership.delete()
	async_to_sync(get_channel_layer().group_send)(
		f"editor_user_{user_id}", {"type": "editor_access_changed"}
	)
	return JsonResponse({})


@require_http_methods(["GET", "POST"])
def document_initialization(request, workspace_id, file_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		entry = FileEntry.objects.select_related("workspace").get(
			id=file_id, workspace_id=workspace_id, kind=FileEntry.Kind.FILE
		)
	except FileEntry.DoesNotExist:
		return _error("Document was not found.", 404)
	role = _workspace_role(entry.workspace, request.user)
	if role is None:
		return _error("Document was not found.", 404)
	can_edit = role in ("owner", WorkspaceMembership.Role.EDITOR)
	if request.method == "POST" and not can_edit:
		return _error("Viewer access is read-only.", 403)

	with transaction.atomic():
		entry = FileEntry.objects.select_for_update().get(id=entry.id)
		if entry.yjs_updates.exists():
			return JsonResponse({"ready": True, "initialize": False})
		if entry.content == empty_document():
			return JsonResponse({"ready": True, "initialize": False})
		now = timezone.now()
		if entry.yjs_initializing_until and entry.yjs_initializing_until > now:
			return JsonResponse({
				"ready": False,
				"retry_after": max(1, ceil((entry.yjs_initializing_until - now).total_seconds())),
			})
		if not can_edit:
			return JsonResponse({"ready": False, "retry_after": 2})
		entry.yjs_initializing_until = now + timedelta(seconds=30)
		entry.save(update_fields=["yjs_initializing_until"])
		return JsonResponse({"ready": True, "initialize": True})


def _parse_body(request):
	if len(request.body) > MAX_CONTENT_BYTES + 4096:
		return None
	try:
		body = json.loads(request.body or b"{}")
	except (json.JSONDecodeError, UnicodeDecodeError):
		return None
	return body if isinstance(body, dict) else None


def _serialize(entry):
	return {
		"id": str(entry.id),
		"name": entry.name,
		"kind": entry.kind,
		"parent_id": str(entry.parent_id) if entry.parent_id else None,
		"content": entry.content,
		"created_at": entry.created_at.isoformat(),
		"updated_at": entry.updated_at.isoformat(),
	}


def _validated_name(value):
	if not isinstance(value, str):
		return None
	name = value.strip()
	device_name = re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.IGNORECASE)
	if (
		not name
		or len(name) > MAX_NAME_LENGTH
		or name in {".", ".."}
		or device_name
		or name.endswith(".")
		or re.search(r'[<>:"|?*/\\\x00-\x1f]', name)
		or any(ord(char) < 32 for char in name)
	):
		return None
	return name


def _get_parent(workspace, parent_id):
	if parent_id in (None, ""):
		return None
	try:
		parent_uuid = uuid.UUID(str(parent_id))
		parent = FileEntry.objects.get(id=parent_uuid, workspace=workspace)
	except (ValueError, TypeError, FileEntry.DoesNotExist):
		return False
	return parent if parent.kind == FileEntry.Kind.FOLDER else False


def _name_conflicts(workspace, parent, name, exclude_id=None):
	siblings = FileEntry.objects.filter(workspace=workspace, parent=parent)
	if exclude_id:
		siblings = siblings.exclude(id=exclude_id)
	return any(entry.name.lower() == name.lower() for entry in siblings.only("name"))


def _valid_content(content):
	if not isinstance(content, (dict, list)):
		return False
	try:
		return len(json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")) <= MAX_CONTENT_BYTES
	except (TypeError, ValueError, UnicodeEncodeError):
		return False


@require_http_methods(["GET", "POST"])
def workspace_files(request, workspace_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		workspace = Workspace.objects.get(id=workspace_id)
	except Workspace.DoesNotExist:
		return _error("Workspace was not found.", 404)
	role = _workspace_role(workspace, request.user)
	if role is None:
		return _error("Workspace was not found.", 404)

	if request.method == "GET":
		entries = FileEntry.objects.filter(workspace=workspace).select_related("parent")
		return JsonResponse({"role": role, "entries": [_serialize(entry) for entry in entries]})
	if role == WorkspaceMembership.Role.VIEWER:
		return _error("Viewer access is read-only.", 403)

	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	name = _validated_name(body.get("name"))
	kind = body.get("kind")
	parent = _get_parent(workspace, body.get("parent_id"))
	if name is None:
		return _error("Name is invalid or exceeds 100 characters.", 400)
	if kind not in FileEntry.Kind.values:
		return _error("Kind must be 'file' or 'folder'.", 400)
	if parent is False:
		return _error("Parent folder was not found.", 400)
	content = body.get("content", empty_document() if kind == FileEntry.Kind.FILE else {})
	if kind == FileEntry.Kind.FOLDER and content:
		return _error("Folders cannot contain file content.", 400)
	if kind == FileEntry.Kind.FILE and not _valid_content(content):
		return _error("File content must be a JSON object or array under 1 MB.", 400)

	try:
		with transaction.atomic():
			Workspace.objects.select_for_update().get(id=workspace.id)
			if _name_conflicts(workspace, parent, name):
				return _error("An item with that name already exists in this folder.", 409)
			entry = FileEntry.objects.create(
				workspace=workspace,
				parent=parent,
				name=name,
				kind=kind,
				content=content if kind == FileEntry.Kind.FILE else {},
			)
	except IntegrityError:
		return _error("An item with that name already exists in this folder.", 409)
	return JsonResponse(_serialize(entry), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def workspace_file(request, workspace_id, file_id):
	if not _authenticated(request):
		return _error("Authentication required.", 401)
	try:
		entry = FileEntry.objects.select_related("workspace", "parent").get(
			id=file_id, workspace_id=workspace_id
		)
	except FileEntry.DoesNotExist:
		return _error("File or folder was not found.", 404)
	role = _workspace_role(entry.workspace, request.user)
	if role is None:
		return _error("File or folder was not found.", 404)
	if request.method == "GET":
		return JsonResponse(_serialize(entry))
	if role == WorkspaceMembership.Role.VIEWER:
		return _error("Viewer access is read-only.", 403)

	if request.method == "DELETE":
		entry.delete()
		return JsonResponse({}, status=200)

	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	name = entry.name
	parent = entry.parent
	content = entry.content

	if "name" in body:
		name = _validated_name(body["name"])
		if name is None:
			return _error("Name is invalid or exceeds 100 characters.", 400)
	if "parent_id" in body:
		parent = _get_parent(entry.workspace, body["parent_id"])
		if parent is False:
			return _error("Parent folder was not found.", 400)
		if entry.kind == FileEntry.Kind.FOLDER:
			ancestor = parent
			while ancestor is not None:
				if ancestor.id == entry.id:
					return _error("A folder cannot be moved into itself or its descendants.", 400)
				ancestor = ancestor.parent
	if "content" in body:
		if entry.kind != FileEntry.Kind.FILE or not _valid_content(body["content"]):
			return _error("File content must be a JSON object or array under 1 MB.", 400)
		content = body["content"]

	try:
		with transaction.atomic():
			Workspace.objects.select_for_update().get(id=entry.workspace_id)
			if _name_conflicts(entry.workspace, parent, name, entry.id):
				return _error("An item with that name already exists in this folder.", 409)
			entry.name = name
			entry.parent = parent
			entry.content = content
			entry.save(update_fields=["name", "parent", "content", "updated_at"])
	except IntegrityError:
		return _error("An item with that name already exists in this folder.", 409)
	return JsonResponse(_serialize(entry))