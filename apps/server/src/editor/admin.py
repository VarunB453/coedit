from django.contrib import admin

from .models import DocumentUpdate, FileEntry, Workspace, WorkspaceMembership


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
	list_display = ("id", "name", "owner", "created_at")
	search_fields = ("name", "owner__username", "id")
	autocomplete_fields = ("owner",)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
	list_display = ("workspace", "user", "role", "created_at")
	list_filter = ("role",)
	search_fields = ("workspace__name", "user__username")


@admin.register(FileEntry)
class FileEntryAdmin(admin.ModelAdmin):
	list_display = ("id", "name", "kind", "workspace", "updated_at")
	search_fields = ("name", "id", "workspace__name")


@admin.register(DocumentUpdate)
class DocumentUpdateAdmin(admin.ModelAdmin):
	list_display = ("id", "document", "author", "created_at")
	readonly_fields = ("document", "author", "update_hash", "update", "created_at")
