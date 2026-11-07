import secrets
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from editor.models import (
    Notification,
    Workspace,
    WorkspaceMembership,
    WorkspaceShareLink,
)
from modules.auth.views import display_name as _display_name
from modules.shared.http import error as _error, parse_json_object
from modules.shared.permissions import is_authenticated as _authenticated
from modules.shared.permissions import workspace_role as _workspace_role
from modules.shared.validation import validate_name


@require_http_methods(["GET", "POST"])
def workspaces(request):
    if not _authenticated(request):
        return _error("Authentication required.", 401)
    if request.method == "GET":
        workspaces = Workspace.objects.filter(
            owner=request.user
        ) | Workspace.objects.filter(memberships__user=request.user)
        return JsonResponse(
            [
                {
                    "id": str(workspace.id),
                    "name": workspace.name,
                    "role": _workspace_role(workspace, request.user),
                }
                for workspace in workspaces.distinct().order_by("created_at")
            ],
            safe=False,
        )
    body = parse_json_object(request)
    if body is None:
        return _error("Request body must be a JSON object.", 400)
    name = validate_name(body.get("name", "Workspace"))
    if name is None:
        return _error("Workspace name is invalid.", 400)
    workspace = Workspace.objects.create(name=name, owner=request.user)
    return JsonResponse(
        {"id": str(workspace.id), "name": workspace.name, "role": "owner"}, status=201
    )


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
    body = parse_json_object(request)
    if body is None or set(body) != {"name"}:
        return _error("Provide a valid workspace name.", 400)
    name = validate_name(body.get("name"))
    if name is None:
        return _error("Workspace name is invalid.", 400)
    workspace.name = name
    workspace.save(update_fields=["name", "updated_at"])
    return JsonResponse(
        {"id": str(workspace.id), "name": workspace.name, "role": "owner"}
    )


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
        return JsonResponse(
            [
                {
                    "id": link.id,
                    "role": link.role,
                    "created_at": link.created_at.isoformat(),
                    "expires_at": (
                        link.expires_at.isoformat() if link.expires_at else None
                    ),
                }
                for link in links.order_by("-created_at")
            ],
            safe=False,
        )
    body = parse_json_object(request)
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
    return JsonResponse(
        {
            "id": link.id,
            "role": link.role,
            "token": token,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        },
        status=201,
    )


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
    link = (
        WorkspaceShareLink.objects.select_related("workspace")
        .filter(token_hash=WorkspaceShareLink.digest(token), revoked_at__isnull=True)
        .first()
    )
    if link is None or (link.expires_at and link.expires_at <= timezone.now()):
        return _error("This sharing link is invalid or expired.", 404)
    if link.workspace.owner_id == request.user.id:
        return JsonResponse({"workspace_id": str(link.workspace_id), "role": "owner"})
    WorkspaceMembership.objects.update_or_create(
        workspace=link.workspace, user=request.user, defaults={"role": link.role}
    )
    if link.workspace.owner_id:
        Notification.objects.create(
            user_id=link.workspace.owner_id,
            workspace=link.workspace,
            kind="member_joined",
            message=f"{request.user.get_username()} joined {link.workspace.name}.",
        )
    return JsonResponse({"workspace_id": str(link.workspace_id), "role": link.role})


@require_http_methods(["GET", "POST"])
def workspace_members(request, workspace_id):
    if not _authenticated(request):
        return _error("Authentication required.", 401)
    try:
        workspace = Workspace.objects.select_related("owner__profile").get(
            id=workspace_id
        )
    except Workspace.DoesNotExist:
        return _error("Workspace was not found.", 404)
    role = _workspace_role(workspace, request.user)
    if role is None:
        return _error("Workspace was not found.", 404)
    if request.method == "GET":
        if role != "owner":
            return _error("Only the workspace owner can manage members.", 403)
        members = [
            {
                "id": workspace.owner_id,
                "username": workspace.owner.get_username(),
                "display_name": _display_name(workspace.owner),
                "role": "owner",
            }
        ]
        members.extend(
            {
                "id": membership.user_id,
                "username": membership.user.get_username(),
                "display_name": _display_name(membership.user),
                "role": membership.role,
            }
            for membership in workspace.memberships.select_related(
                "user__profile"
            ).order_by("user__username")
        )
        return JsonResponse(members, safe=False)
    if role != "owner":
        return _error("Only the workspace owner can manage members.", 403)
    body = parse_json_object(request)
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
    previous_role = (
        WorkspaceMembership.objects.filter(workspace=workspace, user=user)
        .values_list("role", flat=True)
        .first()
    )
    membership, created = WorkspaceMembership.objects.update_or_create(
        workspace=workspace, user=user, defaults={"role": member_role}
    )
    if previous_role != membership.role:
        Notification.objects.create(
            user=user,
            workspace=workspace,
            kind="workspace_access",
            message=f"{workspace.name} shared with you as {membership.role}.",
        )
    if not created:
        async_to_sync(get_channel_layer().group_send)(
            f"editor_user_{user.id}", {"type": "editor_access_changed"}
        )
    return JsonResponse(
        {"id": user.id, "username": user.get_username(), "role": membership.role},
        status=201,
    )


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
        membership = WorkspaceMembership.objects.get(
            workspace=workspace, user_id=user_id
        )
    except WorkspaceMembership.DoesNotExist:
        return _error("Workspace member was not found.", 404)
    membership.delete()
    async_to_sync(get_channel_layer().group_send)(
        f"editor_user_{user_id}", {"type": "editor_access_changed"}
    )
    return JsonResponse({})
