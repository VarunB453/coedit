import hashlib
import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from editor.models import DocumentComment, DocumentVersion, FileEntry, Notification, WorkspaceMembership
from modules.auth.views import display_name
from modules.shared.http import error, parse_json_object
from modules.shared.permissions import is_authenticated, workspace_role


MAX_COMMENT_LENGTH = 4000


def _member_document(request, workspace_id, file_id):
	if not is_authenticated(request):
		return None, None, error("Authentication required.", 401)
	try:
		entry = FileEntry.objects.select_related("workspace").get(
			id=file_id, workspace_id=workspace_id, kind=FileEntry.Kind.FILE
		)
	except FileEntry.DoesNotExist:
		return None, None, error("Document was not found.", 404)
	role = workspace_role(entry.workspace, request.user)
	if role is None:
		return None, None, error("Document was not found.", 404)
	return entry, role, None


@require_http_methods(["GET", "POST"])
def document_comments(request, workspace_id, file_id):
	entry, _, response_error = _member_document(request, workspace_id, file_id)
	if response_error:
		return response_error
	if request.method == "GET":
		comments = entry.comments.select_related("author__profile").all()
		return JsonResponse([
			{"id": comment.id, "body": comment.body,
			 "author": display_name(comment.author) if comment.author else "Former user",
			 "created_at": comment.created_at.isoformat(),
			 "resolved": comment.resolved_at is not None}
			for comment in comments
		], safe=False)
	body = parse_json_object(request, 1_000_000 + 4096)
	text = body.get("body") if body else None
	if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_COMMENT_LENGTH:
		return error("Comment must be between 1 and 4,000 characters.", 400)
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
		"id": comment.id, "body": comment.body, "author": display_name(request.user),
		"created_at": comment.created_at.isoformat(), "resolved": False,
	}, status=201)


@require_http_methods(["GET", "POST"])
def document_history(request, workspace_id, file_id):
	entry, role, response_error = _member_document(request, workspace_id, file_id)
	if response_error:
		return response_error
	if request.method == "GET":
		versions = entry.versions.select_related("author__profile")[:50]
		return JsonResponse([
			{"id": version.id, "author": display_name(version.author) if version.author else "Former user",
			 "created_at": version.created_at.isoformat()}
			for version in versions
		], safe=False)
	if role == WorkspaceMembership.Role.VIEWER:
		return error("Viewer access is read-only.", 403)
	body = parse_json_object(request, 1_000_000 + 4096)
	content = body.get("content") if body else None
	if not isinstance(content, (dict, list)):
		return error("Version content must be valid JSON under 1 MB.", 400)
	try:
		if len(json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 1_000_000:
			return error("Version content must be valid JSON under 1 MB.", 400)
	except (TypeError, ValueError, UnicodeEncodeError):
		return error("Version content must be valid JSON under 1 MB.", 400)
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
	entry, _, response_error = _member_document(request, workspace_id, file_id)
	if response_error:
		return response_error
	try:
		version = entry.versions.get(id=version_id)
	except DocumentVersion.DoesNotExist:
		return error("Document version was not found.", 404)
	return JsonResponse({"id": version.id, "content": version.content})