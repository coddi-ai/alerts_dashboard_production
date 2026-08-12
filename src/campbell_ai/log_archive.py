"""Seal, compress and ship the API's log files to S3 so they outlive the container.

Rotation alone bounds disk use; it does not make logs *available*. With no console
access, a rotated file that the next rotation overwrites takes the only record of an
incident with it, and the window it covers is however long the process took to write
``CAMPBELL_AI_LOG_MAX_BYTES``. That is the gap this closes.

The flow per cycle:

1. **Seal.** If the active log file has gone quiet for longer than the archive interval
   and has content, force a rollover. Without this a low-traffic process never reaches
   the size threshold and its newest logs are never eligible for archiving - which is
   exactly the process you want logs from when it has been idle and slow.
2. **Compress and upload.** Every rotated file (``campbell_api.log.1``, ``.2``, ...) is
   gzipped and uploaded under a key derived from its modification time and size, so
   re-running a cycle produces the same key and cannot duplicate an object.
3. **Delete locally, only after a confirmed upload.** This is what keeps the volume
   bounded. A failed upload leaves the file in place to be retried next cycle; losing a
   log to a network blip would defeat the purpose.

Credentials and bucket come from the same ``BUCKET_NAME``/``ACCESS_KEY``/``SECRET_KEY``
variables this package already uses for the conversation archive (see
``persistence.py``), and boto3 is used directly rather than through the repository's
uploader so this stays self-contained.

Nothing here can break the process it archives for. Every step is contained, and a
misconfigured or unreachable bucket degrades to "rotation only", which is still strictly
better than the unbounded file this replaces.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.campbell_ai.logging_setup import rotating_handler, ui_rotating_handler


logger = logging.getLogger("campbell_ai.log_archive")

DEFAULT_INTERVAL_SECONDS = 900
DEFAULT_S3_PREFIX = "campbellAI/logs"
# Below this the active file is not worth sealing; an empty rollover consumes a backup
# slot and ships nothing.
MIN_SEAL_BYTES = 1024
# Rotated files this package produced. Scoped to the configured stem so the archiver
# never touches another process's logs in a shared logs/ volume.
_ROTATED_SUFFIXES = tuple(str(index) for index in range(1, 100))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(30, int(float(raw)))
    except ValueError:
        return default


class S3LogSink:
    """Minimal S3 writer for archived log files.

    Deliberately not the repository's ``S3Uploader``: this package should not depend on
    the dashboard's data-sync layer to back up its own logs, and the two want different
    behaviour anyway (that one skips existing objects by default and prints progress
    bars).
    """

    def __init__(
        self,
        bucket: str,
        *,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "us-east-1",
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        # botocore retries transient 5xx and throttling itself; this only has to handle
        # the permanent failures that survive it.
        config = Config(retries={"max_attempts": 3, "mode": "standard"})
        if access_key and secret_key:
            self._client = boto3.client(
                "s3",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=config,
            )
        else:
            self._client = boto3.client("s3", region_name=region, config=config)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def put_file(self, path: Path, key: str) -> None:
        with open(path, "rb") as handle:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=handle,
                ContentType="application/gzip",
            )


class LogArchiver:
    """Periodically seals rotated log files and backs them up to S3."""

    def __init__(
        self,
        *,
        log_dir: Path | str = "logs",
        log_stem: str = "campbell_api",
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        s3_prefix: str = DEFAULT_S3_PREFIX,
        bucket: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region: str = "us-east-1",
        sink: Any = None,
        handler_provider: Any = None,
        logger_override: Optional[logging.Logger] = None,
    ):
        # Which logger this instance reports to. The frontend's archiver runs in the
        # dashboard process and must report under `campbell_ai.ui`, or its own failures -
        # "could not archive X" being the one that matters - land outside the file it is
        # responsible for shipping, in the host's log that this whole exercise is about
        # not depending on.
        self._log = logger_override or logger
        self.log_dir = Path(log_dir)
        self.log_stem = log_stem
        # Which rotating handler this archiver is allowed to roll over. The API's and the
        # frontend's live in different processes and different files, so an archiver that
        # grabbed "the" handler would seal the wrong one in whichever process it ran.
        self._handler_provider = handler_provider or rotating_handler
        self.interval_seconds = max(30, int(interval_seconds))
        self.s3_prefix = s3_prefix.strip("/")
        self.bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region

        # `sink` is an injection point for tests; production builds one lazily so a
        # deployment without credentials still gets sealing and rotation, and importing
        # this module never touches the network.
        self._sink = sink
        self._sink_failed = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._cycles = 0
        self._sealed = 0
        self._uploaded = 0
        self._failed = 0
        self._last_cycle_at: Optional[str] = None
        self._last_error: Optional[str] = None

    # -- s3 ------------------------------------------------------------------

    @property
    def s3_enabled(self) -> bool:
        return bool(self._sink or (self.bucket and not self._sink_failed))

    def _get_sink(self) -> Any:
        if self._sink is not None or self._sink_failed or not self.bucket:
            return self._sink
        try:
            self._sink = S3LogSink(
                self.bucket,
                access_key=self._access_key,
                secret_key=self._secret_key,
                region=self._region,
            )
        except Exception as exc:
            self._sink_failed = True
            self._last_error = f"sink: {type(exc).__name__}: {exc}"
            self._log.warning("log archive disabled, S3 client unavailable: %s", exc)
        return self._sink

    def _s3_key(self, path: Path) -> str:
        """Stable, time-partitioned key for one rotated file.

        Derived from mtime and size rather than "now", so the key identifies the file's
        content window and re-running a cycle is idempotent.
        """
        stat = path.stat()
        stamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        return (
            f"{self.s3_prefix}/{stamp:%Y/%m}/"
            f"{self.log_stem}-{stamp:%Y%m%dT%H%M%SZ}-{stat.st_size}.log.gz"
        )

    # -- the cycle -----------------------------------------------------------

    def rotated_files(self) -> list[Path]:
        """Rotated log files awaiting archival, oldest content first."""
        if not self.log_dir.exists():
            return []
        candidates = [
            path
            for path in self.log_dir.glob(f"{self.log_stem}.log.*")
            # `.log.1`, `.log.2`, ... from RotatingFileHandler. A `.gz` is a previous
            # cycle's leftover intermediate and is not a source file.
            if path.is_file() and path.name.rsplit(".", 1)[-1] in _ROTATED_SUFFIXES
        ]
        return sorted(candidates, key=lambda p: p.stat().st_mtime)

    def seal_active_log(self) -> bool:
        """Force a rollover so the current file becomes archivable. True if it rolled."""
        handler = self._handler_provider()
        if handler is None:
            return False
        try:
            path = Path(handler.baseFilename)
            if not path.exists() or path.stat().st_size < MIN_SEAL_BYTES:
                return False
            # `st_mtime` is the last *write*, so this asks "has anything been written
            # recently", not "how old is the file". A file still being appended to is left
            # alone; one that has gone quiet is sealed and shipped.
            if time.time() - path.stat().st_mtime < self.interval_seconds:
                return False
            handler.acquire()
            try:
                handler.doRollover()
            finally:
                handler.release()
            with self._lock:
                self._sealed += 1
            return True
        except Exception as exc:
            with self._lock:
                self._last_error = f"seal: {type(exc).__name__}: {exc}"
            self._log.warning("could not seal active log: %s", exc)
            return False

    def archive_file(self, path: Path) -> bool:
        """Compress and upload one rotated file, deleting it on success."""
        sink = self._get_sink()
        if sink is None:
            return False

        gz_path = path.with_suffix(path.suffix + ".gz")
        try:
            with open(path, "rb") as source, gzip.open(gz_path, "wb") as target:
                shutil.copyfileobj(source, target, length=256 * 1024)
        except OSError as exc:
            with self._lock:
                self._last_error = f"compress: {type(exc).__name__}: {exc}"
            gz_path.unlink(missing_ok=True)
            return False

        try:
            key = self._s3_key(path)
            # An object already there means a previous cycle uploaded it and failed
            # before deleting. Treating that as success is what stops the file being
            # stranded forever; the key is content-derived, so it cannot be a different
            # file's object.
            if not sink.exists(key):
                sink.put_file(gz_path, key)
            path.unlink(missing_ok=True)
            with self._lock:
                self._uploaded += 1
            self._log.info("archived log %s -> s3://%s/%s", path.name, self.bucket, key)
            return True
        except Exception as exc:
            with self._lock:
                self._failed += 1
                self._last_error = f"upload: {type(exc).__name__}: {exc}"
            self._log.warning("could not archive %s: %s", path.name, exc)
            return False
        finally:
            # Never leave the intermediate behind; the source file is the retry unit.
            gz_path.unlink(missing_ok=True)

    def run_cycle(self) -> dict[str, Any]:
        """One seal-and-ship pass. Safe to call directly; used by tests and endpoints."""
        sealed = self.seal_active_log()
        archived = 0
        pending = self.rotated_files()
        if self.s3_enabled:
            for path in pending:
                if self._stop.is_set():
                    break
                if self.archive_file(path):
                    archived += 1
        with self._lock:
            self._cycles += 1
            self._last_cycle_at = datetime.now(tz=timezone.utc).isoformat()
        return {
            "sealed": sealed,
            "archived": archived,
            "pending": len(pending) - archived,
            "s3_enabled": self.s3_enabled,
        }

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "LogArchiver":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="campbell-log-archiver", daemon=True
        )
        self._thread.start()
        self._log.info(
            "log archiver started interval=%ss bucket=%s prefix=%s",
            self.interval_seconds,
            self.bucket or "none (rotation only)",
            self.s3_prefix,
        )
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_cycle()
            except Exception:  # pragma: no cover - archiving must never kill a process
                self._log.exception("log archive cycle failed")

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "interval_seconds": self.interval_seconds,
                "s3_enabled": self.s3_enabled,
                "bucket": self.bucket,
                "prefix": self.s3_prefix,
                "log_dir": str(self.log_dir),
                "cycles": self._cycles,
                "sealed": self._sealed,
                "uploaded": self._uploaded,
                "failed": self._failed,
                "pending_files": [path.name for path in self.rotated_files()],
                "last_cycle_at": self._last_cycle_at,
                "last_error": self._last_error,
            }


_ARCHIVER: Optional[LogArchiver] = None
_ARCHIVER_LOCK = threading.Lock()


def start_log_archiver() -> Optional[LogArchiver]:
    """Start (or return) this process's archiver, configured from the environment.

    With no bucket it still runs, sealing files on schedule so rotation is time-bounded
    as well as size-bounded.
    """
    global _ARCHIVER
    with _ARCHIVER_LOCK:
        if _ARCHIVER is not None:
            return _ARCHIVER
        if not _env_bool("CAMPBELL_AI_LOG_ARCHIVE_ENABLED", True):
            logger.info("log archiver disabled by CAMPBELL_AI_LOG_ARCHIVE_ENABLED")
            return None
        log_file = os.getenv("CAMPBELL_AI_LOG_FILE", "campbell_api.log")
        archiver = LogArchiver(
            log_dir=Path(os.getenv("CAMPBELL_AI_LOG_DIR", "logs")),
            log_stem=Path(log_file).stem or "campbell_api",
            interval_seconds=_env_int(
                "CAMPBELL_AI_LOG_ARCHIVE_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS
            ),
            s3_prefix=os.getenv("CAMPBELL_AI_LOG_ARCHIVE_S3_PREFIX", DEFAULT_S3_PREFIX),
            bucket=os.getenv("BUCKET_NAME", "").strip() or None,
            access_key=os.getenv("ACCESS_KEY", "").strip() or None,
            secret_key=os.getenv("SECRET_KEY", "").strip() or None,
            region=os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1",
        )
        _ARCHIVER = archiver.start()
        return _ARCHIVER


_UI_ARCHIVER: Optional[LogArchiver] = None


def start_ui_log_archiver() -> Optional[LogArchiver]:
    """Start the archiver for the frontend's log file, inside the dashboard process.

    Kept as a separate singleton from the API's rather than a parameter on it: both
    archivers exist, in different processes, and one global holding whichever started
    last would be a bug waiting for the day something imports both.
    """
    global _UI_ARCHIVER
    with _ARCHIVER_LOCK:
        if _UI_ARCHIVER is not None:
            return _UI_ARCHIVER
        if not _env_bool("CAMPBELL_AI_UI_LOG_ARCHIVE_ENABLED", True):
            logger.info("frontend log archiver disabled by CAMPBELL_AI_UI_LOG_ARCHIVE_ENABLED")
            return None
        log_file = os.getenv("CAMPBELL_AI_UI_LOG_FILE", "campbell_ui.log")
        archiver = LogArchiver(
            log_dir=Path(os.getenv("CAMPBELL_AI_LOG_DIR", "logs")),
            log_stem=Path(log_file).stem or "campbell_ui",
            interval_seconds=_env_int(
                "CAMPBELL_AI_LOG_ARCHIVE_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS
            ),
            s3_prefix=os.getenv("CAMPBELL_AI_LOG_ARCHIVE_S3_PREFIX", DEFAULT_S3_PREFIX),
            bucket=os.getenv("BUCKET_NAME", "").strip() or None,
            access_key=os.getenv("ACCESS_KEY", "").strip() or None,
            secret_key=os.getenv("SECRET_KEY", "").strip() or None,
            region=os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1",
            handler_provider=ui_rotating_handler,
            # Under `campbell_ai.ui`, so this archiver's own failures land in the file it
            # ships rather than in the host process's log.
            logger_override=logging.getLogger("campbell_ai.ui.log_archive"),
        )
        _UI_ARCHIVER = archiver.start()
        return _UI_ARCHIVER


def get_ui_log_archiver() -> Optional[LogArchiver]:
    return _UI_ARCHIVER


def reset_ui_log_archiver() -> None:
    """Stop and forget the frontend archiver. For tests and controlled reloads."""
    global _UI_ARCHIVER
    with _ARCHIVER_LOCK:
        if _UI_ARCHIVER is not None:
            _UI_ARCHIVER.stop()
        _UI_ARCHIVER = None


def get_log_archiver() -> Optional[LogArchiver]:
    return _ARCHIVER


def reset_log_archiver() -> None:
    """Stop and forget the process archiver. For tests and controlled reloads."""
    global _ARCHIVER
    with _ARCHIVER_LOCK:
        if _ARCHIVER is not None:
            _ARCHIVER.stop()
        _ARCHIVER = None


def log_archive_stats() -> dict[str, Any]:
    archiver = _ARCHIVER
    if archiver is None:
        return {"running": False}
    return archiver.stats()
