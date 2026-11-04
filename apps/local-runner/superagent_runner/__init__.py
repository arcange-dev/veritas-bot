"""SuperAgent local runner.

Design constraints, in priority order:
  1. Outbound connection only. The runner never listens on a port.
  2. The user, not the server, decides which directories are reachable.
  3. Every command passes a local deny-list that the server cannot override.
  4. Child processes never inherit the runner's own credentials.
"""

__version__ = "0.1.0"
MIN_SUPPORTED_VERSION = "0.1.0"
