"""core URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from editor import views as editor_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/csrf/', editor_views.csrf_token),
    path('api/auth/session/', editor_views.auth_session),
    path('api/auth/register/', editor_views.register),
    path('api/auth/logout/', editor_views.end_session),
    path('api/auth/profile/', editor_views.auth_profile),
    path('api/auth/notifications/', editor_views.notifications),
    path('api/search/', editor_views.search_documents),
    path('api/share/<str:token>/accept/', editor_views.accept_share_link),
    path('api/ai/providers/', editor_views.ai_providers),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/ai/', editor_views.ai_completion),
    path('api/workspaces/', editor_views.workspaces),
    path('api/workspaces/<uuid:workspace_id>/', editor_views.workspace_detail),
    path('api/workspaces/<uuid:workspace_id>/members/', editor_views.workspace_members),
    path('api/workspaces/<uuid:workspace_id>/members/<int:user_id>/', editor_views.workspace_member),
    path('api/workspaces/<uuid:workspace_id>/share-links/', editor_views.workspace_share_links),
    path('api/workspaces/<uuid:workspace_id>/share-links/<int:link_id>/', editor_views.workspace_share_link),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/initialize/', editor_views.document_initialization),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/comments/', editor_views.document_comments),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/history/', editor_views.document_history),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/history/<int:version_id>/', editor_views.document_version),
    path('api/workspaces/<uuid:workspace_id>/files/', editor_views.workspace_files),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/', editor_views.workspace_file),
]
