"""
Tests for app.tools.make_logger.

The frontend's live log streaming attaches a queue handler to the root
logger, so simple_logger loggers must keep propagate=True.
"""
import logging

from app.tools.make_logger import simple_logger


class TestSimpleLogger:
    def test_idempotent_no_handler_stacking(self):
        first = simple_logger("test_make_logger_idem")
        handler_count = len(first.handlers)
        second = simple_logger("test_make_logger_idem")
        assert first is second
        assert len(second.handlers) == handler_count

    def test_default_level_is_info(self):
        lg = simple_logger("test_make_logger_level")
        assert lg.level == logging.INFO

    def test_propagation_stays_enabled_for_sse_streaming(self):
        lg = simple_logger("test_make_logger_propagate")
        assert lg.propagate is True
