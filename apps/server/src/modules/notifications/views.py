from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from editor.models import Notification
from modules.shared.http import error
from modules.shared.permissions import is_authenticated


@require_http_methods(["GET", "POST"])
def notifications(request):
	if not is_authenticated(request):
		return error("Authentication required.", 401)
	if request.method == "POST":
		Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
		return JsonResponse({})
	return JsonResponse([
		{"id": item.id, "kind": item.kind, "message": item.message,
		 "workspace_id": str(item.workspace_id), "document_id": str(item.document_id) if item.document_id else None,
		 "created_at": item.created_at.isoformat(), "read": item.read_at is not None}
		for item in request.user.notifications.select_related("workspace", "document")[:50]
	], safe=False)