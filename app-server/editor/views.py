import json
import re
import uuid

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import FileEntry, Workspace
from .models import empty_document


MAX_NAME_LENGTH = 100
MAX_CONTENT_BYTES = 1_000_000


def _error(message, status):
	return JsonResponse({"error": message}, status=status)


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
	workspace, _ = Workspace.objects.get_or_create(id=workspace_id)

	if request.method == "GET":
		entries = FileEntry.objects.filter(workspace=workspace).select_related("parent")
		return JsonResponse([_serialize(entry) for entry in entries], safe=False)

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
	try:
		entry = FileEntry.objects.select_related("workspace", "parent").get(
			id=file_id, workspace_id=workspace_id
		)
	except FileEntry.DoesNotExist:
		return _error("File or folder was not found.", 404)

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
