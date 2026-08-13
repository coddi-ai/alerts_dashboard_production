"""
Tests for Campbell AI's own resource hardening: bounded caches, memory reclamation,
log rotation/archival and the diagnostics payload.

Everything under test lives inside ``src/campbell_ai/`` and is scoped to the API process.
Two of those boundaries are themselves asserted here, because they are the reason this
package can own its logging inside a repository it does not own:

- importing the package configures no logging and starts no thread;
- ``configure_api_logging`` attaches handlers to the ``campbell_ai`` subtree only, never
  to the root logger.

Covers:
1. count_csv_data_rows matches a pandas parse, including quoted newlines
2. FrameCache evicts by bytes, not entry count, and refuses oversized entries
3. CacheRegistry clears everything registered, surviving a failing member
4. DashboardDataRepository holds frames in a bounded cache and retires stale mtimes
5. _probe_frame no longer parses the whole CSV to count rows
6. ResourceJanitor reclaims on pressure, honours its cooldown, and once per idle stretch
7. configure_api_logging installs a bounded rotating handler without touching root
8. LogArchiver seals the active log, uploads it, and only deletes on success
9. diagnostics.snapshot and tail_log return usable payloads
"""

import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.campbell_ai.data import DashboardDataRepository, count_csv_data_rows
from src.campbell_ai.diagnostics import snapshot, tail_log
from src.campbell_ai.janitor import ResourceJanitor
from src.campbell_ai.log_archive import LogArchiver
from src.campbell_ai.logging_setup import (
    PACKAGE_LOGGER,
    configure_api_logging,
    logging_description,
    reset_api_logging,
    rotating_handler,
)
from src.campbell_ai.resources import (
    CacheRegistry,
    FrameCache,
    frame_nbytes,
    memory_snapshot,
    watermark_from_env,
)


@pytest.fixture
def api_logging(monkeypatch):
    """Configure this package's logging into a temp dir, then detach it.

    A fixture rather than inline setup because leaving a rotating handler attached leaks
    an open file across tests and blocks temp-dir cleanup on Windows.
    """
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPBELL_AI_LOG_DIR", tmp)
        monkeypatch.setenv("CAMPBELL_AI_LOG_FILE", "campbell_api.log")
        try:
            description = configure_api_logging(force=True)
            yield Path(tmp), description
        finally:
            reset_api_logging()


# --------------------------------------------------------------------------------------
# 1. Row counting
# --------------------------------------------------------------------------------------


def _pandas_row_count(path: Path) -> int:
    header = pd.read_csv(path, nrows=0, low_memory=False)
    if not len(header.columns):
        return 0
    return len(pd.read_csv(path, usecols=[0], low_memory=False))


@pytest.mark.parametrize(
    "content,expected",
    [
        ("a,b\n1,2\n3,4\n", 2),
        # No trailing newline: the last line is still a row.
        ("a,b\n1,2\n3,4", 2),
        ("a,b\n", 0),
        ("", 0),
        ("a,b\r\n1,2\r\n3,4\r\n", 2),
        # Newline inside a quoted field is not a row boundary.
        ('a,b\n1,"line1\nline2"\n2,x\n', 2),
        # RFC 4180 escaped quotes flip parity twice and must net out.
        ('a,b\n1,"he said ""hi""\nand left"\n2,ok\n', 2),
        # Several quoted multi-line fields in a row.
        ('a,b\n1,"x\ny\nz"\n2,"p\nq"\n3,ok\n', 3),
    ],
)
def test_count_csv_data_rows_matches_semantics(content, expected):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.csv"
        path.write_text(content, encoding="utf-8", newline="")
        assert count_csv_data_rows(path) == expected


def test_count_csv_data_rows_agrees_with_pandas_across_chunk_boundaries():
    """A quoted newline straddling the read boundary must not be miscounted."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "big.csv"
        rows = ["a,b"]
        for index in range(4000):
            if index % 7 == 0:
                rows.append(f'{index},"multi\nline\nvalue"')
            else:
                rows.append(f"{index},plain")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="")

        # A deliberately tiny chunk forces many boundaries inside quoted fields.
        assert count_csv_data_rows(path, chunk_bytes=64) == 4000
        assert count_csv_data_rows(path) == _pandas_row_count(path)


def test_count_csv_data_rows_missing_file_returns_zero():
    assert count_csv_data_rows(Path("does-not-exist-anywhere.csv")) == 0


# --------------------------------------------------------------------------------------
# 2. FrameCache
# --------------------------------------------------------------------------------------


def _frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame({"a": range(rows), "b": [f"value-{i}" for i in range(rows)]})


def test_frame_cache_returns_what_it_stored():
    cache = FrameCache(budget_bytes=10 * 1024 * 1024, name="test")
    frame = _frame(10)
    cache.put("k", frame)
    assert cache.get("k") is frame
    assert cache.get("missing") is None
    stats = cache.stats()
    assert stats["entries"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_frame_cache_evicts_by_bytes_not_count():
    """The bound that matters: many small entries fit where two large ones do not."""
    frame = _frame(500)
    size = frame_nbytes(frame)
    # Room for exactly two entries.
    cache = FrameCache(budget_bytes=int(size * 2.5), name="test")

    cache.put("a", frame)
    cache.put("b", frame.copy())
    assert cache.stats()["entries"] == 2

    cache.put("c", frame.copy())
    stats = cache.stats()
    assert stats["entries"] == 2, "a third entry must evict, not accumulate"
    assert stats["evictions"] == 1
    assert stats["bytes"] <= cache.budget_bytes
    # 'a' was least recently used and is the one that went.
    assert cache.get("a") is None
    assert cache.get("b") is not None


def test_frame_cache_eviction_is_least_recently_used():
    frame = _frame(500)
    size = frame_nbytes(frame)
    cache = FrameCache(budget_bytes=int(size * 2.5), name="test")
    cache.put("a", frame)
    cache.put("b", frame.copy())
    # Touch 'a' so 'b' becomes the eviction candidate.
    cache.get("a")
    cache.put("c", frame.copy())
    assert cache.get("a") is not None
    assert cache.get("b") is None


def test_frame_cache_refuses_entry_larger_than_budget():
    """Storing it would evict everything and still not fit, so it is not stored."""
    small = _frame(10)
    big = _frame(20000)
    cache = FrameCache(budget_bytes=frame_nbytes(small) * 2, name="test")
    cache.put("small", small)
    cache.put("big", big)
    assert cache.get("big") is None
    assert cache.get("small") is not None, "an oversized insert must not evict the rest"
    assert cache.stats()["oversized"] == 1


def test_frame_cache_overwrites_without_double_counting():
    cache = FrameCache(budget_bytes=50 * 1024 * 1024, name="test")
    cache.put("k", _frame(200))
    first = cache.stats()["bytes"]
    cache.put("k", _frame(200))
    assert cache.stats()["entries"] == 1
    assert cache.stats()["bytes"] == pytest.approx(first, rel=0.05)


def test_frame_cache_clear_reports_released_bytes():
    cache = FrameCache(budget_bytes=50 * 1024 * 1024, name="test")
    cache.put("k", _frame(500))
    held = cache.stats()["bytes"]
    assert cache.clear() == held
    assert cache.stats()["entries"] == 0
    assert cache.stats()["bytes"] == 0


def test_frame_cache_invalidate_where():
    cache = FrameCache(budget_bytes=50 * 1024 * 1024, name="test")
    cache.put(("/a", 1), _frame(50))
    cache.put(("/a", 2), _frame(50))
    cache.put(("/b", 1), _frame(50))
    assert cache.invalidate_where(lambda key: key[0] == "/a") == 2
    assert cache.stats()["entries"] == 1
    assert cache.stats()["bytes"] > 0


# --------------------------------------------------------------------------------------
# 3. CacheRegistry
# --------------------------------------------------------------------------------------


def test_cache_registry_clears_everything_registered():
    registry = CacheRegistry()
    cache = FrameCache(budget_bytes=1024 * 1024, name="frames")
    cache.put("k", _frame(10))
    registry.register_cache(cache)
    registry.register("other", lambda: "cleared")

    released = registry.clear_all()
    assert cache.stats()["entries"] == 0
    assert released["other"] == "cleared"
    assert set(registry.names()) == {"frames", "other"}


def test_cache_registry_survives_a_failing_member():
    """One broken cache must not stop the reclaim that the others need."""
    registry = CacheRegistry()
    good = FrameCache(budget_bytes=1024 * 1024, name="good")
    good.put("k", _frame(10))
    registry.register_cache(good)

    def explode():
        raise RuntimeError("boom")

    registry.register("bad", explode)

    released = registry.clear_all()
    assert "error: RuntimeError" in str(released["bad"])
    assert good.stats()["entries"] == 0, "the healthy cache must still be cleared"


def test_cache_registry_stats_tolerates_missing_and_broken_stats():
    registry = CacheRegistry()
    registry.register("no_stats", lambda: None)
    registry.register("broken", lambda: None, lambda: 1 / 0)
    stats = registry.stats()
    assert "no_stats" not in stats
    assert "error: ZeroDivisionError" in str(stats["broken"])


def test_registered_lru_cache_is_reclaimable():
    from src.campbell_ai.resources import CACHES, registered_lru_cache

    calls = []

    @registered_lru_cache("test.lru", maxsize=4)
    def compute(value):
        calls.append(value)
        return value * 2

    compute(2)
    compute(2)
    assert calls == [2], "second call should hit the cache"
    assert CACHES.stats()["test.lru"]["currsize"] == 1

    CACHES.clear_all()
    compute(2)
    assert calls == [2, 2], "clearing the registry must empty the lru cache"


def test_registered_lru_cache_honours_env_var(monkeypatch):
    from src.campbell_ai.resources import CACHES, registered_lru_cache

    monkeypatch.setenv("TEST_LRU_SIZE", "3")

    @registered_lru_cache("test.lru_env", maxsize=64, env_var="TEST_LRU_SIZE")
    def compute(value):
        return value

    for value in range(10):
        compute(value)
    assert CACHES.stats()["test.lru_env"]["maxsize"] == 3


# --------------------------------------------------------------------------------------
# 4/5. Repository caching and probing
# --------------------------------------------------------------------------------------


@pytest.fixture
def dataset_root():
    """A data root shaped like the real one, with one small alerts CSV."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        alerts = root / "alerts" / "golden" / "cda"
        alerts.mkdir(parents=True)
        (alerts / "consolidated_alerts.csv").write_text(
            "UnitId,Timestamp,note\n"
            "U1,2026-01-01,ok\n"
            'U2,2026-01-02,"has\nnewline"\n',
            encoding="utf-8",
            newline="",
        )
        yield root


def _repo(root, budget_bytes=50 * 1024 * 1024):
    """Repository with isolated caches, so assertions are about this test only."""
    return DashboardDataRepository(
        root,
        frame_cache=FrameCache(budget_bytes=budget_bytes, name="isolated"),
        probe_cache={},
    )


def test_repository_uses_the_injected_bounded_cache(dataset_root):
    repo = _repo(dataset_root)
    cache = repo._frames

    assert len(repo.load("alerts", "cda")) == 2
    assert cache.stats()["entries"] == 1

    repo.load("alerts", "cda")
    assert cache.stats()["hits"] >= 1, "a second load must be served from cache"


def test_repository_frames_are_bounded_by_the_budget(dataset_root):
    """A tiny budget proves the repository cannot accumulate past it."""
    repo = _repo(dataset_root, budget_bytes=1)
    for _ in range(5):
        assert len(repo.load("alerts", "cda")) == 2
    stats = repo._frames.stats()
    assert stats["bytes"] <= repo._frames.budget_bytes
    assert stats["entries"] == 0, "nothing fits, so nothing is retained"


def test_repository_retires_stale_mtime_entries(dataset_root):
    """A re-synced file must not leave its previous generation resident."""
    repo = _repo(dataset_root)
    repo.load("alerts", "cda")
    assert repo._frames.stats()["entries"] == 1

    path = dataset_root / "alerts" / "golden" / "cda" / "consolidated_alerts.csv"
    path.write_text(
        "UnitId,Timestamp,note\nU9,2026-02-01,new\n", encoding="utf-8", newline=""
    )
    # Move mtime forward explicitly; a same-second rewrite can otherwise collide.
    future = time.time() + 10
    os.utime(path, (future, future))

    assert len(repo.load("alerts", "cda")) == 1
    assert repo._frames.stats()["entries"] == 1, "the stale generation must be dropped"


def test_probe_counts_rows_without_parsing_the_file(dataset_root, monkeypatch):
    """The probe must not fall back to a full parse; quoted newlines still count once."""
    repo = _repo(dataset_root)

    import src.campbell_ai.data as data_module

    original = data_module.pd.read_csv
    full_reads = []

    def watched_read_csv(*args, **kwargs):
        # nrows=0 is the header sniff and is expected; anything else is a real parse.
        if kwargs.get("nrows") != 0:
            full_reads.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(data_module.pd, "read_csv", watched_read_csv)

    probe = repo._probe_frame(
        dataset_root / "alerts" / "golden" / "cda" / "consolidated_alerts.csv"
    )
    assert probe["rows"] == 2
    assert probe["columns"] == ["UnitId", "Timestamp", "note"]
    assert full_reads == [], "row counting must not parse the CSV"


def test_probe_cache_is_bounded(dataset_root):
    repo = _repo(dataset_root)
    path = dataset_root / "alerts" / "golden" / "cda" / "consolidated_alerts.csv"
    import src.campbell_ai.data as data_module

    for index in range(data_module._MAX_PROBE_ENTRIES + 20):
        stamp = time.time() + index
        os.utime(path, (stamp, stamp))
        repo._probe_frame(path)
    assert len(repo._probe_cache) <= data_module._MAX_PROBE_ENTRIES


def test_validation_does_not_materialize_frames(dataset_root):
    repo = _repo(dataset_root)
    status = repo.validate_client("CDA")
    assert status["datasets"]["alerts"]["rows"] == 2
    assert repo._frames.stats()["entries"] == 0


def test_probe_and_reclaim_take_the_same_lock(dataset_root, monkeypatch):
    """The probe cache is process-wide, so its lock has to be too.

    The bug this pins down: `_probe_frame` used a per-*instance* lock while the janitor's
    registered `clear()` took none at all. The trim loop reads `len()`, then
    `next(iter(...))`, then `pop()`; a `clear()` landing between them raises `KeyError` or
    `RuntimeError: dictionary changed size during iteration`. Both were reproduced in
    isolation with three writer threads and a short switch interval.

    Asserted by instrumenting the lock rather than by racing threads: a stress test only
    fails when it happens to win the race, and one that passes for the wrong reason is
    worse than none - the first version of this test passed even with the lock removed,
    because the constant clearing kept the cache below the trim threshold so the
    vulnerable loop never ran.
    """
    import src.campbell_ai.data as data_module
    from src.campbell_ai.resources import CACHES

    real_lock = data_module._PROBE_LOCK
    entered: list[str] = []

    class TrackingLock:
        def __init__(self, label):
            self.label = label

        def __enter__(self):
            entered.append(self.label)
            return real_lock.__enter__()

        def __exit__(self, *exc):
            return real_lock.__exit__(*exc)

    monkeypatch.setattr(data_module, "_PROBE_LOCK", TrackingLock("probe-lock"))

    # The shared cache on purpose: that is the one the janitor reaches.
    repo = DashboardDataRepository(
        dataset_root, frame_cache=FrameCache(budget_bytes=1024 * 1024, name="isolated")
    )
    data_module.shared_probe_cache()
    path = dataset_root / "alerts" / "golden" / "cda" / "consolidated_alerts.csv"

    repo._probe_frame(path)
    assert entered, "the probe path must hold the process-wide lock"

    entered.clear()
    CACHES.clear_all()
    assert entered, "the janitor's clear() must hold the same lock the probe path holds"


def test_the_service_singleton_is_never_reclaimable():
    """`get_service` owns the session store and the job registry.

    Registering it would make a memory reclaim discard live conversations and answers in
    flight. This asserts the hazard stays absent rather than trusting a comment.
    """
    import os as _os

    _os.environ.setdefault("CAMPBELL_AI_PERSISTENCE", "false")
    from src.campbell_ai.api import get_service
    from src.campbell_ai.resources import CACHES

    get_service()
    for name in CACHES.names():
        assert "service" not in name, f"{name} must not be reclaimable"
        assert "session" not in name, f"{name} must not be reclaimable"
        assert "job" not in name, f"{name} must not be reclaimable"


def test_prompt_cache_is_registered_and_still_has_its_own_clear():
    from src.campbell_ai.prompts import clear_prompt_cache, load_prompt
    from src.campbell_ai.resources import CACHES

    load_prompt("planner_base.md")
    assert CACHES.stats()["campbell_ai.prompts"]["currsize"] >= 1

    # The pre-existing helper must keep working alongside the registry.
    clear_prompt_cache()
    assert CACHES.stats()["campbell_ai.prompts"]["currsize"] == 0

    load_prompt("planner_base.md")
    CACHES.clear_all()
    assert CACHES.stats()["campbell_ai.prompts"]["currsize"] == 0


# --------------------------------------------------------------------------------------
# 6. Janitor
# --------------------------------------------------------------------------------------


def _janitor(**kwargs) -> ResourceJanitor:
    defaults = dict(
        interval_seconds=5,
        idle_seconds=0,
        rss_watermark_bytes=None,
        thread_warn_threshold=10_000,
    )
    defaults.update(kwargs)
    return ResourceJanitor(**defaults)


def test_janitor_reclaims_under_memory_pressure(monkeypatch):
    janitor = _janitor(rss_watermark_bytes=100)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: 500)

    report = janitor.tick()
    assert report is not None
    assert report["reason"] == "memory_pressure"
    assert janitor.stats()["reclaims_pressure"] == 1


def test_janitor_stays_quiet_below_the_watermark(monkeypatch):
    janitor = _janitor(rss_watermark_bytes=1000)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: 10)
    assert janitor.tick() is None
    assert janitor.stats()["reclaims_pressure"] == 0


def test_janitor_respects_the_pressure_cooldown(monkeypatch):
    """Repeating a reclaim that did not help every tick only burns CPU."""
    janitor = _janitor(rss_watermark_bytes=100, pressure_cooldown_seconds=3600)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: 500)

    assert janitor.tick() is not None
    assert janitor.tick() is None, "second tick inside the cooldown must not reclaim"
    assert janitor.stats()["reclaims_pressure"] == 1


def test_janitor_cannot_reclaim_when_rss_is_unavailable(monkeypatch):
    """Off Linux there is no RSS; 'cannot tell' must not mean 'reclaim constantly'."""
    janitor = _janitor(rss_watermark_bytes=100)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: None)
    assert janitor.tick() is None


def test_janitor_reclaims_once_per_idle_stretch(monkeypatch):
    janitor = _janitor(idle_seconds=1)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: 10)

    janitor.touch()
    assert janitor.tick() is None, "not idle yet"

    time.sleep(1.05)
    report = janitor.tick()
    assert report is not None and report["reason"] == "inactivity"

    # Still idle, but already reclaimed for this stretch.
    assert janitor.tick() is None
    assert janitor.stats()["reclaims_idle"] == 1

    # New activity, then idle again: eligible once more.
    janitor.touch()
    time.sleep(1.05)
    assert janitor.tick() is not None
    assert janitor.stats()["reclaims_idle"] == 2


def test_janitor_idle_disabled_by_zero(monkeypatch):
    janitor = _janitor(idle_seconds=0)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: 10)
    time.sleep(0.05)
    assert janitor.tick() is None


def test_janitor_force_reclaim_ignores_watermark(monkeypatch):
    janitor = _janitor(rss_watermark_bytes=10**12)
    monkeypatch.setattr("src.campbell_ai.janitor.process_rss_bytes", lambda: 1)
    assert janitor.force_reclaim("manual")["reason"] == "manual"


def test_janitor_start_and_stop_is_clean():
    janitor = _janitor(interval_seconds=5)
    janitor.start()
    assert janitor.stats()["running"] is True
    janitor.stop(timeout=2)
    assert janitor.stats()["running"] is False


def test_watermark_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_RSS_LIMIT_MB", "256")
    assert watermark_from_env() == 256 * 1024 * 1024


def test_watermark_falls_back_when_env_is_garbage(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_RSS_LIMIT_MB", "not-a-number")
    monkeypatch.setattr(
        "src.campbell_ai.resources.container_memory_limit_bytes", lambda: None
    )
    assert watermark_from_env(fallback_mb=123) == 123 * 1024 * 1024


def test_watermark_derives_from_cgroup_limit(monkeypatch):
    monkeypatch.delenv("CAMPBELL_AI_RSS_LIMIT_MB", raising=False)
    monkeypatch.setattr(
        "src.campbell_ai.resources.container_memory_limit_bytes",
        lambda: 1000 * 1024 * 1024,
    )
    assert watermark_from_env(limit_ratio=0.5) == 500 * 1024 * 1024


def test_watermark_default_sits_above_the_measured_peak(monkeypatch):
    """The watermark is the trigger, and it has to clear ordinary load.

    At or below the measured 3-user peak it would fire during normal operation, and a
    watchdog that trips constantly is noise rather than protection.
    """
    from src.campbell_ai.resources import (
        DEFAULT_FALLBACK_WATERMARK_MB,
        MEASURED_PEAK_FLOW_MB,
        MEGABYTE,
        PEAK_HEADROOM_RATIO,
    )

    monkeypatch.delenv("CAMPBELL_AI_RSS_LIMIT_MB", raising=False)
    monkeypatch.setattr(
        "src.campbell_ai.resources.container_memory_limit_bytes", lambda: None
    )

    assert PEAK_HEADROOM_RATIO == 1.5
    assert DEFAULT_FALLBACK_WATERMARK_MB == int(MEASURED_PEAK_FLOW_MB * 1.5)

    watermark = watermark_from_env()
    assert watermark == DEFAULT_FALLBACK_WATERMARK_MB * MEGABYTE
    # Clear of the measured peak, by the declared margin.
    assert watermark > MEASURED_PEAK_FLOW_MB * MEGABYTE
    # And clear of the 5-user peak measured at 547 MB, so a burst beyond the expected load
    # does not shed cache either.
    assert watermark > 547 * MEGABYTE


def test_a_real_cgroup_limit_beats_the_assumed_ceiling(monkeypatch):
    """A limit granted later must take effect without touching configuration.

    This is why the default is not an ENV in the Dockerfile: baked in, it would keep
    overriding whatever the deployment actually granted.
    """
    monkeypatch.delenv("CAMPBELL_AI_RSS_LIMIT_MB", raising=False)
    monkeypatch.setattr(
        "src.campbell_ai.resources.container_memory_limit_bytes",
        lambda: 2048 * 1024 * 1024,
    )
    assert watermark_from_env() == int(2048 * 1024 * 1024 * 0.72)


def test_memory_snapshot_shape():
    payload = memory_snapshot()
    for key in ("rss_bytes", "limit_bytes", "rss_pct_of_limit"):
        assert key in payload


# --------------------------------------------------------------------------------------
# 6b. Linux memory probing
#
# This is the section that decides whether the watchdog works at all, and it is dead code
# on any non-Linux developer machine: /proc and the cgroup files do not exist, so every
# function here returns None locally and the parsing would first execute in production.
# The paths are module-level for exactly this reason - these tests point them at fixtures.
# --------------------------------------------------------------------------------------


@pytest.fixture
def fake_proc(monkeypatch):
    """Write fake /proc and cgroup files and point the module at them."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def install(name: str, attribute: str, content: str) -> Path:
            path = root / name
            path.write_text(content, encoding="utf-8")
            monkeypatch.setattr(f"src.campbell_ai.resources.{attribute}", path)
            return path

        yield install


def test_process_rss_parses_statm(monkeypatch, fake_proc):
    """Field 2 of statm is resident pages; the value is pages x page size, not bytes."""
    from src.campbell_ai import resources

    # total=5000 pages, resident=1234 pages, then fields we ignore.
    fake_proc("statm", "_PROC_STATM", "5000 1234 100 10 0 200 0\n")
    monkeypatch.setattr(resources.os, "sysconf", lambda name: 4096, raising=False)

    assert resources.process_rss_bytes() == 1234 * 4096


def test_process_rss_returns_none_without_proc(monkeypatch):
    """Off Linux the answer is 'cannot tell', which callers must not read as 'fine'."""
    from src.campbell_ai import resources

    monkeypatch.setattr(
        resources, "_PROC_STATM", Path("/definitely/not/here/statm")
    )
    assert resources.process_rss_bytes() is None


def test_process_rss_survives_malformed_statm(fake_proc):
    from src.campbell_ai import resources

    fake_proc("statm", "_PROC_STATM", "only-one-field\n")
    assert resources.process_rss_bytes() is None


def test_cgroup_v2_limit_is_preferred(fake_proc):
    """A current Docker Engine gives v2; reading the wrong file yields 'no limit'."""
    from src.campbell_ai import resources

    fake_proc("memory.max", "_CGROUP_V2_LIMIT", "1073741824\n")
    fake_proc("limit_in_bytes", "_CGROUP_V1_LIMIT", "536870912\n")
    assert resources.container_memory_limit_bytes() == 1073741824


def test_cgroup_v1_limit_is_the_fallback(monkeypatch, fake_proc):
    from src.campbell_ai import resources

    monkeypatch.setattr(
        resources, "_CGROUP_V2_LIMIT", Path("/definitely/not/here/memory.max")
    )
    fake_proc("limit_in_bytes", "_CGROUP_V1_LIMIT", "536870912\n")
    assert resources.container_memory_limit_bytes() == 536870912


def test_unlimited_cgroup_v2_reports_no_limit(monkeypatch, fake_proc):
    """v2 writes the literal string 'max' when unlimited."""
    from src.campbell_ai import resources

    fake_proc("memory.max", "_CGROUP_V2_LIMIT", "max\n")
    monkeypatch.setattr(
        resources, "_CGROUP_V1_LIMIT", Path("/definitely/not/here/limit")
    )
    assert resources.container_memory_limit_bytes() is None


def test_unlimited_cgroup_v1_sentinel_is_rejected(monkeypatch, fake_proc):
    """v1 writes a number near 2**63 instead of a word; treating it as a real limit
    would put the watermark at petabytes and disable the watchdog silently."""
    from src.campbell_ai import resources

    monkeypatch.setattr(
        resources, "_CGROUP_V2_LIMIT", Path("/definitely/not/here/memory.max")
    )
    fake_proc("limit_in_bytes", "_CGROUP_V1_LIMIT", "9223372036854771712\n")
    assert resources.container_memory_limit_bytes() is None


def test_cgroup_usage_is_read_separately(fake_proc):
    """Usage includes page cache; it is reported, never used as the trigger."""
    from src.campbell_ai import resources

    fake_proc("memory.current", "_CGROUP_V2_USAGE", "805306368\n")
    assert resources.container_memory_usage_bytes() == 805306368


def test_memory_snapshot_computes_percentage_of_limit(monkeypatch, fake_proc):
    """The single number an operator reads first has to be right."""
    from src.campbell_ai import resources

    fake_proc("statm", "_PROC_STATM", "5000 131072 0 0 0 0 0\n")  # 512 MB at 4 KB pages
    fake_proc("memory.max", "_CGROUP_V2_LIMIT", str(1024 * 1024 * 1024) + "\n")
    monkeypatch.setattr(resources.os, "sysconf", lambda name: 4096, raising=False)

    snapshot = resources.memory_snapshot()
    assert snapshot["rss_mb"] == 512.0
    assert snapshot["limit_mb"] == 1024.0
    assert snapshot["rss_pct_of_limit"] == 50.0


def test_memory_snapshot_percentage_is_none_without_a_limit(monkeypatch, fake_proc):
    """No cgroup limit means no percentage - and the runbook says to set one."""
    from src.campbell_ai import resources

    fake_proc("statm", "_PROC_STATM", "5000 131072 0 0 0 0 0\n")
    monkeypatch.setattr(resources, "container_memory_limit_bytes", lambda: None)
    assert resources.memory_snapshot()["rss_pct_of_limit"] is None


def test_watermark_from_a_realistic_cgroup_limit(monkeypatch, fake_proc):
    """End to end: a 1 GB container must produce a sub-limit watermark, since a reclaim
    has to run while there is still room to allocate the machinery that performs it."""
    from src.campbell_ai import resources

    monkeypatch.delenv("CAMPBELL_AI_RSS_LIMIT_MB", raising=False)
    fake_proc("memory.max", "_CGROUP_V2_LIMIT", str(1024 * 1024 * 1024) + "\n")

    watermark = resources.watermark_from_env()
    assert watermark == int(1024 * 1024 * 1024 * 0.72)
    assert watermark < 1024 * 1024 * 1024


def test_janitor_pressure_fires_against_a_real_rss_reading(monkeypatch, fake_proc):
    """The pressure path driven by the actual probes rather than a stubbed function."""
    from src.campbell_ai import resources

    # 800 MB resident against a 1 GB limit: past the 72% watermark.
    fake_proc("statm", "_PROC_STATM", f"900000 {800 * 256} 0 0 0 0 0\n")
    fake_proc("memory.max", "_CGROUP_V2_LIMIT", str(1024 * 1024 * 1024) + "\n")
    monkeypatch.setattr(resources.os, "sysconf", lambda name: 4096, raising=False)
    monkeypatch.delenv("CAMPBELL_AI_RSS_LIMIT_MB", raising=False)

    janitor = ResourceJanitor(
        interval_seconds=5,
        idle_seconds=0,
        rss_watermark_bytes=resources.watermark_from_env(),
        thread_warn_threshold=10_000,
    )
    report = janitor.tick()
    assert report is not None and report["reason"] == "memory_pressure"
    assert report["rss_before_mb"] == 800.0


# --------------------------------------------------------------------------------------
# 7. Logging configuration and its scope
# --------------------------------------------------------------------------------------


def test_configure_api_logging_installs_a_bounded_rotating_handler(api_logging):
    from logging.handlers import RotatingFileHandler

    tmp, description = api_logging
    assert description["file"] == str(tmp / "campbell_api.log")
    assert description["max_disk_bytes"] == description["max_bytes"] * (
        description["backup_count"] + 1
    )
    handler = rotating_handler()
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes > 0 and handler.backupCount > 0
    assert logging_description()["logger"] == PACKAGE_LOGGER


def test_configure_api_logging_never_touches_the_root_logger(api_logging):
    """The scoping guarantee: this package must not reconfigure its host process."""
    root = logging.getLogger()
    assert not any(
        getattr(handler, "_campbell_ai_managed", False) for handler in root.handlers
    ), "no handler of ours may be attached to root"
    package = logging.getLogger(PACKAGE_LOGGER)
    assert any(
        getattr(handler, "_campbell_ai_managed", False) for handler in package.handlers
    )
    assert package.propagate is False, "propagating would duplicate every line into root"


def test_reset_api_logging_detaches_everything(api_logging):
    reset_api_logging()
    package = logging.getLogger(PACKAGE_LOGGER)
    assert not any(
        getattr(handler, "_campbell_ai_managed", False) for handler in package.handlers
    )
    assert package.propagate is True
    assert logging_description() == {}


def test_importing_the_package_configures_no_logging_and_starts_no_thread():
    """Import must stay inert: only the API process may acquire handlers and threads."""
    import importlib
    import threading

    reset_api_logging()
    before = threading.active_count()
    for module in ("src.campbell_ai.data", "src.campbell_ai.resources"):
        importlib.reload(importlib.import_module(module))

    assert logging_description() == {}, "importing must not configure logging"
    assert threading.active_count() == before, "importing must not start a thread"


def test_configure_api_logging_rotates_and_bounds_backups(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPBELL_AI_LOG_DIR", tmp)
        monkeypatch.setenv("CAMPBELL_AI_LOG_FILE", "rot.log")
        monkeypatch.setenv("CAMPBELL_AI_LOG_MAX_BYTES", "2048")
        monkeypatch.setenv("CAMPBELL_AI_LOG_BACKUP_COUNT", "2")
        monkeypatch.setenv("CAMPBELL_AI_LOG_CONSOLE", "false")
        try:
            configure_api_logging(force=True)
            logger = logging.getLogger("campbell_ai.rotation_test")
            for index in range(4000):
                logger.info("filler line %s with enough text to add up quickly", index)
            rotating_handler().flush()

            produced = sorted(path.name for path in Path(tmp).glob("rot.log*"))
            assert "rot.log" in produced
            # Active file plus at most backupCount rotations: bounded, unlike append-forever.
            assert len(produced) <= 3, produced
        finally:
            reset_api_logging()


def test_configure_api_logging_is_idempotent_without_force(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPBELL_AI_LOG_DIR", tmp)
        monkeypatch.setenv("CAMPBELL_AI_LOG_FILE", "a.log")
        try:
            first = configure_api_logging(force=True)
            monkeypatch.setenv("CAMPBELL_AI_LOG_FILE", "b.log")
            assert configure_api_logging() == first, "a later call must not reconfigure"
        finally:
            reset_api_logging()


# --------------------------------------------------------------------------------------
# 8. Log archiver
# --------------------------------------------------------------------------------------


class _FakeSink:
    """Records uploads; can be made to fail to prove files are not lost."""

    def __init__(self, fail=False):
        self.fail = fail
        self.uploaded = {}

    def exists(self, key):
        return key in self.uploaded

    def put_file(self, path, key):
        if self.fail:
            raise RuntimeError("network down")
        self.uploaded[key] = Path(path).read_bytes()


def _archiver(tmp: Path, sink, **kwargs) -> LogArchiver:
    return LogArchiver(
        log_dir=tmp,
        log_stem=kwargs.pop("log_stem", "campbell_api"),
        interval_seconds=kwargs.pop("interval_seconds", 1),
        bucket="test-bucket",
        sink=sink,
        **kwargs,
    )


def test_archiver_uploads_rotated_files_and_removes_them():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rotated = root / "campbell_api.log.1"
        rotated.write_text("historic log content\n" * 100, encoding="utf-8")

        sink = _FakeSink()
        result = _archiver(root, sink).run_cycle()

        assert result["archived"] == 1
        assert not rotated.exists(), "an archived file must not keep occupying the volume"
        assert len(sink.uploaded) == 1
        key = next(iter(sink.uploaded))
        assert key.endswith(".log.gz") and "campbellAI/logs" in key

        import gzip

        assert b"historic log content" in gzip.decompress(sink.uploaded[key])


def test_archiver_keeps_the_file_when_the_upload_fails():
    """A network blip must not be the reason a log disappears."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rotated = root / "campbell_api.log.1"
        rotated.write_text("keep me\n", encoding="utf-8")

        archiver = _archiver(root, _FakeSink(fail=True))
        result = archiver.run_cycle()

        assert result["archived"] == 0
        assert rotated.exists(), "the file must survive to be retried"
        assert not list(root.glob("*.gz")), "no intermediate should be left behind"
        assert archiver.stats()["failed"] == 1


def test_archiver_treats_an_already_present_object_as_success():
    """Re-running a partially completed cycle must not strand the file forever."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rotated = root / "campbell_api.log.1"
        rotated.write_text("content\n", encoding="utf-8")

        sink = _FakeSink()
        archiver = _archiver(root, sink)
        # Pretend a previous cycle uploaded it and then failed before deleting.
        sink.uploaded[archiver._s3_key(rotated)] = b"whatever"

        assert archiver.archive_file(rotated) is True
        assert not rotated.exists()


def test_archiver_only_touches_its_own_log_files():
    """The logs/ volume is shared; another process's files are not ours to ship."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "campbell_api.log").write_text("active\n", encoding="utf-8")
        (root / "campbell_api.log.1.gz").write_bytes(b"already compressed")
        (root / "campbell_api.log.2").write_text("rotated\n", encoding="utf-8")
        (root / "dashboard.log.1").write_text("not ours\n", encoding="utf-8")

        pending = [path.name for path in _archiver(root, _FakeSink()).rotated_files()]
        assert pending == ["campbell_api.log.2"]


def test_archiver_seals_the_active_log_once_it_goes_quiet(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPBELL_AI_LOG_DIR", tmp)
        monkeypatch.setenv("CAMPBELL_AI_LOG_FILE", "campbell_api.log")
        monkeypatch.setenv("CAMPBELL_AI_LOG_CONSOLE", "false")
        try:
            configure_api_logging(force=True)
            logging.getLogger("campbell_ai.seal_test").info("x" * 4000)
            rotating_handler().flush()

            root = Path(tmp)
            active = root / "campbell_api.log"
            assert active.stat().st_size >= 1024

            # Age the file past the interval so it counts as quiet.
            old = time.time() - 600
            os.utime(active, (old, old))

            sink = _FakeSink()
            result = _archiver(root, sink, interval_seconds=60).run_cycle()

            assert result["sealed"] is True
            assert result["archived"] == 1
        finally:
            reset_api_logging()


def test_archiver_leaves_a_recently_written_log_alone(api_logging):
    tmp, _ = api_logging
    logging.getLogger("campbell_ai.fresh").info("y" * 4000)
    rotating_handler().flush()
    archiver = _archiver(tmp, _FakeSink(), interval_seconds=3600)
    assert archiver.seal_active_log() is False


def test_archiver_runs_without_a_bucket():
    """No credentials must degrade to rotation, not to a crash."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "campbell_api.log.1").write_text("content\n", encoding="utf-8")
        archiver = LogArchiver(log_dir=root, interval_seconds=1, bucket=None)
        result = archiver.run_cycle()
        assert result["s3_enabled"] is False
        assert result["archived"] == 0
        assert (root / "campbell_api.log.1").exists()


def test_archiver_s3_key_is_stable_for_the_same_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rotated = root / "campbell_api.log.1"
        rotated.write_text("content\n", encoding="utf-8")
        archiver = _archiver(root, _FakeSink())
        assert archiver._s3_key(rotated) == archiver._s3_key(rotated)


# --------------------------------------------------------------------------------------
# 8b. Frontend observability
#
# `dashboard/campbell_ai/` is Campbell AI code running inside the dashboard's process. It
# is the only place that measures what a *user* waited, and it had no logger and no timing
# at all - so a latency complaint produced identical evidence whether the API or the
# dashboard around it was the slow part.
# --------------------------------------------------------------------------------------


@pytest.fixture
def ui_logging(monkeypatch):
    """Configure the frontend's logging into a temp dir, then detach it."""
    from src.campbell_ai.logging_setup import configure_ui_logging, reset_ui_logging

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv("CAMPBELL_AI_LOG_DIR", tmp)
        monkeypatch.setenv("CAMPBELL_AI_UI_LOG_FILE", "campbell_ui.log")
        try:
            yield Path(tmp), configure_ui_logging(force=True)
        finally:
            reset_ui_logging()


def test_ui_logging_writes_to_its_own_file(ui_logging):
    """The frontend cannot share the API's handler: different process, different file."""
    tmp, description = ui_logging
    assert description["file"] == str(tmp / "campbell_ui.log")
    assert description["logger"] == "campbell_ai.ui"

    logging.getLogger("campbell_ai.ui.client").warning("probe line")
    from src.campbell_ai.logging_setup import ui_rotating_handler

    ui_rotating_handler().flush()
    assert "probe line" in (tmp / "campbell_ui.log").read_text(encoding="utf-8")


def test_ui_logging_keeps_propagating_to_the_host(ui_logging):
    """Deliberate: dashboard.log must still receive what it received before.

    Silencing lines the dashboard's maintainers may depend on is not this package's call;
    adding a second rotated copy costs them nothing.
    """
    ui_logger = logging.getLogger("campbell_ai.ui")
    assert ui_logger.propagate is True
    assert ui_logging[1]["propagates_to_host"] is True


def test_ui_logging_is_independent_of_the_api_handler(ui_logging, monkeypatch):
    """Configuring one must not detach the other; both files exist side by side."""
    tmp, _ = ui_logging
    monkeypatch.setenv("CAMPBELL_AI_LOG_FILE", "campbell_api.log")
    try:
        configure_api_logging(force=True)
        from src.campbell_ai.logging_setup import ui_rotating_handler

        assert rotating_handler() is not None
        assert ui_rotating_handler() is not None
        assert rotating_handler() is not ui_rotating_handler()
        assert Path(rotating_handler().baseFilename).name == "campbell_api.log"
        assert Path(ui_rotating_handler().baseFilename).name == "campbell_ui.log"
    finally:
        reset_api_logging()


def test_ui_archiver_seals_its_own_handler_not_the_apis(ui_logging):
    """An archiver that grabbed 'the' handler would roll over the wrong file."""
    from src.campbell_ai.logging_setup import ui_rotating_handler

    tmp, _ = ui_logging
    logging.getLogger("campbell_ai.ui.client").warning("z" * 4000)
    ui_rotating_handler().flush()

    active = tmp / "campbell_ui.log"
    old = time.time() - 600
    os.utime(active, (old, old))

    sink = _FakeSink()
    archiver = LogArchiver(
        log_dir=tmp,
        log_stem="campbell_ui",
        interval_seconds=60,
        bucket="test-bucket",
        sink=sink,
        handler_provider=ui_rotating_handler,
    )
    result = archiver.run_cycle()
    assert result["sealed"] is True and result["archived"] == 1
    assert "campbell_ui-" in next(iter(sink.uploaded))


def _client(**kwargs):
    from dashboard.campbell_ai.client import CampbellAPIClient

    return CampbellAPIClient(
        base_url=kwargs.pop("base_url", "http://campbell-api:8000"),
        internal_token=kwargs.pop("internal_token", "token"),
        **kwargs,
    )


def test_client_logs_duration_and_company_on_success(monkeypatch, caplog):
    """The measurement that was missing: wall clock plus which client it was for."""
    import dashboard.campbell_ai.client as client_module

    class _Response:
        def read(self):
            return b'{"session_id": "s1"}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(client_module, "urlopen", lambda *a, **k: _Response())

    with caplog.at_level(logging.INFO, logger="campbell_ai.ui.client"):
        result = _client().initialize("user", "CDA")

    assert result == {"session_id": "s1"}
    line = "\n".join(record.getMessage() for record in caplog.records)
    assert "path=/api/v1/campbell-ai/initialize" in line
    assert "company=cda" in line
    assert "outcome=ok" in line
    assert "ms=" in line


def test_client_logs_a_warning_for_a_slow_call(monkeypatch, caplog):
    """A slow-but-successful call is the one the user complains about, so it warns."""
    import dashboard.campbell_ai.client as client_module

    class _Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(client_module, "urlopen", lambda *a, **k: _Response())
    monkeypatch.setattr(client_module, "SLOW_CALL_WARN_SECONDS", 0.0)

    with caplog.at_level(logging.INFO, logger="campbell_ai.ui.client"):
        _client().initialize("user", "CDA")

    assert [r.levelname for r in caplog.records] == ["WARNING"]


def test_client_records_the_outcome_when_unreachable(monkeypatch, caplog):
    """Failures are logged too, or the log only shows the calls that went well."""
    import dashboard.campbell_ai.client as client_module
    from dashboard.campbell_ai.client import CampbellAPIClientError
    from urllib.error import URLError

    def _boom(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(client_module, "urlopen", _boom)

    with caplog.at_level(logging.INFO, logger="campbell_ai.ui.client"):
        with pytest.raises(CampbellAPIClientError):
            _client().initialize("user", "CDA")

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "outcome=unreachable" in message
    assert "company=cda" in message


def test_client_records_the_http_status_and_kind(monkeypatch, caplog):
    """How long a 503 took separates 'refused at once' from 'died holding the request'."""
    import dashboard.campbell_ai.client as client_module
    from dashboard.campbell_ai.client import CampbellAPIClientError
    from urllib.error import HTTPError

    def _boom(*args, **kwargs):
        raise HTTPError("url", 503, "unavailable", {}, None)

    monkeypatch.setattr(client_module, "urlopen", _boom)

    with caplog.at_level(logging.INFO, logger="campbell_ai.ui.client"):
        with pytest.raises(CampbellAPIClientError):
            _client().initialize("user", "CDA")

    assert "outcome=http_503_unavailable" in "\n".join(
        record.getMessage() for record in caplog.records
    )


# --------------------------------------------------------------------------------------
# 8c. Streaming progress stays in the browser
#
# The regression these guard against: progress used to travel through
# `campbell-ai-stream-store`, whose consumer is a *server* callback declaring the whole
# conversation as State. Every tick therefore uploaded the entire history so the server
# could answer with no_update and a new status string - roughly one wasted round trip per
# second for the length of every answer, each holding a dashboard worker thread.
#
# The interval is not the fix and must stay short: the same `collect()` is what delivers
# the finished answer, so widening it would add dead time to the end of every response.
# --------------------------------------------------------------------------------------


STREAM_JS = Path(__file__).parent.parent / "dashboard" / "assets" / "campbell_ai_stream.js"


def test_collect_no_longer_emits_progress_to_the_server():
    """`collect()` feeds a server callback, so it must only hand over terminal payloads."""
    source = STREAM_JS.read_text(encoding="utf-8")
    collect = source.split("collect: function ()", 1)[1].split("progress: function", 1)[0]
    assert "running: true" not in collect, (
        "a `running` payload on this store reaches finalize_stream and uploads the history"
    )
    # The stall verdict is terminal and must still go through.
    assert "stalled: true" in collect


def test_progress_is_reported_clientside():
    source = STREAM_JS.read_text(encoding="utf-8")
    assert "progress: function (waitingAck, slowAfterSeconds)" in source
    progress = source.split("progress: function", 1)[1]
    # Everything the old server branch produced, now computed in the browser.
    assert "Pensando… " in progress
    assert "La consulta lleva " in progress
    assert "threshold" in progress


def test_progress_collapses_surplus_ticks():
    """The interval ticks ~3x per second while `elapsed` changes once."""
    source = STREAM_JS.read_text(encoding="utf-8")
    assert "lastReportedElapsed" in source
    # Reset on both start and stop, or a second question would report nothing until it
    # passed the previous one's second count.
    assert source.count("lastReportedElapsed = -1") == 2


def test_streaming_interval_stays_short():
    """`collect()` also delivers the finished answer, so this is answer latency."""
    from dashboard.campbell_ai.layout import JOB_POLL_INTERVAL_MS  # noqa: F401

    layout_source = (
        Path(__file__).parent.parent / "dashboard" / "campbell_ai" / "layout.py"
    ).read_text(encoding="utf-8")
    block = layout_source.split('id="campbell-ai-stream-poll"', 1)[1][:200]
    assert "interval=350" in block, (
        "widening this adds up to that much dead time before every answer renders"
    )


def test_progress_callback_does_not_upload_the_conversation():
    """The whole point: the progress path must carry no history State."""
    import os as _os

    _os.environ.setdefault("SKIP_S3_SYNC", "true")
    _os.environ.setdefault("CAMPBELL_AI_UI_LOG_ARCHIVE_ENABLED", "false")
    import dashboard.app as appmod

    deps = appmod.app.server.test_client().get("/_dash-dependencies").get_json()

    progress = [
        dep
        for dep in deps
        if dep.get("clientside_function")
        and [i.get("id") for i in dep.get("inputs", [])] == ["campbell-ai-stream-poll"]
        and [s.get("id") for s in dep.get("state", [])] == ["campbell-ai-waiting-ack"]
    ]
    assert len(progress) == 1, "the clientside progress callback is not registered"

    outputs = str(progress[0]["output"])
    for target in (
        "campbell-ai-status.children",
        "campbell-ai-status.color",
        "campbell-ai-waiting.is_open",
        "campbell-ai-waiting-body.children",
    ):
        assert target in outputs, target
    assert "history" not in str(progress[0].get("state"))


def test_terminal_payloads_still_reach_the_server():
    """Progress moved out; delivery of the answer itself must not have."""
    import os as _os

    _os.environ.setdefault("SKIP_S3_SYNC", "true")
    _os.environ.setdefault("CAMPBELL_AI_UI_LOG_ARCHIVE_ENABLED", "false")
    import dashboard.app as appmod

    deps = appmod.app.server.test_client().get("/_dash-dependencies").get_json()
    server_side = [
        dep
        for dep in deps
        if not dep.get("clientside_function")
        and any(i.get("id") == "campbell-ai-stream-store" for i in dep.get("inputs", []))
    ]
    assert len(server_side) == 1, "finalize_stream must still consume the stream store"
    assert "campbell-ai-history-store" in str(server_side[0].get("state")), (
        "the terminal path legitimately needs the history to append to"
    )


# --------------------------------------------------------------------------------------
# 9. Diagnostics
# --------------------------------------------------------------------------------------


def test_snapshot_carries_the_sections_an_operator_needs():
    payload = snapshot()
    for section in (
        "process",
        "memory",
        "caches",
        "janitor",
        "logging",
        "log_files",
        "log_archive",
        "gc",
        "disk",
    ):
        assert section in payload, section
    assert payload["process"]["name"] == "campbell-api"
    assert payload["process"]["thread_count"] >= 1
    assert isinstance(payload["process"]["thread_names"], list)


def test_snapshot_is_json_serializable():
    import json

    json.dumps(snapshot())


def test_tail_log_returns_the_last_lines():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tail.log"
        path.write_text(
            "".join(f"line {index}\n" for index in range(5000)), encoding="utf-8"
        )
        result = tail_log(10, log_file=path)
        assert result["returned_lines"] == 10
        assert result["lines"][-1] == "line 4999"
        assert result["lines"][0] == "line 4990"


def test_tail_log_handles_a_file_smaller_than_the_request():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "small.log"
        path.write_text("only\ntwo\n", encoding="utf-8")
        assert tail_log(500, log_file=path)["lines"] == ["only", "two"]


def test_tail_log_reports_a_missing_file():
    result = tail_log(10, log_file=Path("nope.log"))
    assert "error" in result and result["lines"] == []


def test_tail_log_caps_the_request():
    from src.campbell_ai.diagnostics import MAX_TAIL_LINES

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cap.log"
        path.write_text(
            "".join(f"line {index}\n" for index in range(MAX_TAIL_LINES + 500)),
            encoding="utf-8",
        )
        assert tail_log(MAX_TAIL_LINES + 500, log_file=path)["requested_lines"] == (
            MAX_TAIL_LINES
        )


# --------------------------------------------------------------------------------------
# 11. The query path must not deep-copy the dataset
#
# Every query method used to open with `self.load(...).copy()`, and `.copy()` with no
# argument is `deep=True`: the whole dataset was duplicated before any filter narrowed it,
# to return twenty rows. Measured at +59.8 MB for three concurrent queries over
# `alerts_detail` - the entire per-user cost of concurrency.
#
# It protected nothing: pandas 3 enforces Copy-on-Write unconditionally, and `load()`
# already returns a distinct object.
# --------------------------------------------------------------------------------------


def test_copy_on_write_is_enforced_by_this_pandas():
    """The premise the whole optimization rests on, asserted rather than assumed.

    If a future pandas made CoW optional again, the defensive copies would have to come
    back - so this fails loudly instead of letting the cache be silently corruptible.
    """
    assert int(pd.__version__.split(".")[0]) >= 3, (
        "below pandas 3 Copy-on-Write can be disabled, and load() would need a real copy"
    )


def test_load_returns_a_frame_the_caller_may_mutate(dataset_root):
    """Mutating what `load()` returns must never reach the cached frame."""
    repo = _repo(dataset_root)
    first = repo.load("alerts", "cda")
    original = str(first["note"].iloc[0])

    first["note"] = "MUTADO"
    first["columna_nueva"] = 1
    first.iloc[0, 0] = "TAMBIEN_MUTADO"

    second = repo.load("alerts", "cda")
    assert str(second["note"].iloc[0]) == original, "the cached frame was corrupted"
    assert "columna_nueva" not in second.columns
    assert repo._frames.stats()["hits"] >= 1, "the second load must come from cache"


def test_repeated_queries_return_identical_results(dataset_root):
    """The failure a shared, un-copied cache would produce: one query poisoning the next.

    The query methods replace whole columns (`pd.to_datetime`, `pd.to_numeric`) on the frame
    they get back, so this is the behaviour that has to hold for the copy to be removable.
    """
    repo = _repo(dataset_root)
    results = [repo.query_alerts("cda", limit=10) for _ in range(3)]
    assert results[0] == results[1] == results[2]


def test_no_query_method_deep_copies_its_dataset():
    """Pins the change itself, since a defensive `.copy()` is easy to re-add by reflex."""
    import re

    source = (
        Path(__file__).parent.parent / "src" / "campbell_ai" / "data.py"
    ).read_text(encoding="utf-8")

    # Anchored to an assignment so the pattern matches code and not the docstring in
    # `load()`, which quotes the old call shape to explain why it is gone.
    offenders = re.findall(
        r"^\s*\w+\s*=\s*self\.load\([^)]*\)\.copy\(\s*\)", source, re.MULTILINE
    )
    assert offenders == [], (
        f"{len(offenders)} site(s) deep-copy the whole dataset before filtering: {offenders}"
    )
    # `load()` documents why, so the reasoning survives without this test being read.
    assert "Do not add a defensive `.copy()` on the result." in source
