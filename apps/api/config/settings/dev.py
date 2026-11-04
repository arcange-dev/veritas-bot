from .base import *  # noqa: F401,F403
from .base import env_bool

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True          # dev only
GRAPH_RECURSION_LIMIT = 40
