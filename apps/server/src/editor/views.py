import json
import hashlib
import logging
import re
import secrets
import uuid
from datetime import timedelta
from math import ceil

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
	FileEntry, Notification,
	Workspace, WorkspaceMembership, WorkspaceShareLink,
)
from .models import empty_document
from .ai import stream_completion
from modules.auth.views import auth_profile, auth_session, csrf_token, display_name as _display_name, end_session, register, user_payload as _user_payload
from modules.ai import views as ai_views
from modules.collaboration.views import document_comments, document_history, document_version
from modules.notifications.views import notifications
from modules.shared.http import error as _error, parse_json_object
from modules.shared.permissions import is_authenticated as _authenticated
from modules.shared.permissions import workspace_role as _workspace_role


MAX_NAME_LENGTH = 100
MAX_CONTENT_BYTES = 1_000_000
MAX_COMMENT_LENGTH = 4000
logger = logging.getLogger(__name__)


def ai_providers(request):
	return ai_views.ai_providers(request)


def ai_completion(request, workspace_id, file_id):
	return ai_views.ai_completion(request, workspace_id, file_id, stream_completion)


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
		links = WorkspaceShareLink.objects.filter(
			Q(workspace=workspace, revoked_at__isnull=True)
			& (Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
		)
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
	return parse_json_object(request, MAX_CONTENT_BYTES + 4096)


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