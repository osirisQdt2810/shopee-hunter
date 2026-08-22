"""Logging with redaction, because this app handles session cookies.

A stack trace that helpfully includes ``SPC_EC=<the user's session token>`` is a security
bug in a log file. The filter here scrubs known-sensitive keys out of every record before
it reaches a handler, so no call site has to remember.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

LOGGER_NAME = "shopee_hunter"

# Substrings that mark a value as secret wherever they appear (query string, JSON, header).
#
# The two settings field names are listed in FULL as well as by their generic stem, because
# the value patterns below anchor on `\b` and `_` is a word character: `\bsecret\b` never
# matches inside `app_secret`, and `\bcookie\b` never matches inside `cookie_string`. Both are
# exactly the names these values carry in a settings dump or a repr, so the generic stems were
# missing the most likely way either one reaches a log.
_SECRET_KEYS = (
    "cookie_string",
    "app_secret",
    "cookie",
    "authorization",
    "csrftoken",
    "spc_ec",
    "spc_f",
    "spc_si",
    "spc_u",
    "sso",
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "partner_key",
    "af-ac-enc-dat",
)

_REDACTED = "<redacted>"

# key=value / "key": "value" / key: value — one pattern per shape we actually log.
_PATTERNS = tuple(
    re.compile(pattern % re.escape(key), re.IGNORECASE)
    for key in _SECRET_KEYS
    for pattern in (
        r'("?%s"?\s*[:=]\s*")([^"]*)(")',
        r"(\b%s\b\s*=\s*)([^&;,\s]+)",
    )
)


class RedactingFilter(logging.Filter):
    """Replaces secret-looking values in the formatted message and its args.

    Only *string* arguments are rewritten. An earlier version coerced every argument with
    ``str()``, which turned a float destined for ``%.0f`` into ``"120.0"`` and made logging
    raise a TypeError while reporting a blocked request — the log line about the failure
    became a second failure. Non-strings cannot carry a secret in a form these patterns
    match, so leaving them alone costs nothing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact(arg) if isinstance(arg, str) else arg for arg in record.args
                )
        return True


def redact(text: str) -> str:
    """Scrub secret values out of ``text``, keeping the key names for debuggability."""
    for pattern in _PATTERNS:
        text = pattern.sub(
            lambda m: f"{m.group(1)}{_REDACTED}{m.group(3) if m.lastindex == 3 else ''}",
            text,
        )
    return text


def configure(
    level: int = logging.INFO,
    *,
    log_file: Optional[Path] = None,
    quiet_libraries: bool = True,
) -> logging.Logger:
    """Set up the app logger. Idempotent — safe to call from tests and from ``app.py``.

    Args:
        level: Threshold for our own logger.
        log_file: Optional file to mirror records into (the user data dir in production).
        quiet_libraries: Silence httpx/httpcore request spam, which is per-request and
            would otherwise bury our own lines during a scan.

    Returns:
        The configured app logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"
            )
        )
        stream.addFilter(RedactingFilter())
        logger.addHandler(stream)

    if log_file is not None and not any(
        isinstance(h, logging.FileHandler) for h in logger.handlers
    ):
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s [%(filename)s:%(lineno)d]: %(message)s"
            )
        )
        file_handler.addFilter(RedactingFilter())
        logger.addHandler(file_handler)

    if quiet_libraries:
        for noisy in ("httpx", "httpcore", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    return logger


def get_logger(module: str = "") -> logging.Logger:
    """Child logger for a module: ``get_logger("sources.shopee_web")``."""
    return logging.getLogger(f"{LOGGER_NAME}.{module}" if module else LOGGER_NAME)
