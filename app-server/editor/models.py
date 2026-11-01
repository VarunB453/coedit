import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


def empty_document():
	return {"type": "doc", "content": [{"type": "paragraph"}]}


class Workspace(models.Model):
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	created_at = models.DateTimeField(auto_now_add=True)


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
