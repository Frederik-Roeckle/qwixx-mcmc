# Logging helpers: everything is written to a log file.
# Worker processes send their records through a multiprocessing queue to the
# main process, which is the only one writing to the file (safe on Windows).

import logging
import logging.handlers
import os
from datetime import datetime

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(processName)s %(name)s: %(message)s"


def default_log_file(prefix):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join("logs", f"{prefix}_{stamp}.log")


def _file_handler(log_file):
    directory = os.path.dirname(log_file)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def setup_logging(log_file, level=logging.INFO):
    """Single process: root logger writes to `log_file`."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(_file_handler(log_file))


def start_queue_listener(log_file, queue, level=logging.INFO):
    """Main process: writes its own and the workers' records to `log_file`.
    Returns the listener; call listener.stop() at the end to flush."""
    setup_logging(log_file, level)
    handler = logging.getLogger().handlers[0]
    listener = logging.handlers.QueueListener(queue, handler, respect_handler_level=True)
    listener.start()
    return listener


def init_worker_logging(queue, level=logging.INFO):
    """Worker process initializer: forward all records to the main process."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(logging.handlers.QueueHandler(queue))
