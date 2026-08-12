"""Rotating log file for the Campbell AI API process, scoped to this package.

The service had no log file of its own: everything went to stdout and lived only as
long as the container's log driver kept it. That makes an incident unreadable after the
fact, which is the whole problem when the symptom is "it was fine this morning".

Two scoping decisions matter, because this package lives inside a larger repository it
does not own:

**The root logger is never touched.** Handlers are attached to the ``campbell_ai``
logger and to uvicorn's, and nothing else. Reconfiguring root from library code would
hijack the logging of whatever process happened to import this module - the dashboard
imports parts of this package, and it has its own logging policy. Attaching to a named
subtree cannot do that.

**``campbell_ai`` stops propagating.** Once this package owns handlers for its own
subtree, letting records continue to root would duplicate every line into whatever the
host process configured. Isolation here is what makes "the API's logs" a well-defined
set of lines in a well-defined file.

Console output is left to uvicorn for its own loggers, so request lines are not printed
twice; this module only adds the console handler ``campbell_ai`` would otherwise lack.

Disk use is bounded and calculable: ``CAMPBELL_AI_LOG_MAX_BYTES x
(CAMPBELL_AI_LOG_BACKUP_COUNT + 1)``, 60 MB with the defaults. History beyond that is
not lost - ``log_archive.py`` ships sealed files to S3 before they are recycled.
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional


# The logger subtree this package owns. Every module here uses
# `logging.getLogger("campbell_ai.<something>")`, so one attachment point covers all.
PACKAGE_LOGGER = "campbell_ai"

# uvicorn's own loggers, added so the file holds request/error lines next to the
# application's. Their console handling is uvicorn's and is left alone.
SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

# The Campbell AI frontend runs inside the *dashboard* process, so it needs its own
# attachment and its own file: one process cannot rotate the other's handler, and
# interleaving two processes into one file corrupts it. See `configure_ui_logging`.
UI_LOGGER = "campbell_ai.ui"

DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "campbell_api.log"
DEFAULT_UI_LOG_FILE = "campbell_ui.log"
# 10 MB x 5 backups = 60 MB worst case, including the active file.
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

FILE_FORMAT = (
    "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)
CONSOLE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

_LOCK = threading.Lock()
_CONFIGURED: dict[str, Any] = {}
_HANDLER: Optional[RotatingFileHandler] = None
_UI_CONFIGURED: dict[str, Any] = {}
_UI_HANDLER: Optional[RotatingFileHandler] = None


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configure_api_logging(force: bool = False) -> dict[str, Any]:
    """Attach a bounded rotating file handler to this package's loggers.

    Idempotent: the first call in a process wins and later callers get the same
    description back, so importing a module that logs cannot silently reconfigure a
    process that already decided where its logs go. Pass ``force=True`` to rebuild
    (tests, controlled reloads).

    Returns a description of what was configured - path, level, rotation bounds - which
    the diagnostics endpoint reports, so an operator can confirm the settings that are
    live rather than the ones the environment was supposed to set.

    Never raises. A log file that cannot be opened is bad; an API that will not start
    because of it is worse, so the failure is recorded in the returned description and
    reported through diagnostics.
    """
    global _HANDLER

    with _LOCK:
        if _CONFIGURED and not force:
            return dict(_CONFIGURED)

        log_dir = Path(os.getenv("CAMPBELL_AI_LOG_DIR", DEFAULT_LOG_DIR))
        log_file = os.getenv("CAMPBELL_AI_LOG_FILE", DEFAULT_LOG_FILE)
        level_name = os.getenv("CAMPBELL_AI_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        max_bytes = _env_int("CAMPBELL_AI_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)
        backup_count = _env_int("CAMPBELL_AI_LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT)
        want_console = _env_bool("CAMPBELL_AI_LOG_CONSOLE", True)

        package_logger = logging.getLogger(PACKAGE_LOGGER)
        package_logger.setLevel(level)
        # This package owns its subtree now; propagating as well would print every line
        # twice in any host process that configured root.
        package_logger.propagate = False

        # Detach only handlers this module installed, so a re-configure cannot leave two
        # file handlers writing the same file, and cannot remove a handler someone else
        # deliberately attached.
        for target in (package_logger, *(logging.getLogger(n) for n in SERVER_LOGGERS)):
            for handler in list(target.handlers):
                if getattr(handler, "_campbell_ai_managed", False):
                    target.removeHandler(handler)
                    try:
                        handler.close()
                    except Exception:  # pragma: no cover - closing a dead handler is fine
                        pass

        file_path: Optional[Path] = None
        file_error: Optional[str] = None
        _HANDLER = None
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_path = log_dir / log_file
            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
            )
            file_handler._campbell_ai_managed = True  # type: ignore[attr-defined]
            package_logger.addHandler(file_handler)
            # Same handler object on the server loggers: one file, one lock, no
            # interleaving between the application's lines and the request lines.
            for name in SERVER_LOGGERS:
                logging.getLogger(name).addHandler(file_handler)
            _HANDLER = file_handler
        except OSError as exc:
            file_error = f"{type(exc).__name__}: {exc}"

        if want_console:
            console = logging.StreamHandler()
            console.setLevel(level)
            console.setFormatter(
                logging.Formatter(CONSOLE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
            )
            console._campbell_ai_managed = True  # type: ignore[attr-defined]
            # Only on this package's logger: uvicorn already prints its own, and adding
            # one there would double every request line on stdout.
            package_logger.addHandler(console)

        _CONFIGURED.clear()
        _CONFIGURED.update(
            {
                "logger": PACKAGE_LOGGER,
                "level": level_name,
                "file": str(file_path) if file_path else None,
                "file_error": file_error,
                "console": want_console,
                "max_bytes": max_bytes,
                "backup_count": backup_count,
                "max_disk_bytes": max_bytes * (backup_count + 1),
                "server_loggers": list(SERVER_LOGGERS),
            }
        )
        description = dict(_CONFIGURED)

    log = logging.getLogger("campbell_ai.logging")
    log.info(
        "logging configured file=%s level=%s rotation=%sMBx%s",
        description["file"] or "console-only",
        description["level"],
        round(description["max_bytes"] / (1024 * 1024), 1),
        description["backup_count"],
    )
    if file_error:
        log.error("log file unavailable, continuing without one: %s", file_error)
    return description


def configure_ui_logging(force: bool = False) -> dict[str, Any]:
    """Give the Campbell AI frontend its own rotating log file.

    The frontend (``dashboard/campbell_ai/``) is Campbell AI code that happens to run in
    the dashboard's process. Its failures - a timeout talking to the API, an unreachable
    service, a job that expired - used to land in ``dashboard.log``, which never rotates
    and is nobody's to archive. Those are the most useful lines there are for a latency
    complaint, because the frontend is the only place that measures what the *user*
    waited, so they belong in a file this package rotates and ships.

    Two things differ from ``configure_api_logging`` on purpose:

    - **A separate file.** Two processes cannot share a ``RotatingFileHandler``: neither
      can rotate the other's handle, and interleaved writes across a rollover corrupt the
      file. ``campbell_ui.log`` is the frontend's; ``campbell_api.log`` is the service's.
    - **Propagation stays on.** Unlike the API subtree, records here keep flowing to the
      host's root logger, so ``dashboard.log`` still receives exactly what it received
      before. Silencing lines the dashboard's maintainers may rely on is not ours to
      decide; adding a second, rotated copy costs them nothing.

    Called from ``register_campbell_ai_callbacks``, so the dashboard needs no change: it
    already invokes that function, and this is Campbell AI configuring Campbell AI.
    """
    global _UI_HANDLER

    with _LOCK:
        if _UI_CONFIGURED and not force:
            return dict(_UI_CONFIGURED)

        log_dir = Path(os.getenv("CAMPBELL_AI_LOG_DIR", DEFAULT_LOG_DIR))
        log_file = os.getenv("CAMPBELL_AI_UI_LOG_FILE", DEFAULT_UI_LOG_FILE)
        level_name = os.getenv("CAMPBELL_AI_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        max_bytes = _env_int("CAMPBELL_AI_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)
        backup_count = _env_int("CAMPBELL_AI_LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT)

        ui_logger = logging.getLogger(UI_LOGGER)
        ui_logger.setLevel(level)

        for handler in list(ui_logger.handlers):
            if getattr(handler, "_campbell_ai_ui_managed", False):
                ui_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # pragma: no cover - closing a dead handler is fine
                    pass

        file_path: Optional[Path] = None
        file_error: Optional[str] = None
        _UI_HANDLER = None
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_path = log_dir / log_file
            file_handler = RotatingFileHandler(
                file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(
                logging.Formatter(FILE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
            )
            file_handler._campbell_ai_ui_managed = True  # type: ignore[attr-defined]
            ui_logger.addHandler(file_handler)
            _UI_HANDLER = file_handler
        except OSError as exc:
            # No console handler is added here: the dashboard already prints whatever it
            # prints, and duplicating that is noise. Losing the file is reported and the
            # frontend keeps working.
            file_error = f"{type(exc).__name__}: {exc}"

        _UI_CONFIGURED.clear()
        _UI_CONFIGURED.update(
            {
                "logger": UI_LOGGER,
                "level": level_name,
                "file": str(file_path) if file_path else None,
                "file_error": file_error,
                "max_bytes": max_bytes,
                "backup_count": backup_count,
                "max_disk_bytes": max_bytes * (backup_count + 1),
                "propagates_to_host": True,
            }
        )
        description = dict(_UI_CONFIGURED)

    log = logging.getLogger("campbell_ai.ui.logging")
    log.info(
        "frontend logging configured file=%s level=%s rotation=%sMBx%s",
        description["file"] or "none",
        description["level"],
        round(description["max_bytes"] / (1024 * 1024), 1),
        description["backup_count"],
    )
    if file_error:
        log.error("frontend log file unavailable: %s", file_error)
    return description


def ui_logging_description() -> dict[str, Any]:
    """What ``configure_ui_logging`` set up, or empty if it never ran."""
    with _LOCK:
        return dict(_UI_CONFIGURED)


def ui_rotating_handler() -> Optional[RotatingFileHandler]:
    """The frontend's rotating handler, for the archiver that seals it on a schedule."""
    return _UI_HANDLER


def reset_ui_logging() -> None:
    """Detach the frontend's handler and forget its configuration. For tests."""
    global _UI_HANDLER
    with _LOCK:
        ui_logger = logging.getLogger(UI_LOGGER)
        for handler in list(ui_logger.handlers):
            if getattr(handler, "_campbell_ai_ui_managed", False):
                ui_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # pragma: no cover
                    pass
        _UI_CONFIGURED.clear()
        _UI_HANDLER = None


def logging_description() -> dict[str, Any]:
    """What ``configure_api_logging`` actually set up, or empty if it never ran."""
    with _LOCK:
        return dict(_CONFIGURED)


def rotating_handler() -> Optional[RotatingFileHandler]:
    """The live rotating handler, for the archiver that seals files on a schedule."""
    return _HANDLER


def reset_api_logging() -> None:
    """Detach this package's handlers and forget the configuration. For tests."""
    global _HANDLER
    with _LOCK:
        for name in (PACKAGE_LOGGER, *SERVER_LOGGERS):
            target = logging.getLogger(name)
            for handler in list(target.handlers):
                if getattr(handler, "_campbell_ai_managed", False):
                    target.removeHandler(handler)
                    try:
                        handler.close()
                    except Exception:  # pragma: no cover
                        pass
        logging.getLogger(PACKAGE_LOGGER).propagate = True
        _CONFIGURED.clear()
        _HANDLER = None
