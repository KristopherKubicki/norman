import logging
import json
import re
import uuid
import contextvars
from typing import Optional, Union

from fastapi import Request

from .config import settings

request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)
conversation_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "conversation_id", default=None
)


class RequestContextFilter(logging.Filter):
    """Attach request/conversation IDs from contextvars to log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - simple
        record.request_id = request_id_var.get()
        record.conversation_id = conversation_id_var.get()
        return True


class SensitiveDataFilter(logging.Filter):
    """Redact obvious secrets from log messages."""

    _pattern = re.compile(r"(api[_-]?key|token|password|secret)", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - simple
        if isinstance(record.msg, str):
            record.msg = self._pattern.sub("[REDACTED]", record.msg)
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(self._pattern.sub("[REDACTED]", arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        return True


class JSONFormatter(logging.Formatter):
    """Format log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - simple
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "module": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            log_record["request_id"] = record.request_id
        if getattr(record, "conversation_id", None):
            log_record["conversation_id"] = record.conversation_id
        return json.dumps(log_record)


async def request_context_middleware(request: Request, call_next):
    """Middleware to populate request ID for structured logs."""
    req_id = str(uuid.uuid4())
    token = request_id_var.set(req_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = req_id
    return response


def setup_logger(name: str, level: Optional[Union[int, str]] = None) -> logging.Logger:
    """Return a configured :class:`logging.Logger` instance.

    The function is safe to call multiple times for the same ``name``. A
    ``StreamHandler`` is only added if the logger doesn't already have one to
    avoid duplicate log messages when modules import this helper repeatedly.
    """

    logger = logging.getLogger(name)
    if level is None:
        level = settings.log_level
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(level)

    has_stream = any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    if not has_stream:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = JSONFormatter()
        handler.setFormatter(formatter)
        handler.addFilter(RequestContextFilter())
        handler.addFilter(SensitiveDataFilter())
        logger.addHandler(handler)

    return logger
