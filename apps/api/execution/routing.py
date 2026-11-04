from django.urls import path

from execution.consumers import RunnerConsumer, TerminalConsumer

websocket_urlpatterns = [
    path("ws/runner/", RunnerConsumer.as_asgi()),
    path("ws/sessions/<uuid:session_id>/", TerminalConsumer.as_asgi()),
]
