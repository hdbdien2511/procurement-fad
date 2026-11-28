from contextvars import ContextVar

audit_context: ContextVar[dict | None] = ContextVar("audit_context", default=None)
