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
    path('api/workspaces/', editor_views.workspaces),
    path('api/workspaces/<uuid:workspace_id>/members/', editor_views.workspace_members),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/initialize/', editor_views.document_initialization),
    path('api/workspaces/<uuid:workspace_id>/files/', editor_views.workspace_files),
    path('api/workspaces/<uuid:workspace_id>/files/<uuid:file_id>/', editor_views.workspace_file),
]
