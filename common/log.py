import logging
import os
import sys
import io
import re
import traceback


_SECRET_FIELD = re.compile(
    r'(?i)(["\']?(?:password|token|api[_-]?key|cookie|authorization|client[_-]?secret|access[_-]?token)["\']?\s*[:=]\s*)(["\']?)([^\s,}"\']+)',
)
_BEARER = re.compile(r'(?i)\bBearer\s+[^\s,;]+')


class _SecretFilter(logging.Filter):
    def filter(self, record):
        message = _redact(record.getMessage())
        record.msg = message
        record.args = ()
        if record.exc_info:
            record.exc_text = _redact(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return True


def _redact(message):
    message = _BEARER.sub('Bearer [REDACTED]', message)
    return _SECRET_FIELD.sub(r'\1\2[REDACTED]', message)


def _log_path():
    # Mirror config.get_data_root() without importing config (avoids a circular
    # import, since config imports this module). The desktop build sets
    # STELLA_DATA_DIR (e.g. ~/.stella); source deployments fall back to CWD.
    data_dir = os.environ.get("STELLA_DATA_DIR")
    if data_dir:
        data_dir = os.path.expanduser(data_dir)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "run.log")
    return "run.log"


def _reset_logger(log):
    for handler in log.handlers:
        handler.close()
        log.removeHandler(handler)
        del handler
    log.handlers.clear()
    log.propagate = False
    stdout = sys.stdout
    if hasattr(stdout, "buffer"):
        stdout = io.TextIOWrapper(stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    console_handle = logging.StreamHandler(stdout)
    console_handle.addFilter(_SecretFilter())
    console_handle.setFormatter(
        logging.Formatter(
            "[%(levelname)s][%(asctime)s][%(filename)s:%(lineno)d] - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(console_handle)
    # The Electron shell persists the backend's stdout/stderr to run.log.
    # Writing the same record here would duplicate every packaged-app log.
    if os.environ.get("STELLA_LOG_MIRRORED_BY_SHELL") == "1":
        return
    # File logging is best-effort: if the log path isn't writable (e.g. a
    # packaged app installed under Program Files run by a non-admin user, with
    # an unwritable CWD), fall back to console-only instead of crashing the
    # whole process at import time.
    try:
        file_handle = logging.FileHandler(_log_path(), encoding="utf-8")
        file_handle.addFilter(_SecretFilter())
        file_handle.setFormatter(
            logging.Formatter(
                "[%(levelname)s][%(asctime)s][%(filename)s:%(lineno)d] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        log.addHandler(file_handle)
    except OSError:
        console_handle.handle(
            logging.LogRecord(
                "log", logging.WARNING, __file__, 0,
                "[log] file logging disabled (log path not writable): %s",
                (_log_path(),), None,
            )
        )


def _get_logger():
    log = logging.getLogger("log")
    _reset_logger(log)
    log.setLevel(logging.INFO)
    return log


# 日志句柄
logger = _get_logger()
