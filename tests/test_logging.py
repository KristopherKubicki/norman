import logging
from app.core.logging import setup_logger


def test_setup_logger_idempotent():
    name = "test_setup_logger_idempotent"
    logger1 = setup_logger(name)
    initial_handlers = list(logger1.handlers)
    # call again to ensure no duplicate handlers are added
    logger2 = setup_logger(name)
    assert logger1 is logger2
    assert logger1.handlers == initial_handlers
    # ensure exactly one StreamHandler is attached
    stream_handlers = [h for h in logger1.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) == 1
    # cleanup
    for handler in list(logger1.handlers):
        logger1.removeHandler(handler)


def test_setup_logger_level_from_settings(monkeypatch):
    name = "test_setup_logger_level_from_settings"
    from app.core import config

    old_level = config.settings.log_level
    monkeypatch.setattr(config.settings, "log_level", "WARNING")
    try:
        logger = setup_logger(name)
        assert logger.level == logging.WARNING
    finally:
        monkeypatch.setattr(config.settings, "log_level", old_level)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)


def test_setup_logger_explicit_level():
    name = "test_setup_logger_explicit_level"
    logger = setup_logger(name, level="ERROR")
    assert logger.level == logging.ERROR
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
