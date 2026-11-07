from editor.models import WorkspaceMembership


def is_authenticated(request):
	return bool(request.user.is_authenticated)


def workspace_role(workspace, user):
	if workspace.owner_id == user.id:
		return "owner"
	membership = WorkspaceMembership.objects.filter(workspace=workspace, user=user).first()
	if membership:
		return membership.role
	return None