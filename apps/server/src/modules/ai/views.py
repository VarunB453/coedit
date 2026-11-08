import json
import logging
import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from editor.ai import (
    ACTION_INSTRUCTIONS,
    PROVIDERS,
    available_providers,
    build_messages,
    daily_request_limit,
    stream_completion,
)
from editor.models import AIConversation, AIUsage, FileEntry
from modules.ai.retrieval import (
    WorkspaceTooLargeError,
    retrieve_workspace_context,
)
from modules.shared.http import error, parse_json_object
from modules.shared.permissions import is_authenticated, workspace_role

logger = logging.getLogger(__name__)
MAX_CONTEXT_LENGTH = 60_000
MAX_PROMPT_LENGTH = 4_000
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARACTERS = 24_000


def _member_document(request, workspace_id, file_id):
    if not is_authenticated(request):
        return None, error("Authentication required.", 401)
    try:
        entry = FileEntry.objects.select_related("workspace").get(
            id=file_id, workspace_id=workspace_id, kind=FileEntry.Kind.FILE
        )
    except FileEntry.DoesNotExist:
        return None, error("Document was not found.", 404)
    if workspace_role(entry.workspace, request.user) is None:
        return None, error("Document was not found.", 404)
    return entry, None


def _bounded_history(messages):
    selected = []
    total_characters = 0
    for message in reversed(messages[-MAX_HISTORY_MESSAGES:]):
        if (
            not isinstance(message, dict)
            or message.get("role") not in {"user", "assistant"}
            or not isinstance(message.get("content"), str)
        ):
            continue
        content = message["content"]
        if total_characters + len(content) > MAX_HISTORY_CHARACTERS:
            break
        selected.insert(0, {"role": message["role"], "content": content})
        total_characters += len(content)
    return selected


def _save_chat_turn(conversation_id, user, entry, prompt, answer):
    with transaction.atomic():
        conversation = AIConversation.objects.select_for_update().get(
            id=conversation_id,
            user=user,
            workspace=entry.workspace,
            document=entry,
        )
        messages = list(conversation.messages)
        messages.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ]
        )
        conversation.messages = messages[-MAX_HISTORY_MESSAGES:]
        conversation.save(update_fields=["messages", "updated_at"])


def _reserve_usage(request, entry, provider, input_characters):
    limit = daily_request_limit()
    now = timezone.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    User = get_user_model()
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        requests_today = AIUsage.objects.filter(
            user=request.user, created_at__gte=day_start
        ).count()
        if requests_today >= limit:
            return None, limit
        config = PROVIDERS[provider]
        usage = AIUsage.objects.create(
            user=request.user,
            workspace=entry.workspace,
            document=entry,
            provider=provider,
            model=os.environ.get(config["model_env"], config["default_model"]),
            input_characters=input_characters,
        )
    return usage, limit


@require_http_methods(["GET"])
def ai_providers(request):
    if not is_authenticated(request):
        return error("Authentication required.", 401)
    return JsonResponse({"providers": available_providers()})


@require_http_methods(["GET"])
def ai_usage(request):
    if not is_authenticated(request):
        return error("Authentication required.", 401)
    try:
        limit = daily_request_limit()
    except RuntimeError as configuration_error:
        logger.error("Invalid AI quota configuration: %s", configuration_error)
        return error("AI usage limits are not configured correctly.", 503)
    day_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    usage = AIUsage.objects.filter(user=request.user, created_at__gte=day_start)
    requests_today = usage.count()
    return JsonResponse(
        {
            "requests_today": requests_today,
            "daily_request_limit": limit,
            "remaining_requests": max(0, limit - requests_today),
            "output_characters_today": sum(
                usage.values_list("output_characters", flat=True)
            ),
        }
    )


@require_http_methods(["GET", "DELETE"])
def ai_conversation(request, workspace_id, file_id):
    entry, response_error = _member_document(request, workspace_id, file_id)
    if response_error:
        return response_error
    conversation = AIConversation.objects.filter(
        user=request.user, workspace=entry.workspace, document=entry
    ).first()
    if request.method == "DELETE":
        if conversation is not None:
            conversation.messages = []
            conversation.save(update_fields=["messages", "updated_at"])
        return JsonResponse({"messages": []})
    return JsonResponse(
        {
            "conversation_id": str(conversation.id) if conversation else None,
            "messages": _bounded_history(conversation.messages) if conversation else [],
        }
    )


@require_http_methods(["POST"])
def ai_completion(request, workspace_id, file_id, completion_stream=None):
    if not is_authenticated(request):
        return error("Authentication required.", 401)
    body = parse_json_object(request)
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
    context = body.get("context", "")
    prompt = body.get("prompt", "")
    if not isinstance(provider, str) or provider not in PROVIDERS:
        return error("AI provider is invalid.", 400)
    if not any(item["id"] == provider for item in available_providers()):
        return error(
            "Choose an AI provider configured by your workspace administrator.", 503
        )
    if not isinstance(action, str) or action not in ACTION_INSTRUCTIONS:
        return error("AI action is invalid.", 400)
    if (
        not isinstance(context, str)
        or len(context) > MAX_CONTEXT_LENGTH
        or not isinstance(prompt, str)
        or len(prompt) > MAX_PROMPT_LENGTH
    ):
        return error("AI request exceeds the supported size.", 400)
    if not prompt.strip() and action not in {"summarize", "grammar", "insights"}:
        return error("Enter an instruction or question.", 400)

    sources = []
    if action == "workspace_search":
        try:
            sources = retrieve_workspace_context(entry.workspace_id, prompt)
        except WorkspaceTooLargeError:
            return error(
                "Workspace search is limited to 500 documents. Narrow this workspace before searching.",
                413,
            )
        context = "\n\n".join(
            f"[Document: {source['name']}]\n{source['excerpt']}" for source in sources
        )
        if not context:
            context = "(No matching passages were found in this workspace.)"

    conversation = None
    history = []
    if action == "chat":
        conversation, _ = AIConversation.objects.get_or_create(
            user=request.user,
            workspace=entry.workspace,
            document=entry,
        )
        history = _bounded_history(conversation.messages)
    messages = build_messages(action, entry.name, context, prompt, history)
    input_characters = sum(len(message["content"]) for message in messages)
    try:
        usage, limit = _reserve_usage(request, entry, provider, input_characters)
    except RuntimeError as configuration_error:
        logger.error("Invalid AI quota configuration: %s", configuration_error)
        return error("AI usage limits are not configured correctly.", 503)
    if usage is None:
        return JsonResponse(
            {
                "error": "Daily AI request limit reached.",
                "daily_request_limit": limit,
            },
            status=429,
        )

    stream = completion_stream or stream_completion

    def events():
        output = []
        status = AIUsage.Status.PENDING
        iterator = None
        try:
            if sources:
                yield (
                    "event: sources\n"
                    f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"
                )
            iterator = iter(stream(provider, messages))
            for text in iterator:
                if not isinstance(text, str):
                    continue
                output.append(text)
                usage.output_characters += len(text)
                yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
            answer = "".join(output)
            if not answer.strip():
                raise RuntimeError("The AI provider returned an empty response.")
            if conversation is not None:
                _save_chat_turn(
                    conversation.id, request.user, entry, prompt, answer
                )
            status = AIUsage.Status.COMPLETED
            yield 'data: {"done":true}\n\n'
        except GeneratorExit:
            status = AIUsage.Status.CANCELLED
            raise
        except RuntimeError as provider_error:
            status = AIUsage.Status.FAILED
            logger.warning("AI provider stream failed: %s", provider_error)
            yield (
                "event: error\n"
                f"data: {json.dumps({'error': str(provider_error)}, ensure_ascii=False)}\n\n"
            )
        finally:
            close = getattr(iterator, "close", None)
            if close:
                close()
            usage.status = status
            usage.save(update_fields=["status", "output_characters"])

    response = StreamingHttpResponse(
        events(), content_type="text/event-stream; charset=utf-8"
    )
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response
