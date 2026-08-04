"""Structured logging with mandatory credential redaction.

Ported from ``cewe-worker/src/core/logging_config.py``. SPEC §4 makes this
non-optional: "log ทุกตัวผ่าน credential redaction" — the
:class:`CredentialRedactionFilter` is attached to **every** handler so meter
passwords, cipher keys and tokens are masked before they reach stdout or disk.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import ClassVar

from arichds.constants import LOG_FILE_BACKUP_COUNT, LOG_FILE_MAX_BYTES

_LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_DATE_FMT: str = "%Y-%m-%dT%H:%M:%S%z"


class CredentialRedactionFilter(logging.Filter):
    """Redact passwords and secret keys before they reach any log handler.

    Patterns cover the field names that appear in connection strings, config
    objects, CLI args and exception messages. The filter always returns True so
    the record is still emitted — it only rewrites the message.

    MUST be attached to every handler (SPEC §4).
    """

    PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"(password\s*[=:]\s*)\S+", re.IGNORECASE),
        re.compile(r"(pwd\s*[=:]\s*)\S+", re.IGNORECASE),
        re.compile(r"(passwd\s*[=:]\s*)\S+", re.IGNORECASE),
        re.compile(r"(authentication_key\s*[=:]\s*)\S+", re.IGNORECASE),
        re.compile(r"(block_cipher_key\s*[=:]\s*)\S+", re.IGNORECASE),
        # SMART TCC HighGMAC system title — accepts system_title, system-title,
        # or "system title" (space).
        re.compile(r"(system[_ ]?title\s*[=:]\s*)\S+", re.IGNORECASE),
        # Meter Key (SPEC §3.9) — never persisted and never logged on purpose;
        # redacted defensively so an exception echoing a request body cannot
        # leak a redeemable key.
        re.compile(r"(meter_key\s*[=:]\s*)\S+", re.IGNORECASE),
        re.compile(r"(secret\s*[=:]\s*)\S+", re.IGNORECASE),
        # Also covers ARICHDS_MACHINE_TOKEN=… and machine_token: … — the key
        # ends in "token", so the suffix match already redacts both.
        re.compile(r"(token\s*[=:]\s*)\S+", re.IGNORECASE),
        # ORDER IS LOAD-BEARING: `bearer` must run BEFORE `authorization`,
        # otherwise the authorization pattern consumes only the word "Bearer"
        # and leaves the token itself in clear.
        re.compile(r"(bearer\s+)\S+", re.IGNORECASE),
        re.compile(r"(authorization\s*[=:]\s*)\S+", re.IGNORECASE),
        # Activation Code (CONTEXT.md) — a signed license is not a secret in the
        # same sense as a password, but it is machine-bound customer data and a
        # full code in a log line is noise at best.
        re.compile(r"(activation_code\s*[=:]\s*)\S+", re.IGNORECASE),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply all redaction patterns to the formatted message."""
        try:
            msg = record.getMessage()
            for pattern in self.PATTERNS:
                msg = pattern.sub(r"\1[REDACTED]", msg)
            record.msg = msg
            record.args = None
        except Exception:  # noqa: BLE001
            # Never let the filter itself crash the logging machinery.
            pass
        return True


def configure_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    enable_console: bool = True,
    enable_file: bool = True,
) -> None:
    """Configure logging for the ARICHDS process.

    Removes any handlers added before this call (e.g. by ``basicConfig`` during
    import), then attaches a fresh set with the
    :class:`CredentialRedactionFilter` wired to each one.

    Args:
        level: Logging level string (DEBUG / INFO / WARNING / ERROR / CRITICAL).
        log_dir: Directory for the rotating log file. No file handler when None.
        enable_console: Attach a stdout StreamHandler.
        enable_file: Attach a RotatingFileHandler (requires *log_dir*).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in list(root.handlers):
        root.removeHandler(handler)

    redaction_filter = CredentialRedactionFilter()
    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_LOG_DATE_FMT)

    if enable_console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        console.addFilter(redaction_filter)
        root.addHandler(console)

    if enable_file and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            filename=log_dir / "arichds.log",
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(redaction_filter)
        root.addHandler(rotating)
