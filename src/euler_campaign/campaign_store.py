"""Crash-safe, append-only persistence for Euler campaign revisions and runs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import MISSING, fields, is_dataclass
import json
from math import isfinite
from pathlib import Path
import sqlite3
from threading import RLock
from types import ModuleType
from typing import Any, Generator

from . import campaign, config, coverage, euler, geometry, models, profiles, qprime
from .campaign import (
    CampaignPlan,
    CampaignState,
    RoundRecord,
    _plan_fingerprint,
    _validate_state,
    validate_plan,
)
from .config import CampaignProject, _validate_campaign_revision
from .coverage import CoverageGrid, audit_simulation
from .profiles import SimulationResult

_SCHEMA_VERSION = 1
_DATA_MODULES: tuple[ModuleType, ...] = (
    campaign, config, coverage, euler, geometry, models, profiles, qprime,
)


def _dataclass_registry() -> dict[str, type[Any]]:
    registry: dict[str, type[Any]] = {}
    for module in _DATA_MODULES:
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == module.__name__
                and is_dataclass(value)
            ):
                registry[f"{value.__module__}.{value.__qualname__}"] = value
    return registry


_DATACLASSES = _dataclass_registry()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not (-float("inf") < value < float("inf")):
            raise ValueError("campaign persistence does not support non-finite floats")
        return value
    if is_dataclass(value) and not isinstance(value, type):
        type_name = f"{type(value).__module__}.{type(value).__qualname__}"
        if _DATACLASSES.get(type_name) is not type(value):
            raise TypeError(f"unsupported campaign record type: {type_name}")
        return {
            "$type": type_name,
            "fields": {
                field.name: _encode(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, tuple):
        return {"$tuple": [_encode(item) for item in value]}
    if isinstance(value, frozenset):
        encoded = [_encode(item) for item in value]
        encoded.sort(key=_canonical_json)
        return {"$frozenset": encoded}
    if isinstance(value, list):
        return {"$list": [_encode(item) for item in value]}
    if isinstance(value, dict):
        encoded_pairs = [(_encode(key), _encode(item)) for key, item in value.items()]
        encoded_pairs.sort(key=lambda pair: _canonical_json(pair[0]))
        return {"$dict": encoded_pairs}
    raise TypeError(f"unsupported campaign persistence value: {type(value).__name__}")


def _decode(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("persisted campaign floats must be finite")
        return value
    if not isinstance(value, dict):
        raise ValueError("invalid campaign persistence payload")
    if set(value) == {"$type", "fields"}:
        type_name = value["$type"]
        cls = _DATACLASSES.get(type_name) if isinstance(type_name, str) else None
        if cls is None:
            raise ValueError(f"unsupported persisted campaign record type: {type_name}")
        raw_fields = value["fields"]
        if not isinstance(raw_fields, dict):
            raise ValueError("persisted dataclass fields must be a mapping")
        dataclass_fields = fields(cls)
        expected = {field.name for field in dataclass_fields}
        missing_required = {
            field.name
            for field in dataclass_fields
            if field.name not in raw_fields
            and field.default is MISSING
            and field.default_factory is MISSING
        }
        if not raw_fields.keys() <= expected or missing_required:
            raise ValueError(f"persisted fields do not match {type_name}")
        return cls(**{name: _decode(item) for name, item in raw_fields.items()})
    if set(value) == {"$tuple"} and isinstance(value["$tuple"], list):
        return tuple(_decode(item) for item in value["$tuple"])
    if set(value) == {"$frozenset"} and isinstance(value["$frozenset"], list):
        return frozenset(_decode(item) for item in value["$frozenset"])
    if set(value) == {"$list"} and isinstance(value["$list"], list):
        return [_decode(item) for item in value["$list"]]
    if set(value) == {"$dict"} and isinstance(value["$dict"], list):
        pairs = value["$dict"]
        if any(not isinstance(pair, list) or len(pair) != 2 for pair in pairs):
            raise ValueError("persisted mapping entries must be key/value pairs")
        decoded = [(_decode(pair[0]), _decode(pair[1])) for pair in pairs]
        result = dict(decoded)
        if len(result) != len(decoded):
            raise ValueError("persisted mapping contains duplicate keys")
        return result
    raise ValueError("unknown tagged campaign persistence value")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _dump(value: Any) -> str:
    return _canonical_json(_encode(value))


def _load(payload: str) -> Any:
    try:
        value = json.loads(
            payload,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError("persisted campaign JSON is invalid") from error
    return _decode(value)


class SQLiteCampaignStore:
    """SQLite store with atomic round checkpoints and generation-scoped results.

    Plan revisions and simulation results are insert-only. A completed round and
    its next state are committed in one transaction; state snapshots remain
    replaceable so a campaign can resume after each checkpoint.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            self.path, timeout=30.0, isolation_level=None, check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._initialize_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def _initialize_schema(self) -> None:
        with self._lock:
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, _SCHEMA_VERSION):
                raise RuntimeError(
                    f"unsupported campaign database version: {version}"
                )
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS legacy_plans (
                    campaign_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_states (
                    campaign_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_simulations (
                    campaign_id TEXT NOT NULL,
                    domain_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (campaign_id, domain_id)
                );
                CREATE TABLE IF NOT EXISTS legacy_rounds (
                    campaign_id TEXT NOT NULL,
                    lineage_start_signature_id TEXT NOT NULL,
                    round_index INTEGER NOT NULL,
                    record_payload TEXT NOT NULL,
                    state_payload TEXT NOT NULL,
                    PRIMARY KEY (
                        campaign_id, lineage_start_signature_id, round_index
                    )
                );
                CREATE TABLE IF NOT EXISTS campaign_revisions (
                    campaign_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    parent_revision INTEGER,
                    parent_plan_fingerprint TEXT,
                    plan_fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (campaign_id, plan_revision)
                );
                CREATE TABLE IF NOT EXISTS campaign_generations (
                    campaign_id TEXT NOT NULL,
                    run_generation_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    simulation_fingerprint TEXT NOT NULL,
                    created_order INTEGER PRIMARY KEY AUTOINCREMENT,
                    UNIQUE (campaign_id, run_generation_id)
                );
                CREATE TABLE IF NOT EXISTS campaign_run_states (
                    campaign_id TEXT NOT NULL,
                    run_generation_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (campaign_id, run_generation_id, plan_revision),
                    FOREIGN KEY (campaign_id, run_generation_id)
                        REFERENCES campaign_generations(campaign_id, run_generation_id)
                );
                CREATE TABLE IF NOT EXISTS campaign_simulations (
                    campaign_id TEXT NOT NULL,
                    run_generation_id TEXT NOT NULL,
                    simulation_fingerprint TEXT NOT NULL,
                    signature_id TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    domain_id TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (
                        campaign_id, run_generation_id, simulation_fingerprint,
                        signature_id, seed
                    ),
                    UNIQUE (campaign_id, run_generation_id, domain_id),
                    FOREIGN KEY (campaign_id, run_generation_id)
                        REFERENCES campaign_generations(campaign_id, run_generation_id)
                );
                CREATE TABLE IF NOT EXISTS campaign_rounds (
                    campaign_id TEXT NOT NULL,
                    run_generation_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL,
                    lineage_start_signature_id TEXT NOT NULL,
                    round_index INTEGER NOT NULL,
                    record_payload TEXT NOT NULL,
                    state_payload TEXT NOT NULL,
                    PRIMARY KEY (
                        campaign_id, run_generation_id, plan_revision,
                        lineage_start_signature_id, round_index
                    ),
                    FOREIGN KEY (campaign_id, run_generation_id)
                        REFERENCES campaign_generations(campaign_id, run_generation_id)
                );
                CREATE TRIGGER IF NOT EXISTS immutable_campaign_revisions_update
                BEFORE UPDATE ON campaign_revisions
                BEGIN
                    SELECT RAISE(ABORT, 'campaign revisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS immutable_campaign_revisions_delete
                BEFORE DELETE ON campaign_revisions
                BEGIN
                    SELECT RAISE(ABORT, 'campaign revisions are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS immutable_campaign_simulations_update
                BEFORE UPDATE ON campaign_simulations
                BEGIN
                    SELECT RAISE(ABORT, 'campaign simulations are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS immutable_campaign_simulations_delete
                BEFORE DELETE ON campaign_simulations
                BEGIN
                    SELECT RAISE(ABORT, 'campaign simulations are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS immutable_campaign_rounds_update
                BEFORE UPDATE ON campaign_rounds
                BEGIN
                    SELECT RAISE(ABORT, 'campaign rounds are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS immutable_campaign_rounds_delete
                BEFORE DELETE ON campaign_rounds
                BEGIN
                    SELECT RAISE(ABORT, 'campaign rounds are append-only');
                END;
                """
            )
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    @staticmethod
    def _insert_immutable(
        connection: sqlite3.Connection,
        query: str,
        values: tuple[Any, ...],
        select_query: str,
        select_values: tuple[Any, ...],
        expected_payload: str,
        record_name: str,
    ) -> None:
        connection.execute(query, values)
        row = connection.execute(select_query, select_values).fetchone()
        if row is None or row["payload"] != expected_payload:
            raise ValueError(f"conflicting immutable {record_name} already exists")

    def load_plan(self, campaign_id: str) -> CampaignPlan | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM legacy_plans WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return None if row is None else _load(row["payload"])

    def save_plan(self, plan: CampaignPlan) -> None:
        validate_plan(plan)
        payload = _dump(plan)
        fingerprint = _plan_fingerprint(plan)
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO legacy_plans VALUES (?, ?, ?)",
                (plan.campaign_id, fingerprint, payload),
            )
            row = connection.execute(
                "SELECT fingerprint, payload FROM legacy_plans WHERE campaign_id = ?",
                (plan.campaign_id,),
            ).fetchone()
            if row is None or row["fingerprint"] != fingerprint or row["payload"] != payload:
                raise ValueError("campaign plan is immutable once persisted")

    def load_state(self, campaign_id: str) -> CampaignState | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM legacy_states WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return None if row is None else _load(row["payload"])

    def save_state(self, campaign_id: str, state: CampaignState) -> None:
        if state.campaign_id != campaign_id:
            raise ValueError("state campaign_id does not match the requested campaign")
        payload = _dump(state)
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO legacy_states VALUES (?, ?)
                   ON CONFLICT(campaign_id) DO UPDATE SET payload = excluded.payload""",
                (campaign_id, payload),
            )

    def save_simulation(self, campaign_id: str, result: SimulationResult) -> None:
        if not isinstance(result, SimulationResult):
            raise TypeError("result must be a SimulationResult")
        payload = _dump(result)
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO legacy_simulations VALUES (?, ?, ?)",
                (campaign_id, result.domain_id, payload),
            )
            row = connection.execute(
                """SELECT payload FROM legacy_simulations
                   WHERE campaign_id = ? AND domain_id = ?""",
                (campaign_id, result.domain_id),
            ).fetchone()
            if row is None or row["payload"] != payload:
                raise ValueError("domain_id conflicts with a different simulation result")

    def covered_bins(
        self, campaign_id: str, grid: CoverageGrid,
    ) -> frozenset[int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM legacy_simulations WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchall()
        covered: set[int] = set()
        for row in rows:
            covered.update(audit_simulation(_load(row["payload"]), grid).observed_bins)
        return frozenset(covered)

    def save_round(
        self, campaign_id: str, record: RoundRecord, state: CampaignState,
    ) -> None:
        if state.campaign_id != campaign_id:
            raise ValueError("state campaign_id does not match the requested campaign")
        record_payload = _dump(record)
        state_payload = _dump(state)
        with self._transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO legacy_rounds VALUES (?, ?, ?, ?, ?)""",
                (
                    campaign_id, record.lineage_start_signature_id,
                    record.round_index, record_payload, state_payload,
                ),
            )
            row = connection.execute(
                """SELECT record_payload, state_payload FROM legacy_rounds
                   WHERE campaign_id = ? AND lineage_start_signature_id = ?
                     AND round_index = ?""",
                (
                    campaign_id, record.lineage_start_signature_id,
                    record.round_index,
                ),
            ).fetchone()
            if (
                row is None
                or row["record_payload"] != record_payload
                or row["state_payload"] != state_payload
            ):
                raise ValueError("campaign round conflicts with an existing checkpoint")
            connection.execute(
                """INSERT INTO legacy_states VALUES (?, ?)
                   ON CONFLICT(campaign_id) DO UPDATE SET payload = excluded.payload""",
                (campaign_id, state_payload),
            )

    def load_revision(
        self, campaign_id: str, plan_revision: int,
    ) -> CampaignProject | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT payload FROM campaign_revisions
                   WHERE campaign_id = ? AND plan_revision = ?""",
                (campaign_id, plan_revision),
            ).fetchone()
        if row is None:
            return None
        project = _load(row["payload"])
        if not isinstance(project, CampaignProject):
            raise ValueError("stored campaign revision has an invalid record type")
        return project

    def latest_revision(self, campaign_id: str) -> CampaignProject | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT payload FROM campaign_revisions
                   WHERE campaign_id = ? ORDER BY plan_revision DESC LIMIT 1""",
                (campaign_id,),
            ).fetchone()
        if row is None:
            return None
        project = _load(row["payload"])
        if not isinstance(project, CampaignProject):
            raise ValueError("stored campaign revision has an invalid record type")
        return project

    def save_revision(
        self,
        project: CampaignProject,
        source_generation_id: str | None = None,
    ) -> None:
        validate_plan(project.plan)
        _validate_campaign_revision(project)
        campaign_id = project.plan.campaign_id
        fingerprint = _plan_fingerprint(project.plan)
        payload = _dump(project)
        with self._transaction() as connection:
            latest = connection.execute(
                """SELECT plan_revision, plan_fingerprint, payload FROM campaign_revisions
                   WHERE campaign_id = ? ORDER BY plan_revision DESC LIMIT 1""",
                (campaign_id,),
            ).fetchone()
            if latest is None:
                if project.parent_revision is None:
                    if source_generation_id is not None:
                        raise ValueError("a root revision must not name a source generation")
                else:
                    raise ValueError(
                        "the first stored campaign revision must be a root plan revision"
                    )
                connection.execute(
                    """INSERT INTO campaign_revisions VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        campaign_id, project.plan_revision, project.parent_revision,
                        project.parent_plan_fingerprint, fingerprint, payload,
                    ),
                )
                return

            latest_revision = int(latest["plan_revision"])
            if project.plan_revision == latest_revision:
                if latest["payload"] != payload or latest["plan_fingerprint"] != fingerprint:
                    raise ValueError("campaign plan revision is immutable")
                return
            if (
                project.plan_revision <= latest_revision
                or project.parent_revision != latest_revision
                or project.parent_plan_fingerprint != latest["plan_fingerprint"]
            ):
                raise ValueError("new campaign revision must extend its stored predecessor")
            if not source_generation_id:
                raise ValueError("campaign revision extension requires its source generation")

            previous = _load(latest["payload"])
            if not isinstance(previous, CampaignProject):
                raise ValueError("stored predecessor is not a campaign project")
            self._validate_revision_extension(
                connection, previous, project, source_generation_id,
            )
            connection.execute(
                """INSERT INTO campaign_revisions VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id, project.plan_revision, project.parent_revision,
                    project.parent_plan_fingerprint, fingerprint, payload,
                ),
            )

    @staticmethod
    def _validate_revision_extension(
        connection: sqlite3.Connection,
        previous: CampaignProject,
        project: CampaignProject,
        source_generation_id: str,
    ) -> None:
        old_plan, new_plan = previous.plan, project.plan
        if (
            previous.base_case != project.base_case
            or previous.category_catalog != project.category_catalog
            or previous.output_path_template != project.output_path_template
            or old_plan.grid != new_plan.grid
            or old_plan.bounds != new_plan.bounds
            or old_plan.exploration_seed != new_plan.exploration_seed
            or old_plan.verification_seeds != new_plan.verification_seeds
        ):
            raise ValueError("campaign revision changed immutable execution inputs")
        if old_plan.campaign_id != new_plan.campaign_id:
            raise ValueError("campaign_id must remain stable across revisions")

        row = connection.execute(
            """SELECT plan_revision FROM campaign_generations
               WHERE campaign_id = ? AND run_generation_id = ?""",
            (old_plan.campaign_id, source_generation_id),
        ).fetchone()
        if row is None or row["plan_revision"] != previous.plan_revision:
            raise ValueError("source generation is not at the predecessor revision")
        state_row = connection.execute(
            """SELECT payload FROM campaign_run_states
               WHERE campaign_id = ? AND run_generation_id = ? AND plan_revision = ?""",
            (old_plan.campaign_id, source_generation_id, previous.plan_revision),
        ).fetchone()
        if state_row is None:
            raise ValueError("source generation has no predecessor state")
        previous_state = _load(state_row["payload"])
        if not isinstance(previous_state, CampaignState):
            raise ValueError("source generation has an invalid state record")
        _validate_state(old_plan, previous_state)

        starts_unchanged = old_plan.start_signatures == new_plan.start_signatures
        starts_appended = (
            len(new_plan.start_signatures) > len(old_plan.start_signatures)
            and new_plan.start_signatures[:len(old_plan.start_signatures)]
            == old_plan.start_signatures
        )
        budget_increased = (
            previous.round_budget is not None
            and project.round_budget is not None
            and project.round_budget > previous.round_budget
        )
        update_rule_changed = old_plan.update_rule_id != new_plan.update_rule_id
        if (
            update_rule_changed
            and starts_unchanged
            and project.round_budget == previous.round_budget
        ):
            return
        if starts_appended and project.round_budget == previous.round_budget:
            if previous_state.status != "all_lineages_saturated":
                raise ValueError("signature extension requires all lineages saturated")
            return
        if starts_unchanged and budget_increased:
            if previous_state.status != "round_budget_exhausted":
                raise ValueError("round-budget extension requires an exhausted budget")
            return
        raise ValueError(
            "revision must change the update rule, append starts after saturation, "
            "or increase an exhausted round budget"
        )

    def latest_generation(
        self, campaign_id: str, plan_revision: int,
    ) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT run_generation_id FROM campaign_generations
                   WHERE campaign_id = ? AND plan_revision = ?
                   ORDER BY created_order DESC LIMIT 1""",
                (campaign_id, plan_revision),
            ).fetchone()
        return None if row is None else row["run_generation_id"]

    def campaign_generation_ids(self, campaign_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT run_generation_id FROM campaign_generations
                   WHERE campaign_id = ? ORDER BY created_order""",
                (campaign_id,),
            ).fetchall()
        return tuple(row["run_generation_id"] for row in rows)

    def generation_exists(self, campaign_id: str, run_generation_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT 1 FROM campaign_generations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
        return row is not None

    def generation_fingerprint(
        self, campaign_id: str, run_generation_id: str,
    ) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT simulation_fingerprint FROM campaign_generations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
        return None if row is None else row["simulation_fingerprint"]

    def load_generation_state(
        self, campaign_id: str, run_generation_id: str, plan_revision: int,
    ) -> CampaignState | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT payload FROM campaign_run_states
                   WHERE campaign_id = ? AND run_generation_id = ? AND plan_revision = ?""",
                (campaign_id, run_generation_id, plan_revision),
            ).fetchone()
        return None if row is None else _load(row["payload"])

    def create_generation(
        self,
        campaign_id: str,
        run_generation_id: str,
        plan_revision: int,
        simulation_fingerprint: str,
        state: CampaignState,
    ) -> None:
        if (
            not run_generation_id.strip()
            or not simulation_fingerprint.strip()
            or state.campaign_id != campaign_id
        ):
            raise ValueError("generation ID, fingerprint, and campaign state must be valid")
        state_payload = _dump(state)
        with self._transaction() as connection:
            revision = connection.execute(
                """SELECT plan_fingerprint, payload FROM campaign_revisions
                   WHERE campaign_id = ? AND plan_revision = ?""",
                (campaign_id, plan_revision),
            ).fetchone()
            if revision is None or state.plan_fingerprint != revision["plan_fingerprint"]:
                raise ValueError("generation state does not match a stored plan revision")
            project = _load(revision["payload"])
            if not isinstance(project, CampaignProject):
                raise ValueError("stored campaign revision has an invalid record type")
            _validate_state(project.plan, state)
            generation = connection.execute(
                """SELECT plan_revision, simulation_fingerprint FROM campaign_generations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
            if generation is None:
                connection.execute(
                    """INSERT INTO campaign_generations
                       (campaign_id, run_generation_id, plan_revision, simulation_fingerprint)
                       VALUES (?, ?, ?, ?)""",
                    (
                        campaign_id, run_generation_id, plan_revision,
                        simulation_fingerprint,
                    ),
                )
            elif generation["plan_revision"] != plan_revision:
                if generation["simulation_fingerprint"] != simulation_fingerprint:
                    raise ValueError("execution fingerprint changed within a run generation")
                if generation["plan_revision"] + 1 != plan_revision:
                    raise ValueError("generation cannot skip a plan revision")
                old_state = connection.execute(
                    """SELECT payload FROM campaign_run_states
                       WHERE campaign_id = ? AND run_generation_id = ?
                         AND plan_revision = ?""",
                    (campaign_id, run_generation_id, generation["plan_revision"]),
                ).fetchone()
                if old_state is None:
                    raise ValueError("generation is missing its predecessor state")
                connection.execute(
                    """UPDATE campaign_generations SET plan_revision = ?
                       WHERE campaign_id = ? AND run_generation_id = ?""",
                    (plan_revision, campaign_id, run_generation_id),
                )
            elif generation["simulation_fingerprint"] != simulation_fingerprint:
                raise ValueError("execution fingerprint changed within a run generation")
            existing = connection.execute(
                """SELECT payload FROM campaign_run_states
                   WHERE campaign_id = ? AND run_generation_id = ? AND plan_revision = ?""",
                (campaign_id, run_generation_id, plan_revision),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO campaign_run_states VALUES (?, ?, ?, ?)""",
                    (campaign_id, run_generation_id, plan_revision, state_payload),
                )
            elif existing["payload"] != state_payload:
                raise ValueError("run generation already has a different initial state")

    def save_generation_state(
        self,
        campaign_id: str,
        run_generation_id: str,
        plan_revision: int,
        state: CampaignState,
    ) -> None:
        if state.campaign_id != campaign_id:
            raise ValueError("state campaign_id does not match the requested campaign")
        payload = _dump(state)
        with self._transaction() as connection:
            generation = connection.execute(
                """SELECT plan_revision FROM campaign_generations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
            if generation is None or generation["plan_revision"] != plan_revision:
                raise ValueError("run generation is not at the requested plan revision")
            revision = connection.execute(
                """SELECT plan_fingerprint, payload FROM campaign_revisions
                   WHERE campaign_id = ? AND plan_revision = ?""",
                (campaign_id, plan_revision),
            ).fetchone()
            if revision is None or state.plan_fingerprint != revision["plan_fingerprint"]:
                raise ValueError("state does not match the stored plan revision")
            project = _load(revision["payload"])
            if not isinstance(project, CampaignProject):
                raise ValueError("stored campaign revision has an invalid record type")
            _validate_state(project.plan, state)
            connection.execute(
                """INSERT INTO campaign_run_states VALUES (?, ?, ?, ?)
                   ON CONFLICT(campaign_id, run_generation_id, plan_revision)
                   DO UPDATE SET payload = excluded.payload""",
                (campaign_id, run_generation_id, plan_revision, payload),
            )

    def load_generation_simulation(
        self,
        campaign_id: str,
        run_generation_id: str,
        simulation_fingerprint: str,
        signature_id: str,
        seed: int,
    ) -> SimulationResult | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT payload FROM campaign_simulations
                   WHERE campaign_id = ? AND run_generation_id = ?
                     AND simulation_fingerprint = ? AND signature_id = ? AND seed = ?""",
                (
                    campaign_id, run_generation_id, simulation_fingerprint,
                    signature_id, seed,
                ),
            ).fetchone()
        return None if row is None else _load(row["payload"])

    def save_generation_simulation(
        self,
        campaign_id: str,
        run_generation_id: str,
        simulation_fingerprint: str,
        plan_revision: int,
        result: SimulationResult,
    ) -> None:
        if not isinstance(result, SimulationResult):
            raise TypeError("result must be a SimulationResult")
        payload = _dump(result)
        with self._transaction() as connection:
            generation = connection.execute(
                """SELECT plan_revision FROM campaign_generations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
            if generation is None or generation["plan_revision"] != plan_revision:
                raise ValueError("simulation source revision is not active in this generation")
            revision = connection.execute(
                """SELECT payload FROM campaign_revisions
                   WHERE campaign_id = ? AND plan_revision = ?""",
                (campaign_id, plan_revision),
            ).fetchone()
            if revision is None:
                raise ValueError("simulation source revision is not stored")
            project = _load(revision["payload"])
            if not isinstance(project, CampaignProject):
                raise ValueError("stored campaign revision has an invalid record type")
            audit_simulation(result, project.plan.grid)
            connection.execute(
                """INSERT OR IGNORE INTO campaign_simulations
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id, run_generation_id, simulation_fingerprint,
                    result.signature_id, result.seed, result.domain_id,
                    plan_revision, payload,
                ),
            )
            row = connection.execute(
                """SELECT payload, domain_id FROM campaign_simulations
                   WHERE campaign_id = ? AND run_generation_id = ?
                     AND simulation_fingerprint = ? AND signature_id = ? AND seed = ?""",
                (
                    campaign_id, run_generation_id, simulation_fingerprint,
                    result.signature_id, result.seed,
                ),
            ).fetchone()
            if row is None or row["payload"] != payload or row["domain_id"] != result.domain_id:
                raise ValueError("simulation fingerprint key conflicts with stored evidence")

    def generation_covered_bins(
        self, campaign_id: str, run_generation_id: str, grid: CoverageGrid,
    ) -> frozenset[int]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT payload FROM campaign_simulations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchall()
        covered: set[int] = set()
        seen_domains: set[str] = set()
        for row in rows:
            result = _load(row["payload"])
            if result.domain_id in seen_domains:
                continue
            seen_domains.add(result.domain_id)
            covered.update(audit_simulation(result, grid).observed_bins)
        return frozenset(covered)

    def generation_round_count(
        self, campaign_id: str, run_generation_id: str,
    ) -> int:
        with self._lock:
            row = self._connection.execute(
                """SELECT COUNT(*) AS count FROM campaign_rounds
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
        return int(row["count"])

    def save_generation_round(
        self,
        campaign_id: str,
        run_generation_id: str,
        plan_revision: int,
        record: RoundRecord,
        state: CampaignState,
    ) -> None:
        if state.campaign_id != campaign_id:
            raise ValueError("state campaign_id does not match the requested campaign")
        record_payload, state_payload = _dump(record), _dump(state)
        with self._transaction() as connection:
            generation = connection.execute(
                """SELECT plan_revision FROM campaign_generations
                   WHERE campaign_id = ? AND run_generation_id = ?""",
                (campaign_id, run_generation_id),
            ).fetchone()
            if generation is None or generation["plan_revision"] != plan_revision:
                raise ValueError("round source revision is not active in this generation")
            revision = connection.execute(
                """SELECT plan_fingerprint, payload FROM campaign_revisions
                   WHERE campaign_id = ? AND plan_revision = ?""",
                (campaign_id, plan_revision),
            ).fetchone()
            if revision is None or state.plan_fingerprint != revision["plan_fingerprint"]:
                raise ValueError("round state does not match the stored plan revision")
            project = _load(revision["payload"])
            if not isinstance(project, CampaignProject):
                raise ValueError("stored campaign revision has an invalid record type")
            _validate_state(project.plan, state)
            connection.execute(
                """INSERT OR IGNORE INTO campaign_rounds VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id, run_generation_id, plan_revision,
                    record.lineage_start_signature_id, record.round_index,
                    record_payload, state_payload,
                ),
            )
            existing = connection.execute(
                """SELECT record_payload, state_payload FROM campaign_rounds
                   WHERE campaign_id = ? AND run_generation_id = ? AND plan_revision = ?
                     AND lineage_start_signature_id = ? AND round_index = ?""",
                (
                    campaign_id, run_generation_id, plan_revision,
                    record.lineage_start_signature_id, record.round_index,
                ),
            ).fetchone()
            if (
                existing is None
                or existing["record_payload"] != record_payload
                or existing["state_payload"] != state_payload
            ):
                raise ValueError("round checkpoint conflicts with immutable stored evidence")
            connection.execute(
                """INSERT INTO campaign_run_states VALUES (?, ?, ?, ?)
                   ON CONFLICT(campaign_id, run_generation_id, plan_revision)
                   DO UPDATE SET payload = excluded.payload""",
                (campaign_id, run_generation_id, plan_revision, state_payload),
            )
