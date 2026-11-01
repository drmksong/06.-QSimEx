"""Separate schema3 main control journal over the immutable schema4 raw store."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from threading import Lock

from .fingerprint import fingerprint_snapshot
from .main_policy import MAXIMUM_STARTS
from .store import STORE_SCHEMA_VERSION, _atomic, _job_key


CONTROL_SCHEMA_VERSION = 3
_MEMORY_LOCK = Lock()


@dataclass
class MainPause(Exception):
    reason: str
    detail: object = None

    def __str__(self):
        return f"{self.reason}: {self.detail}"


@contextmanager
def single_writer(connection):
    """OS releases the lifetime lock even after a process crash; never steal a live lock."""
    path = connection.execute("PRAGMA database_list").fetchone()[2]
    descriptor = None
    if path:
        descriptor = os.open(path + ".main-control.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise RuntimeError("another main controller owns this database") from error
    elif not _MEMORY_LOCK.acquire(blocking=False):
        raise RuntimeError("another in-memory main controller is active")
    try:
        yield
    finally:
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        else:
            _MEMORY_LOCK.release()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def initialize_main_store(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != STORE_SCHEMA_VERSION:
        raise ValueError("main control requires raw schema4; no automatic migration")
    with _atomic(connection):
        connection.execute("CREATE TABLE IF NOT EXISTS main_control_schema (version INTEGER PRIMARY KEY)")
        versions = connection.execute("SELECT version FROM main_control_schema").fetchall()
        if versions and versions not in (
            [(1,)], [(2,)], [(CONTROL_SCHEMA_VERSION,)]
        ):
            raise ValueError("unsupported main control schema version")
        if not versions:
            connection.execute("INSERT INTO main_control_schema VALUES (?)",
                               (CONTROL_SCHEMA_VERSION,))
        connection.execute("""
            CREATE TABLE IF NOT EXISTS main_control_runs (
                run_id TEXT PRIMARY KEY, config_fingerprint TEXT NOT NULL,
                policy_snapshot TEXT NOT NULL, runtime_snapshot TEXT NOT NULL,
                state_json TEXT NOT NULL, status TEXT NOT NULL, reason TEXT)
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS main_control_starts (
                run_id TEXT NOT NULL REFERENCES main_control_runs(run_id),
                start_index INTEGER NOT NULL CHECK(start_index BETWEEN 1 AND {MAXIMUM_STARTS}),
                input_id TEXT NOT NULL, seed INTEGER NOT NULL,
                job_key TEXT NOT NULL, role TEXT NOT NULL, resuming INTEGER NOT NULL,
                status TEXT NOT NULL, expected_counts TEXT NOT NULL,
                PRIMARY KEY(run_id, start_index))
        """.format(MAXIMUM_STARTS=MAXIMUM_STARTS))
        starts_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='main_control_starts'"
        ).fetchone()[0]
        if f"BETWEEN 1 AND {MAXIMUM_STARTS}" not in starts_schema.upper():
            connection.execute("DROP TRIGGER IF EXISTS main_control_starts_no_delete")
            connection.execute("DROP TRIGGER IF EXISTS main_control_starts_identity_immutable")
            connection.execute("""
                CREATE TABLE main_control_starts_v3 (
                    run_id TEXT NOT NULL REFERENCES main_control_runs(run_id),
                    start_index INTEGER NOT NULL CHECK(start_index BETWEEN 1 AND {MAXIMUM_STARTS}),
                    input_id TEXT NOT NULL, seed INTEGER NOT NULL,
                    job_key TEXT NOT NULL, role TEXT NOT NULL, resuming INTEGER NOT NULL,
                    status TEXT NOT NULL, expected_counts TEXT NOT NULL,
                    PRIMARY KEY(run_id, start_index))
            """.format(MAXIMUM_STARTS=MAXIMUM_STARTS))
            connection.execute(
                "INSERT INTO main_control_starts_v3 SELECT * FROM main_control_starts")
            connection.execute("DROP TABLE main_control_starts")
            connection.execute(
                "ALTER TABLE main_control_starts_v3 RENAME TO main_control_starts")
        if versions in ([(1,)], [(2,)]):
            connection.execute("DROP TRIGGER IF EXISTS main_control_schema_no_update")
            connection.execute("UPDATE main_control_schema SET version=? WHERE version=?",
                               (CONTROL_SCHEMA_VERSION, versions[0][0]))
        connection.execute("""
            CREATE TABLE IF NOT EXISTS main_control_events (
                run_id TEXT NOT NULL REFERENCES main_control_runs(run_id),
                event_index INTEGER NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(run_id,event_index))
        """)
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS main_control_policy_immutable
            BEFORE UPDATE ON main_control_runs
            WHEN NEW.run_id != OLD.run_id OR NEW.config_fingerprint != OLD.config_fingerprint
              OR NEW.policy_snapshot != OLD.policy_snapshot OR NEW.runtime_snapshot != OLD.runtime_snapshot
            BEGIN SELECT RAISE(ABORT, 'main policy/runtime snapshot is immutable'); END
        """)
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS main_control_runs_no_delete
            BEFORE DELETE ON main_control_runs
            BEGIN SELECT RAISE(ABORT, 'main runs are immutable'); END
        """)
        for table in ("main_control_events", "main_control_schema"):
            for action in ("UPDATE", "DELETE"):
                connection.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
                    BEFORE {action} ON {table}
                    BEGIN SELECT RAISE(ABORT, 'main control journal is immutable'); END
                """)
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS main_control_starts_no_delete
            BEFORE DELETE ON main_control_starts
            BEGIN SELECT RAISE(ABORT, 'main starts are immutable'); END
        """)
        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS main_control_starts_identity_immutable
            BEFORE UPDATE ON main_control_starts
            WHEN NEW.run_id != OLD.run_id OR NEW.start_index != OLD.start_index
              OR NEW.input_id != OLD.input_id OR NEW.seed != OLD.seed
              OR NEW.job_key != OLD.job_key OR NEW.role != OLD.role
              OR NEW.resuming != OLD.resuming OR NEW.expected_counts != OLD.expected_counts
            BEGIN SELECT RAISE(ABORT, 'main start identity is immutable'); END
        """)


def open_run(connection, config, runtime, initial_state):
    runtime_json = _json(runtime)
    run_id = "main-" + fingerprint_snapshot(
        {"config": config.fingerprint, "runtime": runtime}).sha256_hex
    rows = connection.execute(
        "SELECT run_id, config_fingerprint, runtime_snapshot FROM main_control_runs").fetchall()
    matches = [row for row in rows if row[1] == config.fingerprint]
    if matches and matches != [(run_id, config.fingerprint, runtime_json)]:
        raise ValueError("main config/runtime mismatch; explicit review and a separate run database required")
    existing = connection.execute(
        "SELECT config_fingerprint, policy_snapshot, runtime_snapshot "
        "FROM main_control_runs WHERE run_id=?", (run_id,)).fetchone()
    expected = (config.fingerprint, config.snapshot_json, runtime_json)
    if existing is not None and existing != expected:
        raise ValueError("main config/runtime mismatch; explicit review and a separate run database required")
    with _atomic(connection):
        connection.execute("""
            INSERT OR IGNORE INTO main_control_runs VALUES (?, ?, ?, ?, ?, 'running', NULL)
        """, (run_id, config.fingerprint, config.snapshot_json, runtime_json, _json(initial_state)))
    return run_id, load_state(connection, run_id)


def load_state(connection, run_id):
    row = connection.execute("SELECT state_json FROM main_control_runs WHERE run_id=?",
                             (run_id,)).fetchone()
    if row is None:
        raise ValueError("unknown main run")
    return json.loads(row[0])


def checkpoint(connection, run_id, state, *, status="running", reason=None):
    with _atomic(connection):
        connection.execute(
            "UPDATE main_control_runs SET state_json=?, status=?, reason=? WHERE run_id=?",
            (_json(state), status, reason, run_id))


def starts_consumed(connection, run_id):
    return connection.execute("SELECT COUNT(*) FROM main_control_starts WHERE run_id=?",
                              (run_id,)).fetchone()[0]


def reserve_start(connection, run_id, job, *, input_id, role, resuming, expected_counts,
                  policy):
    # Called inside the runner's raw-attempt savepoint: the debit and raw start commit together.
    with _atomic(connection):
        count = starts_consumed(connection, run_id)
        if count >= policy.maximum_starts:
            raise MainPause("budget_exhausted", {"starts_consumed": count})
        total = sum(expected_counts.values())
        if total > policy.maximum_expected_joints:
            raise MainPause("high_cost_review", {"total_expected_joints": total,
                                               "per_set": expected_counts})
        connection.execute(
            "INSERT INTO main_control_starts VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)",
            (run_id, count + 1, input_id, job.realization_seed, _json(_job_key(job)),
             role, int(resuming), _json(expected_counts)))
    return count + 1


def reconcile_starts(connection, run_id):
    """Raw commit is authoritative if the controller died before its next checkpoint."""
    rows = connection.execute(
        "SELECT start_index, job_key FROM main_control_starts WHERE run_id=? ORDER BY start_index",
        (run_id,)).fetchall()
    with _atomic(connection):
        for index, key_json in rows:
            key = json.loads(key_json)
            statuses = connection.execute("""
                SELECT status FROM attempts WHERE manifest_id=? AND design_id=? AND block_id=?
                    AND sample_index=? AND realization_seed=? AND execution_fingerprint_digest=?
            """, key).fetchall()
            states = {s[0] for s in statuses}
            if "succeeded" in states and "running" in states:
                raise ValueError("ambiguous succeeded/running raw attempt")
            status = ("succeeded" if "succeeded" in states else "failed" if "failed" in states
                      else "interrupted" if "running" in states else "reserved")
            connection.execute("""
                UPDATE main_control_starts SET status=? WHERE run_id=? AND start_index=?
            """, (status, run_id, index))


def append_event(connection, run_id, kind, payload):
    with _atomic(connection):
        index = connection.execute(
            "SELECT COALESCE(MAX(event_index),0)+1 FROM main_control_events WHERE run_id=?",
            (run_id,)).fetchone()[0]
        connection.execute("INSERT INTO main_control_events VALUES (?, ?, ?, ?)",
                           (run_id, index, kind, _json(payload)))
    return index
