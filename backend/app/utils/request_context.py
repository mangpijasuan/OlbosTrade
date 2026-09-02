"""
Request-scoped correlation ID, threaded into every log line via a
logging.Filter in logger.py. Set by RequestIDMiddleware for HTTP requests
and by _guarded() for background scheduler ticks — anything logged outside
either context (e.g. at import time) falls back to "-".
"""

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
