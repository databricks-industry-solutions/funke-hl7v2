"""Live medallion-flow metrics for the Data Flow tab.

Backs ``GET /api/flow`` (per-stage row count / freshness / throughput) and
``GET /api/flow/sample`` (one real message traced raw -> parsed -> gold). Both read the demo's
Delta tables through the SQL warehouse using the same Statement Execution pattern as
``generator.GeneratorController._rehydrate`` — the app container has no Spark.

Each method keeps a last-good result so a cold or transient warehouse never blanks the UI: on
any error the previous value is returned with ``stale=True``. When no warehouse is bound
(``DATABRICKS_WAREHOUSE_ID`` unset, e.g. local dev) the methods report ``available=False`` and
never call out.
"""

import logging
import os
from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient

from generator import parse_event

log = logging.getLogger("adt.flow")

# HL7 addresses for the parsed-field view, mapped to the keys parse_event returns. Ordered the
# way the message reads top to bottom.
_PARSED_FIELDS = [
    ("MSH-9.2", "Trigger", "trigger"),
    ("MSH-3", "Source EMR", "source"),
    ("PID-5", "Patient", "patient_name"),
    ("PV1-2", "Patient class", "patient_class"),
    ("PV1-3.4", "Facility", "facility"),
    ("PV1-3.1", "Unit", "unit"),
    ("PV1-3.2", "Room", "room"),
    ("PV1-19", "Visit number", "visit_number"),
]

# Gold columns surfaced in the trace panel, in display order.
_GOLD_FIELDS = [
    "event_type",
    "source_system",
    "event_ts",
    "facility_code",
    "unit",
    "room",
    "bed",
    "patient_class",
    "visit_number",
    "patient_first_name",
    "patient_last_name",
    "patient_sex",
]


class FlowController:
    """Query per-stage flow metrics and a sample message trace via the SQL warehouse."""

    def __init__(self):
        volume_path = os.environ.get(
            "LANDING_VOLUME_PATH", "/Volumes/main/hl7/landing"
        ).rstrip("/")
        parts = volume_path.split("/")  # ['', 'Volumes', catalog, schema, volume]
        self._catalog = parts[2] if len(parts) > 2 else "main"
        self._schema = parts[3] if len(parts) > 3 else "hl7"
        self._warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

        self._w = WorkspaceClient()
        self._last_metrics: dict | None = None
        self._last_sample: dict | None = None

    def _table(self, name: str) -> str:
        return f"{self._catalog}.{self._schema}.{name}"

    def _execute(self, statement: str):
        """Run a single statement and return ``(columns, rows)``; rows are lists of str|None."""
        resp = self._w.statement_execution.execute_statement(
            warehouse_id=self._warehouse_id,
            statement=statement,
            wait_timeout="30s",
        )
        if not (resp.manifest and resp.result and resp.result.data_array):
            return (
                [c.name for c in resp.manifest.schema.columns] if resp.manifest else []
            ), []
        cols = [c.name for c in resp.manifest.schema.columns]
        return cols, resp.result.data_array

    # --- per-stage metrics -----------------------------------------------------------------

    def metrics(self) -> dict:
        """Return count / freshness / throughput for bronze, silver, gold in one round-trip."""
        if not self._warehouse_id:
            return {"available": False, "stages": {}}
        stage_tables = [
            ("bronze", self._table("raw_messages")),
            ("silver", self._table("parsed_messages")),
            ("gold", self._table("adt_events")),
        ]
        statement = "\nUNION ALL\n".join(
            f"""SELECT '{stage}' AS stage, COUNT(*) AS total,
                       date_diff(SECOND, MAX(inserted), now()) AS age_s,
                       COUNT_IF(inserted > now() - INTERVAL 1 MINUTE) AS per_min
                FROM {table}""" for stage, table in stage_tables
        )
        try:
            cols, rows = self._execute(statement)
            stages = {}
            for row in rows:
                d = dict(zip(cols, row))
                stages[d["stage"]] = {
                    "count": int(d["total"]) if d["total"] is not None else 0,
                    "age_seconds": int(d["age_s"]) if d["age_s"] is not None else None,
                    "per_min": int(d["per_min"]) if d["per_min"] is not None else 0,
                }
            result = {
                "available": True,
                "stale": False,
                "generated_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "stages": stages,
            }
            self._last_metrics = result
            return result
        except Exception:
            log.exception("flow metrics query failed")
            if self._last_metrics:
                return {**self._last_metrics, "stale": True}
            return {"available": False, "stages": {}}

    # --- sample message trace --------------------------------------------------------------

    def sample(self) -> dict:
        """Return the newest message that reached gold, traced raw -> parsed -> gold."""
        if not self._warehouse_id:
            return {"available": False}
        gold_cols = ", ".join(f"g.{c}" for c in _GOLD_FIELDS)
        statement = f"""
            SELECT r.content AS raw_hl7, {gold_cols}
            FROM {self._table('adt_events')} g
            JOIN {self._table('raw_messages')} r ON r.messageId = g.messageId
            ORDER BY g.inserted DESC
            LIMIT 1
        """
        try:
            cols, rows = self._execute(statement)
            if not rows:
                return {"available": True, "empty": True}
            d = dict(zip(cols, rows[0]))
            raw = d.get("raw_hl7") or ""
            fields = parse_event(raw)
            parsed = [
                {"address": addr, "label": label, "value": fields.get(key, "")}
                for addr, label, key in _PARSED_FIELDS
            ]
            gold = {c: d.get(c) for c in _GOLD_FIELDS}
            result = {
                "available": True,
                "stale": False,
                "raw": raw,
                "parsed": parsed,
                "gold": gold,
            }
            self._last_sample = result
            return result
        except Exception:
            log.exception("flow sample query failed")
            if self._last_sample:
                return {**self._last_sample, "stale": True}
            return {"available": False}
