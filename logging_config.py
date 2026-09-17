"""Structured JSON logging for product-service.

Every log line is a single JSON object so the log shipper (and OpenSearch)
can index fields without regex parsing.
"""
import json
import logging
import sys

SERVICE_NAME = "product-service"

# Attributes the stdlib puts on every LogRecord. Anything *not* in here was
# passed by us via `extra=` and gets promoted to a top-level JSON field.
_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):

    def format(self, record):
        log = {
            "service": SERVICE_NAME,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                log[key] = value

        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)

        return json.dumps(log, default=str)


def safe_extra(fields):
    """Rename any key that would collide with a built-in LogRecord attribute.

    `logging` raises KeyError if `extra=` tries to overwrite e.g. `created`
    or `message`, and error details come from the domain, not from us.
    """
    return {
        (f"detail_{k}" if k in _RESERVED else k): v
        for k, v in fields.items()
    }


def configure_logging(level=logging.INFO):
    """Attach the JSON handler to our logger exactly once."""
    logger = logging.getLogger(SERVICE_NAME)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    # Our handler is the only one that should emit these records.
    logger.propagate = False

    return logger


logger = configure_logging()
