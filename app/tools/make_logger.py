import logging
import sys
import io


def simple_logger(name,
                  logging_format: str = logging.BASIC_FORMAT,
                  output_stream: io.TextIOWrapper = sys.stderr,
                  log_level: int = logging.DEBUG,
                  filename: str | None = None) -> logging.Logger:
    """
    Returns a logger which logs to a stream (default stderr) by default and to a file if a filename is given.

    :param name: logger name
    :param logging_format: format string in accordance with the python logging library
    :param output_stream: system output stream, e.g. sys.stdout, sys.stderr
    :param log_level: log level as defined by the logging builtin
    :param filename: if given, creates a log file with the given name

    :return: logging.Logger with the desired configuration
    """
    root = logging.getLogger(name=name)

    formatter = logging.Formatter(logging_format)

    if filename:
        file_handler = logging.FileHandler(filename=filename)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(output_stream)
    stream_handler.setFormatter(formatter)

    root.addHandler(stream_handler)
    root.debug(f"created logger {name}")

    root.setLevel(log_level)
    return root

