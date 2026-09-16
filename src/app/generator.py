"""In-process synthetic ADT generator that backs the control-room app.

Runs the pure-Python :class:`funke.demo.adt.Hospital` engine in a background thread, writing one
HL7v2 file per event into the landing volume via the Databricks **Files API** (an app container
has no FUSE volume mount and no Spark). The realtime loop mirrors the standalone job generator
(``resources/demo/adt_generator.py``) — diurnal/weekly shaped pacing capped at 120 s between
messages — but here it is driven by Start/Stop from the UI and exposes live counters, per-unit
occupancy (read straight from the engine's in-memory state, so it never waits on the pipeline),
and a rolling event feed.

On a cold start (empty ``current_census``) it seeds a shaped week of backdated history in a
"seeding" phase, parallelizing the Files-API uploads. A restart with a populated census instead
rehydrates open visits via the SQL warehouse so occupancy resumes instead of leaving phantom beds.
"""

import io
import logging
import os
import random
import threading
import time
import uuid
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from databricks.sdk import WorkspaceClient

from funke.demo.adt import Hospital
from funke.demo.emr import EMRS
from funke.demo.facilities import FACILITIES
from funke.demo.volume import build_backfill_timestamps, volume_multiplier_noisy

log = logging.getLogger("adt.generator")

# Cap the realtime inter-message sleep so overnight troughs never stall the live demo.
_MAX_SLEEP_SECONDS = 120.0
# Trailing window used to report the live message rate.
_RATE_WINDOW_SECONDS = 120.0
# Parallel Files-API uploads for the cold-start backfill (I/O bound).
_BACKFILL_WORKERS = 32


def parse_event(message: str) -> dict:
    """Pull the display fields out of a rendered ADT message.

    The layout is fixed by :func:`funke.demo.adt.build_adt_message`, so a positional split is
    enough — and defensive (missing fields degrade to empty strings) so a feed row never crashes
    the loop.

    Returns:
        Dict with ``trigger``, ``source`` (MSH-3 EMR code), ``facility``, ``unit``, ``room``,
        ``patient_class``, ``visit_number`` and ``patient_name``.
    """
    seg = {line.split("|", 1)[0]: line.split("|") for line in message.splitlines()}

    def field(name: str, idx: int) -> str:
        parts = seg.get(name, [])
        return parts[idx] if len(parts) > idx else ""

    trigger = ""
    msh9 = field("MSH", 8)  # "ADT^A01^ADT_A01"
    if msh9:
        comps = msh9.split("^")
        trigger = comps[1] if len(comps) > 1 else ""

    location = field("PV1", 3).split("^")  # unit^room^bed^facility
    name = field("PID", 5).split("^")  # last^first
    return {
        "trigger": trigger,
        "source": field("MSH", 2),  # MSH-3 sending application = source EMR code
        "facility": location[3] if len(location) > 3 else "",
        "unit": location[0] if len(location) > 0 else "",
        "room": location[1] if len(location) > 1 else "",
        "patient_class": field("PV1", 2),
        "visit_number": field("PV1", 19),
        "patient_name": " ".join(reversed([p for p in name[:2] if p])),
    }


class GeneratorController:
    """Owns the Hospital engine and the background generation thread.

    Thread-safety: all reads/writes of the engine and counters happen under ``self._lock`` so
    the API handlers (status/census) get a consistent snapshot while the loop mutates state.
    """

    def __init__(self):
        volume_path = os.environ.get(
            "LANDING_VOLUME_PATH", "/Volumes/main/hl7/landing"
        ).rstrip("/")
        parts = volume_path.split("/")  # ['', 'Volumes', catalog, schema, volume]
        self._landing_dir = volume_path
        self._catalog = parts[2] if len(parts) > 2 else "main"
        self._schema = parts[3] if len(parts) > 3 else "hl7"
        self._warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

        self._w = WorkspaceClient()
        self.dashboard_url = self._resolve_dashboard_url()
        self._hospital = Hospital()
        self._rng = random.Random()

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

        self._status = "stopped"
        self._seeded = False  # true once this process has backfilled/rehydrated
        self._started_at: float | None = None
        self._messages_written = 0
        self._events_by_type: Counter = Counter()
        self._events_by_source: Counter = Counter()
        self._recent: deque = deque(maxlen=50)
        self._rate_times: deque = deque()
        self._backfill_total = 0
        self._backfill_done = 0

        # Tunables surfaced to the UI.
        self.peak_rate_per_hour = 400.0
        self.backfill_hours = 168.0
        self.backfill_peak_rate_per_hour = 400.0
        # Per-EMR admit mix (the control-room mixer). Equal by default; pushed to the engine.
        self.emr_weights: dict[str, float] = {e.code: 1.0 for e in EMRS}
        self._hospital.set_source_weights(self.emr_weights)

    _DASHBOARD_NAME = "Hospital Bed Utilization"

    def _resolve_dashboard_url(self) -> str:
        """Return the embeddable URL for the bed-utilization AI/BI dashboard.

        Honors a ``DASHBOARD_URL`` env override (handy for local dev); otherwise looks the
        dashboard up by display name via the Lakeview API and returns its ``/embed`` URL so it
        renders inside the app's Dashboard tab (an ``iframe``). Matches on substring so the dev
        ``[dev <user>] `` prefix still resolves. Returns "" if it can't be found — the tab then
        shows a fallback hint instead of a broken frame.
        """
        override = os.environ.get("DASHBOARD_URL", "")
        if override:
            return override
        try:
            host = self._w.config.host.rstrip("/")
            for d in self._w.lakeview.list():
                if d.display_name and self._DASHBOARD_NAME in d.display_name:
                    return f"{host}/embed/dashboardsv3/{d.dashboard_id}"
        except Exception:
            logging.exception("could not resolve dashboard url")
        return ""

    # --- lifecycle ---------------------------------------------------------------------

    def start(self) -> dict:
        with self._lock:
            if self._status in ("running", "seeding"):
                return self._status_locked()
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, daemon=True)
            self._worker.start()
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        self._set_status("stopped")
        return self.status()

    def _run(self) -> None:
        """Background entry: seed on cold start, then run the realtime loop until stopped."""
        try:
            if not self._seeded:
                if self._rehydrate() == 0:
                    self._set_status("seeding")
                    self._run_backfill()
                self._seeded = True
            self._started_at = time.time()
            self._set_status("running")
            self._run_realtime()
        except (
            Exception
        ):  # keep the app alive; surface via status flipping back to stopped
            log.exception("generator run failed")
        finally:
            if not self._stop.is_set():
                self._set_status("stopped")

    # --- generation --------------------------------------------------------------------

    def _upload(self, message: str) -> None:
        path = f"{self._landing_dir}/{uuid.uuid4()}.hl7"
        self._w.files.upload(path, io.BytesIO(message.encode("utf-8")), overwrite=True)

    def _generate(self, now: datetime) -> str:
        with self._lock:
            return self._hospital.generate_event(now)

    def _run_backfill(self) -> None:
        """Seed a shaped week of backdated history, uploading files in parallel."""
        start = datetime.now() - timedelta(hours=self.backfill_hours)
        timestamps = build_backfill_timestamps(
            self.backfill_hours, self.backfill_peak_rate_per_hour, self._rng, start
        )
        # Generate strictly in time order (shared engine state); upload is what we parallelize.
        messages = [self._generate(ts) for ts in timestamps]
        with self._lock:
            self._backfill_total = len(messages)
            self._backfill_done = 0
            for msg in messages:
                event = parse_event(msg)
                self._events_by_type[event["trigger"]] += 1
                self._events_by_source[event["source"]] += 1
        with ThreadPoolExecutor(max_workers=_BACKFILL_WORKERS) as pool:
            for _ in pool.map(self._upload, messages):
                with self._lock:
                    self._messages_written += 1
                    self._backfill_done += 1
        log.info("seeded %d backfill messages to %s", len(messages), self._landing_dir)

    def _run_realtime(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            message = self._generate(now)
            self._upload(message)
            self._record(message)
            sleep_s = min(
                (3600.0 / self.peak_rate_per_hour)
                / volume_multiplier_noisy(now, self._rng),
                _MAX_SLEEP_SECONDS,
            )
            self._stop.wait(sleep_s)  # interruptible sleep

    def _record(self, message: str) -> None:
        event = parse_event(message)
        now = time.time()
        with self._lock:
            self._messages_written += 1
            self._events_by_type[event["trigger"]] += 1
            self._events_by_source[event["source"]] += 1
            self._recent.appendleft(
                {**event, "ts": datetime.now().isoformat(timespec="seconds")}
            )
            self._rate_times.append(now)
            cutoff = now - _RATE_WINDOW_SECONDS
            while self._rate_times and self._rate_times[0] < cutoff:
                self._rate_times.popleft()

    # --- census / rehydrate ------------------------------------------------------------

    def _rehydrate(self) -> int:
        """Seed the engine from current_census so a restart resumes real occupancy.

        Best-effort: a missing table (genuine cold start) or any warehouse error is treated as
        an empty census (returns 0), which triggers the backfill path.
        """
        if not self._warehouse_id:
            return 0
        table = f"{self._catalog}.{self._schema}.current_census"
        try:
            resp = self._w.statement_execution.execute_statement(
                warehouse_id=self._warehouse_id,
                statement=f"SELECT * FROM {table}",
                wait_timeout="30s",
            )
            if not (resp.result and resp.result.data_array and resp.manifest):
                return 0
            cols = [c.name for c in resp.manifest.schema.columns]
            rows = [dict(zip(cols, row)) for row in resp.result.data_array]
        except (
            Exception
        ) as exc:  # table missing on cold start, or transient warehouse error
            log.info("rehydrate skipped (%s); treating as cold start", exc)
            return 0
        with self._lock:
            seeded = self._hospital.seed_open_visits(rows)
        log.info("rehydrated %d open visits from %s", seeded, table)
        return seeded

    def census(self) -> dict:
        with self._lock:
            counts = Counter(
                (v.facility_code, v.unit) for v in self._hospital.visits.values()
            )
            total_occupied = len(self._hospital.visits)
        total_capacity = self._hospital.total_capacity()
        facilities = []
        for facility in FACILITIES:
            units = []
            f_occ = f_cap = 0
            for unit in facility.units:
                occ = counts.get((facility.code, unit.name), 0)
                units.append(
                    {
                        "unit": unit.name,
                        "occupied": occ,
                        "capacity": unit.bed_capacity,
                        "utilization": _pct(occ, unit.bed_capacity),
                    }
                )
                f_occ += occ
                f_cap += unit.bed_capacity
            facilities.append(
                {
                    "code": facility.code,
                    "name": facility.name,
                    "kind": facility.kind,
                    "occupied": f_occ,
                    "capacity": f_cap,
                    "utilization": _pct(f_occ, f_cap),
                    "units": units,
                }
            )
        return {
            "total_occupied": total_occupied,
            "total_capacity": total_capacity,
            "utilization": _pct(total_occupied, total_capacity),
            "facilities": facilities,
        }

    # --- status / config ---------------------------------------------------------------

    def _set_status(self, status: str) -> None:
        with self._lock:
            self._status = status

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict:
        rate = len(self._rate_times) / _RATE_WINDOW_SECONDS * 3600.0
        uptime = time.time() - self._started_at if self._started_at else 0.0
        return {
            "status": self._status,
            "messages_written": self._messages_written,
            "events_by_type": dict(self._events_by_type),
            "events_by_source": dict(self._events_by_source),
            "rate_per_hour": round(rate),
            "uptime_seconds": round(uptime),
            "recent": list(self._recent),
            "seeding": {"done": self._backfill_done, "total": self._backfill_total},
            "config": self.get_config(),
            "emrs": [{"code": e.code, "display_name": e.display_name} for e in EMRS],
            "dashboard_url": self.dashboard_url,
        }

    def get_config(self) -> dict:
        return {
            "peak_rate_per_hour": self.peak_rate_per_hour,
            "backfill_hours": self.backfill_hours,
            "emr_weights": dict(self.emr_weights),
        }

    def set_config(
        self,
        peak_rate_per_hour: float | None = None,
        emr_weights: dict[str, float] | None = None,
    ) -> dict:
        if peak_rate_per_hour is not None:
            self.peak_rate_per_hour = max(1.0, float(peak_rate_per_hour))
        if emr_weights is not None:
            # Keep only known EMR codes; push the new admit mix to the engine.
            self.emr_weights = {
                e.code: max(
                    0.0, float(emr_weights.get(e.code, self.emr_weights[e.code]))
                )
                for e in EMRS
            }
            self._hospital.set_source_weights(self.emr_weights)
        return self.get_config()


def _pct(occupied: int, capacity: int) -> float:
    return round(100.0 * occupied / capacity, 1) if capacity else 0.0
