import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django_asgi_app = get_asgi_application()

try:
    from channels.routing import ProtocolTypeRouter, URLRouter

    from core.channels_auth import RunnerAuthMiddleware
    from execution.routing import websocket_urlpatterns

    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": RunnerAuthMiddleware(URLRouter(websocket_urlpatterns)),
    })
except ImportError:      # channels not installed in minimal environments
    application = django_asgi_app
