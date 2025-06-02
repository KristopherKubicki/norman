import logging
from typing import Optional, Union

from .config import settings

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
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
