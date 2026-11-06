import uuid

from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q
from django.db.models.functions import Lower
import editor.models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="FileEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100)),
                ("kind", models.CharField(choices=[("file", "File"), ("folder", "Folder")], max_length=10)),
                ("content", models.JSONField(blank=True, default=editor.models.empty_document)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="children", to="editor.fileentry")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="editor.workspace")),
            ],
            options={"ordering": ("kind", "name")},
        ),
        migrations.AddConstraint(
            model_name="fileentry",
            constraint=models.UniqueConstraint(Lower("name"), "workspace", condition=Q(parent__isnull=True), name="uniq_root_name_per_ws"),
        ),
        migrations.AddConstraint(
            model_name="fileentry",
            constraint=models.UniqueConstraint(Lower("name"), "workspace", "parent", condition=Q(parent__isnull=False), name="uniq_child_name_per_parent"),
        ),
    ]