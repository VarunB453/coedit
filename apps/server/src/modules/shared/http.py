import json

from django.http import JsonResponse

DEFAULT_JSON_BODY_LIMIT = 1_004_096


def error(message, status):
    return JsonResponse({"error": message}, status=status)


def parse_json_object(request, max_bytes=DEFAULT_JSON_BODY_LIMIT):
    if len(request.body) > max_bytes:
        return None
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None
