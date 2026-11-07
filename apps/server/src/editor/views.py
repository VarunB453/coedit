from .ai import stream_completion
from modules.ai import views as ai_views
from modules.auth.views import (
    auth_profile,
    auth_session,
    csrf_token,
    display_name as _display_name,
    end_session,
    register,
    user_payload as _user_payload,
)
from modules.collaboration.views import (
    MAX_COMMENT_LENGTH,
    document_comments,
    document_history,
    document_version,
)
from modules.documents.views import (
    document_initialization,
    search_documents,
    workspace_file,
    workspace_files,
)
from modules.notifications.views import notifications
from modules.shared.http import error as _error, parse_json_object
from modules.shared.permissions import is_authenticated as _authenticated
from modules.shared.permissions import workspace_role as _workspace_role
from modules.shared.validation import MAX_NAME_LENGTH
from modules.workspaces.views import (
    accept_share_link,
    workspace_detail,
    workspace_member,
    workspace_members,
    workspace_share_link,
    workspace_share_links,
    workspaces,
)

MAX_CONTENT_BYTES = 1_000_000


def _parse_body(request):
    return parse_json_object(request)


def ai_providers(request):
    return ai_views.ai_providers(request)


def ai_completion(request, workspace_id, file_id):
    return ai_views.ai_completion(request, workspace_id, file_id, stream_completion)
