import logging

def setup_logger(name: str) -> logging.Logger:
    """Return a configured :class:`logging.Logger` instance.

    The function is safe to call multiple times for the same ``name``. A
    ``StreamHandler`` is only added if the logger doesn't already have one to
    avoid duplicate log messages when modules import this helper repeatedly.
    """

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    has_stream = any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    if not has_stream:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
