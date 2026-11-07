import json
import uuid
from datetime import timedelta
from math import ceil

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from editor.models import (
    DocumentSnapshot,
    FileEntry,
    Workspace,
    WorkspaceMembership,
    empty_document,
)
from modules.shared.http import error as _error, parse_json_object
from modules.shared.permissions import is_authenticated as _authenticated
from modules.shared.permissions import workspace_role as _workspace_role
from modules.shared.validation import validate_name

MAX_CONTENT_BYTES = 1_000_000


@require_http_methods(["GET"])
def search_documents(request):
    if not _authenticated(request):
        return _error("Authentication required.", 401)
    query = request.GET.get("q", "").strip()
    workspace_id = request.GET.get("workspace")
    if len(query) < 2 or len(query) > 100:
        return _error("Search must be between 2 and 100 characters.", 400)
    entries = (
        FileEntry.objects.filter(kind=FileEntry.Kind.FILE)
        .filter(
            Q(workspace__owner=request.user)
            | Q(workspace__memberships__user=request.user)
        )
        .filter(Q(name__icontains=query) | Q(content__icontains=query))
        .select_related("workspace")
    )
    if workspace_id:
        entries = entries.filter(workspace_id=workspace_id)
    results = [
        {
            "id": str(entry.id),
            "name": entry.name,
            "workspace_id": str(entry.workspace_id),
            "workspace_name": entry.workspace.name,
            "updated_at": entry.updated_at.isoformat(),
        }
        for entry in entries.distinct().order_by("-updated_at")[:50]
    ]
    return JsonResponse({"results": results})


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
        if entry.yjs_updates.exists() or DocumentSnapshot.objects.filter(
            document=entry
        ).exists():
            return JsonResponse({"ready": True, "initialize": False})
        if entry.content == empty_document():
            return JsonResponse({"ready": True, "initialize": False})
        now = timezone.now()
        if entry.yjs_initializing_until and entry.yjs_initializing_until > now:
            return JsonResponse(
                {
                    "ready": False,
                    "retry_after": max(
                        1, ceil((entry.yjs_initializing_until - now).total_seconds())
                    ),
                }
            )
        if not can_edit:
            return JsonResponse({"ready": False, "retry_after": 2})
        entry.yjs_initializing_until = now + timedelta(seconds=30)
        entry.save(update_fields=["yjs_initializing_until"])
        return JsonResponse({"ready": True, "initialize": True})


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
        return (
            len(
                json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")
            )
            <= MAX_CONTENT_BYTES
        )
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
        return JsonResponse(
            {"role": role, "entries": [_serialize(entry) for entry in entries]}
        )
    if role == WorkspaceMembership.Role.VIEWER:
        return _error("Viewer access is read-only.", 403)

    body = parse_json_object(request)
    if body is None:
        return _error("Request body must be a JSON object.", 400)
    name = validate_name(body.get("name"))
    kind = body.get("kind")
    parent = _get_parent(workspace, body.get("parent_id"))
    if name is None:
        return _error("Name is invalid or exceeds 100 characters.", 400)
    if kind not in FileEntry.Kind.values:
        return _error("Kind must be 'file' or 'folder'.", 400)
    if parent is False:
        return _error("Parent folder was not found.", 400)
    content = body.get(
        "content", empty_document() if kind == FileEntry.Kind.FILE else {}
    )
    if kind == FileEntry.Kind.FOLDER and content:
        return _error("Folders cannot contain file content.", 400)
    if kind == FileEntry.Kind.FILE and not _valid_content(content):
        return _error("File content must be a JSON object or array under 1 MB.", 400)

    try:
        with transaction.atomic():
            Workspace.objects.select_for_update().get(id=workspace.id)
            if _name_conflicts(workspace, parent, name):
                return _error(
                    "An item with that name already exists in this folder.", 409
                )
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

    body = parse_json_object(request)
    if body is None:
        return _error("Request body must be a JSON object.", 400)
    name = entry.name
    parent = entry.parent
    content = entry.content

    if "name" in body:
        name = validate_name(body["name"])
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
                    return _error(
                        "A folder cannot be moved into itself or its descendants.", 400
                    )
                ancestor = ancestor.parent
    if "content" in body:
        if entry.kind != FileEntry.Kind.FILE or not _valid_content(body["content"]):
            return _error(
                "File content must be a JSON object or array under 1 MB.", 400
            )
        content = body["content"]

    try:
        with transaction.atomic():
            Workspace.objects.select_for_update().get(id=entry.workspace_id)
            if _name_conflicts(entry.workspace, parent, name, entry.id):
                return _error(
                    "An item with that name already exists in this folder.", 409
                )
            entry.name = name
            entry.parent = parent
            entry.content = content
            entry.save(update_fields=["name", "parent", "content", "updated_at"])
    except IntegrityError:
        return _error("An item with that name already exists in this folder.", 409)
    return JsonResponse(_serialize(entry))
