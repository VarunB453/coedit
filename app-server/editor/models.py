import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


def empty_document():
	return {"type": "doc", "content": [{"type": "paragraph"}]}


class Workspace(models.Model):
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	name = models.CharField(max_length=100, default="Untitled workspace")
	owner = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="owned_workspaces",
	)
	created_at = models.DateTimeField(auto_now_add=True)


class WorkspaceMembership(models.Model):
	class Role(models.TextChoices):
		EDITOR = "editor", "Editor"
		VIEWER = "viewer", "Viewer"

	workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships")
	role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=("workspace", "user"), name="uniq_workspace_member")
		]


class FileEntry(models.Model):
	class Kind(models.TextChoices):
		FILE = "file", "File"
		FOLDER = "folder", "Folder"

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="entries")
	parent = models.ForeignKey(
		"self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
	)
	name = models.CharField(max_length=100)
	kind = models.CharField(max_length=10, choices=Kind.choices)
	content = models.JSONField(default=empty_document, blank=True)
	yjs_initializing_until = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ("kind", "name")
		constraints = [
			models.UniqueConstraint(
				Lower("name"), "workspace", condition=Q(parent__isnull=True), name="uniq_root_name_per_ws"
			),
			models.UniqueConstraint(
				Lower("name"), "workspace", "parent", condition=Q(parent__isnull=False), name="uniq_child_name_per_parent"
			),
		]


class DocumentUpdate(models.Model):
	document = models.ForeignKey(FileEntry, on_delete=models.CASCADE, related_name="yjs_updates")
	author = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="document_updates",
	)
	update_hash = models.CharField(max_length=64)
	update = models.BinaryField()
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ("id",)
		constraints = [
			models.UniqueConstraint(fields=("document", "update_hash"), name="uniq_document_yjs_update")
		]