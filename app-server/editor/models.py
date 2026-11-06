import uuid
import hashlib

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
	updated_at = models.DateTimeField(auto_now=True)


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


class UserProfile(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
	display_name = models.CharField(max_length=100, blank=True)

	def __str__(self):
		return self.display_name or self.user.get_username()


class WorkspaceShareLink(models.Model):
	workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="share_links")
	token_hash = models.CharField(max_length=64, unique=True)
	role = models.CharField(max_length=10, choices=WorkspaceMembership.Role.choices)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="created_share_links")
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField(null=True, blank=True)
	revoked_at = models.DateTimeField(null=True, blank=True)

	@staticmethod
	def digest(token):
		return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DocumentComment(models.Model):
	document = models.ForeignKey(FileEntry, on_delete=models.CASCADE, related_name="comments")
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="document_comments")
	body = models.TextField(max_length=4000)
	created_at = models.DateTimeField(auto_now_add=True)
	resolved_at = models.DateTimeField(null=True, blank=True)
	resolved_by = models.ForeignKey(
		settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
		related_name="resolved_document_comments",
	)

	class Meta:
		ordering = ("created_at",)


class DocumentVersion(models.Model):
	document = models.ForeignKey(FileEntry, on_delete=models.CASCADE, related_name="versions")
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="document_versions")
	content = models.JSONField()
	content_hash = models.CharField(max_length=64)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ("-created_at", "-id")
		constraints = [
			models.UniqueConstraint(fields=("document", "content_hash"), name="uniq_document_version_hash")
		]


class Notification(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
	workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="notifications")
	kind = models.CharField(max_length=30)
	message = models.CharField(max_length=255)
	document = models.ForeignKey(FileEntry, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
	created_at = models.DateTimeField(auto_now_add=True)
	read_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ("-created_at", "-id")