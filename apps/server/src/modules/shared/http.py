import json

from django.http import JsonResponse


def error(message, status):
	return JsonResponse({"error": message}, status=status)


def parse_json_object(request, max_bytes):
	if len(request.body) > max_bytes:
		return None
	try:
		body = json.loads(request.body or b"{}")
	except (json.JSONDecodeError, UnicodeDecodeError):
		return None
	return body if isinstance(body, dict) else None