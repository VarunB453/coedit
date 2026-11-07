import json
import logging

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods

from editor.ai import ACTION_INSTRUCTIONS, PROVIDERS, available_providers, build_messages, stream_completion
from editor.models import FileEntry
from modules.shared.http import error, parse_json_object
from modules.shared.permissions import is_authenticated, workspace_role


logger = logging.getLogger(__name__)
MAX_NAME_LENGTH = 100


@require_http_methods(["GET"])
def ai_providers(request):
	if not is_authenticated(request):
		return error("Authentication required.", 401)
	return JsonResponse({"providers": available_providers()})


@require_http_methods(["POST"])
def ai_completion(request, workspace_id, file_id):
	if not is_authenticated(request):
		return error("Authentication required.", 401)
	body = parse_json_object(request, 1_000_000 + 4096)
	if body is None:
		return error("Request body must be a JSON object.", 400)
	try:
		entry = FileEntry.objects.select_related("workspace").get(
			id=file_id, workspace_id=workspace_id, kind=FileEntry.Kind.FILE
		)
	except FileEntry.DoesNotExist:
		return error("Document was not found.", 404)
	if workspace_role(entry.workspace, request.user) is None:
		return error("Document was not found.", 404)

	provider = body.get("provider")
	action = body.get("action")
	document_name = body.get("document_name", entry.name)
	context = body.get("context", "")
	prompt = body.get("prompt", "")
	history = body.get("history", [])
	if not isinstance(provider, str) or provider not in PROVIDERS:
		return error("AI provider is invalid.", 400)
	if not any(item["id"] == provider for item in available_providers()):
		return error("Choose an AI provider configured by your workspace administrator.", 503)
	if not isinstance(action, str) or action not in ACTION_INSTRUCTIONS:
		return error("AI action is invalid.", 400)
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
		return error("AI request exceeds the supported size.", 400)
	if any(
		not isinstance(message, dict)
		or message.get("role") not in {"user", "assistant"}
		or not isinstance(message.get("content"), str)
		or len(message["content"]) > 4000
		for message in history
	):
		return error("Conversation history is invalid.", 400)
	if not prompt.strip() and action not in {"summarize", "grammar", "insights"}:
		return error("Enter an instruction or question.", 400)

	messages = build_messages(action, document_name, context, prompt, history)

	def events():
		try:
			for text in stream_completion(provider, messages):
				yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
			yield "data: {\"done\":true}\n\n"
		except RuntimeError as error:
			logger.warning("AI provider stream failed: %s", error)
			yield f"event: error\ndata: {json.dumps({'error': str(error)})}\n\n"

	response = StreamingHttpResponse(events(), content_type="text/event-stream; charset=utf-8")
	response["Cache-Control"] = "no-cache, no-transform"
	response["X-Accel-Buffering"] = "no"
	return response