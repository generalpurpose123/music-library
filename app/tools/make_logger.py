import logging
import sys
import io


def simple_logger(name,
                  logging_format: str = logging.BASIC_FORMAT,
                  output_stream: io.TextIOWrapper = sys.stderr,
                  log_level: int = logging.INFO,
                  filename: str | None = None) -> logging.Logger:
    """
    Returns a logger which logs to a stream (default stderr) by default and to a file if a filename is given.

    Idempotent: calling it again with the same name returns the already
    configured logger without stacking handlers. Propagation stays enabled —
    the web frontend attaches a queue handler to the root logger and relies
    on records propagating up for its live log streaming.

    :param name: logger name
    :param logging_format: format string in accordance with the python logging library
    :param output_stream: system output stream, e.g. sys.stdout, sys.stderr
    :param log_level: log level as defined by the logging builtin
    :param filename: if given, creates a log file with the given name

    :return: logging.Logger with the desired configuration
    """
    logger_ = logging.getLogger(name=name)
    if getattr(logger_, "_simple_logger_configured", False):
        return logger_

    formatter = logging.Formatter(logging_format)

    if filename:
        file_handler = logging.FileHandler(filename=filename)
        file_handler.setFormatter(formatter)
        logger_.addHandler(file_handler)

    stream_handler = logging.StreamHandler(output_stream)
    stream_handler.setFormatter(formatter)
    logger_.addHandler(stream_handler)

    logger_.setLevel(log_level)
    logger_._simple_logger_configured = True
    return logger_
