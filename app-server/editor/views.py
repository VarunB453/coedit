import json
import re
import uuid
from datetime import timedelta
from math import ceil

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import FileEntry, Workspace, WorkspaceMembership
from .models import empty_document


MAX_NAME_LENGTH = 100
MAX_CONTENT_BYTES = 1_000_000


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
def csrf_token(request):
	return JsonResponse({"csrfToken": get_token(request)})


@require_http_methods(["GET", "POST"])
def auth_session(request):
	if request.method == "GET":
		if not _authenticated(request):
			return _error("Authentication required.", 401)
		return JsonResponse({"id": request.user.id, "username": request.user.get_username()})
	body = _parse_body(request)
	if body is None:
		return _error("Request body must be a JSON object.", 400)
	user = authenticate(request, username=body.get("username", ""), password=body.get("password", ""))
	if user is None:
		return _error("Username or password is incorrect.", 401)
	login(request, user)
	return JsonResponse({"id": user.id, "username": user.get_username()})


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
	return JsonResponse({"id": user.id, "username": user.get_username()}, status=201)


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


@require_http_methods(["GET", "POST"])
def workspace_members(request, workspace_id):
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
		if role != "owner":
			return _error("Only the workspace owner can manage members.", 403)
		members = [{"id": workspace.owner_id, "username": workspace.owner.get_username(), "role": "owner"}]
		members.extend(
			{"id": membership.user_id, "username": membership.user.get_username(), "role": membership.role}
			for membership in workspace.memberships.select_related("user").order_by("user__username")
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
	membership, _ = WorkspaceMembership.objects.update_or_create(
		workspace=workspace, user=user, defaults={"role": member_role}
	)
	return JsonResponse({"id": user.id, "username": user.get_username(), "role": membership.role}, status=201)


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


@require_http_methods(["PATCH", "DELETE"])
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