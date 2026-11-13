import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# django
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

# channels
from channels.security.websocket import OriginValidator
from channels.routing import ProtocolTypeRouter
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from django.conf import settings

# local
from editor.socket.routing import websocket_urlpatterns


application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": OriginValidator(
        AuthMiddlewareStack(
            URLRouter(
                websocket_urlpatterns
            )
        ),
        settings.CORS_ALLOWED_ORIGINS,
    ),
})
