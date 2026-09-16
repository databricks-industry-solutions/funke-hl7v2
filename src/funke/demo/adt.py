"""
Synthetic HL7v2 ADT message generation for the bed-utilization demo.

This module *constructs* real ADT messages (not canned replays) modeled on the
``ADT_A01`` sample, and drives them from a stateful :class:`Hospital` engine that maintains
currently-admitted visits and respects per-unit bed capacity from :mod:`funke.demo.facilities`.

Supported trigger events:
    A01  Admit inpatient/emergency
    A02  Transfer (move an open visit to another unit in the same facility)
    A03  Discharge (frees the bed)
    A04  Register outpatient

Every generated visit carries a stable ``visit_number`` (PV1-19) so the downstream gold layer
can sequence events per encounter and treat A03 as the end of an occupancy.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from funke.demo.emr import DEFAULT_EMR, EMRS, EmrProfile, emr_by_code
from funke.demo.facilities import FACILITIES, Facility, Unit
from funke.demo.volume import admit_discharge_bias

FIELD_SEP = "|"
COMPONENT_SEP = "^"
ENCODING = "^~\\&"
HL7_VERSION = "2.8"
DTM_FORMAT = "%Y%m%d%H%M%S"

# How strongly the time-of-day tilt shifts the admit/discharge weights (see generate_event).
_BIAS_STRENGTH = 0.25


@dataclass(frozen=True)
class _Pin:
    """A unit held inside a fixed occupancy band, expressed as bed counts.

    Attributes:
        facility: Facility code of the pinned unit.
        unit: Unit name of the pinned unit.
        low: Minimum occupied beds the engine tops the unit up to.
        high: Maximum occupied beds the engine lets the unit hold.
    """

    facility: str
    unit: str
    low: int
    high: int


# Units pinned near capacity so the demo dashboard's "facilities near capacity" panel always
# tells a dramatic story: both ICUs run fully CRITICAL (>=95% occupied) while an ED and a
# med-surg floor sit in the WARNING band (85-95%). The normal admit/discharge/transfer flow
# leaves these units alone; the engine only tops them up to `low` and caps them at `high`.
# Bands are bed counts sized to the capacities in facilities.py:
#   MGEN/ICU=20     -> 20/20 = 100%      CRITICAL
#   LAKE/ICU=12     -> 12/12 = 100%      CRITICAL
#   MGEN/ED=30      -> 27/30..28/30 = 90-93%   WARNING
#   LAKE/MEDSURG=60 -> 54/60..56/60 = 90-93%   WARNING
_PINNED_UNITS: tuple[_Pin, ...] = (
    _Pin("MGEN", "ICU", low=20, high=20),
    _Pin("LAKE", "ICU", low=12, high=12),
    _Pin("MGEN", "ED", low=27, high=28),
    _Pin("LAKE", "MEDSURG", low=54, high=56),
)
_PINNED_SET = frozenset((p.facility, p.unit) for p in _PINNED_UNITS)

_FIRST_NAMES = [
    "James",
    "Mary",
    "Robert",
    "Patricia",
    "John",
    "Jennifer",
    "Michael",
    "Linda",
    "David",
    "Elizabeth",
    "William",
    "Barbara",
    "Richard",
    "Susan",
    "Joseph",
    "Jessica",
    "Thomas",
    "Sarah",
    "Carlos",
    "Maria",
    "Wei",
    "Mei",
    "Amir",
    "Fatima",
    "Kwame",
    "Aisha",
]
_LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Nguyen",
    "Kim",
    "Patel",
    "Okafor",
    "Ali",
    "Chen",
    "Singh",
    "Cohen",
    "Rossi",
]


@dataclass
class Visit:
    """A single patient encounter occupying one bed.

    Attributes:
        visit_number: Stable encounter id (PV1-19).
        patient_id: Medical record number (PID-3).
        first_name, last_name, sex, dob: Demographics (PID-5/8/7).
        facility_code, unit, room, bed: Assigned location (PV1-3 components).
        patient_class: HL7 PV1-2 class (``I``/``E``/``O``).
        admit_ts: Admission timestamp (PV1-44).
        bed_slot: Internal 1-based bed slot used to reserve/release capacity.
        source_system: EMR code (MSH-3) that owns this encounter; assigned at admit and reused
            for the visit's transfer/discharge so the source stays consistent.
    """

    visit_number: str
    patient_id: str
    first_name: str
    last_name: str
    sex: str
    dob: str
    facility_code: str
    unit: str
    room: str
    bed: str
    patient_class: str
    admit_ts: datetime
    bed_slot: int
    source_system: str = ""


def _segment(name: str, fields: dict[int, str]) -> str:
    """Build a non-MSH segment line from a {field_number: value} mapping."""
    max_field = max(fields) if fields else 0
    parts = [fields.get(i, "") for i in range(1, max_field + 1)]
    return name + FIELD_SEP + FIELD_SEP.join(parts)


def _msh_segment(fields: dict[int, str]) -> str:
    """Build the MSH line. MSH-1 is the field separator, MSH-2 the encoding chars."""
    max_field = max(fields)
    parts = [fields.get(i, "") for i in range(3, max_field + 1)]
    return "MSH" + FIELD_SEP + ENCODING + FIELD_SEP + FIELD_SEP.join(parts)


def _fmt(ts: datetime) -> str:
    return ts.strftime(DTM_FORMAT)


def build_adt_message(
    trigger: str,
    visit: Visit,
    event_ts: datetime,
    control_id: str,
    discharge_ts: datetime | None = None,
    emr: EmrProfile = DEFAULT_EMR,
) -> str:
    """Render an ADT message string for the given trigger event and visit.

    Args:
        trigger: ADT trigger event code (``A01``/``A02``/``A03``/``A04``).
        visit: The visit whose state the message reports.
        event_ts: Message/event timestamp (MSH-7, EVN-2).
        control_id: Unique message control id (MSH-10).
        discharge_ts: Discharge timestamp (PV1-45); set only for A03.
        emr: The source EMR profile — sets MSH-3/5/6/12, the PID-5 name style, and any
            proprietary Z-segments, so different EMRs render visibly different messages.

    Returns:
        The full HL7v2 message as a newline-delimited string.
    """
    structure = f"ADT_{trigger}"
    msh = _msh_segment(
        {
            3: emr.code,
            4: visit.facility_code,
            5: emr.receiving_app,
            6: emr.receiving_facility,
            7: _fmt(event_ts),
            9: f"ADT{COMPONENT_SEP}{trigger}{COMPONENT_SEP}{structure}",
            10: control_id,
            11: "P",
            12: emr.hl7_version,
        }
    )
    evn = _segment(
        "EVN",
        {1: trigger, 2: _fmt(event_ts), 6: _fmt(event_ts), 7: visit.facility_code},
    )
    pid = _segment(
        "PID",
        {
            1: "1",
            3: f"{visit.patient_id}^^^FUNKE^MR",
            5: emr.render_name(visit),
            7: visit.dob,
            8: visit.sex,
        },
    )
    location = COMPONENT_SEP.join(
        [visit.unit, visit.room, visit.bed, visit.facility_code]
    )
    pv1_fields = {
        1: "1",
        2: visit.patient_class,
        3: location,
        19: visit.visit_number,
        44: _fmt(visit.admit_ts),
    }
    if discharge_ts is not None:
        pv1_fields[45] = _fmt(discharge_ts)
    pv1 = _segment("PV1", pv1_fields)

    return "\n".join([msh, evn, pid, pv1] + emr.z_segments(visit, event_ts))


class Hospital:
    """Stateful ADT event source across the facility network.

    Holds the set of currently-admitted visits and free/occupied bed slots per unit, and
    emits one coherent ADT message per :meth:`generate_event` call — biasing toward admits
    when beds are empty and discharges when the network is full so occupancy stays realistic.
    """

    def __init__(self, seed: int | None = None, run_id: str | None = None):
        """Initialize an empty hospital network.

        Args:
            seed: Optional RNG seed for reproducible sequences (used in tests).
            run_id: Short prefix for visit/patient ids to keep them unique across generator
                restarts. Defaults to a random 4-hex-char value.
        """
        self._rng = random.Random(seed)
        self._run_id = run_id or f"{self._rng.randrange(16**4):04x}"
        self._seq = 0
        self.visits: dict[str, Visit] = {}
        # (facility_code, unit) -> set of occupied 1-based bed slots
        self._occupied: dict[tuple[str, str], set[int]] = {}
        # Relative admit-source mix across EMRs (the control-room mixer weights). Equal by default.
        self.source_weights: dict[str, float] = {e.code: 1.0 for e in EMRS}

    def set_source_weights(self, weights: dict[str, float]) -> None:
        """Update the per-EMR admit mix. Unknown codes are ignored; missing codes keep 0 weight."""
        self.source_weights = {
            e.code: max(0.0, float(weights.get(e.code, 0.0))) for e in EMRS
        }
        if sum(self.source_weights.values()) <= 0:  # never leave an all-zero mix
            self.source_weights = {e.code: 1.0 for e in EMRS}

    def _pick_source(self) -> str:
        """Choose an EMR code for a new admit, weighted by :attr:`source_weights`."""
        codes = [e.code for e in EMRS]
        weights = [self.source_weights.get(c, 0.0) for c in codes]
        if sum(weights) <= 0:
            weights = [1.0] * len(codes)
        return self._rng.choices(codes, weights=weights, k=1)[0]

    def seed_open_visits(self, rows) -> int:
        """Rehydrate currently-open visits so a restarted generator resumes real occupancy.

        Without this, a restart starts from an empty state and never discharges visits
        admitted by the previous run, leaving them stuck forever in the delete-on-A03
        ``current_census`` gold table as phantom occupied beds.

        Args:
            rows: Iterable of mappings (e.g. ``current_census`` rows) with keys
                ``visit_number``, ``facility_code``, ``unit``, ``room``, ``patient_class``,
                ``admit_ts`` and optional patient fields. Rows missing a numeric ``room``
                (the bed slot) are skipped.

        Returns:
            The number of visits seeded.
        """
        count = 0
        for row in rows:
            row = dict(row)
            try:
                slot = int(row["room"])
            except (KeyError, TypeError, ValueError):
                continue
            admit_ts = row.get("admit_ts")
            visit = Visit(
                visit_number=row["visit_number"],
                patient_id=row.get("patient_id", ""),
                first_name=row.get("patient_first_name", ""),
                last_name=row.get("patient_last_name", ""),
                sex=row.get("patient_sex", ""),
                dob=row.get("patient_dob", ""),
                facility_code=row["facility_code"],
                unit=row["unit"],
                room=row["room"],
                bed=row.get("bed") or "01",
                patient_class=row["patient_class"],
                admit_ts=admit_ts if isinstance(admit_ts, datetime) else datetime.now(),
                bed_slot=slot,
                source_system=row.get("source_system") or self._pick_source(),
            )
            self.visits[visit.visit_number] = visit
            self._occupied.setdefault((visit.facility_code, visit.unit), set()).add(
                slot
            )
            count += 1
        return count

    def _facility(self, facility_code: str) -> Facility:
        return next(f for f in FACILITIES if f.code == facility_code)

    def _unit(self, facility_code: str, unit_name: str) -> Unit:
        facility = self._facility(facility_code)
        return next(u for u in facility.units if u.name == unit_name)

    def _free_slot(self, facility_code: str, unit: Unit) -> int | None:
        occupied = self._occupied.setdefault((facility_code, unit.name), set())
        for slot in range(1, unit.bed_capacity + 1):
            if slot not in occupied:
                return slot
        return None

    def _units_with_capacity(self) -> list[tuple[Facility, Unit]]:
        out = []
        for facility in FACILITIES:
            for unit in facility.units:
                if (facility.code, unit.name) in _PINNED_SET:
                    continue  # pinned units are managed by _maintain_pins, not random admits
                if self._free_slot(facility.code, unit) is not None:
                    out.append((facility, unit))
        return out

    def total_capacity(self) -> int:
        return sum(u.bed_capacity for f in FACILITIES for u in f.units)

    def occupancy_ratio(self) -> float:
        return len(self.visits) / self.total_capacity()

    def _new_patient(self) -> tuple[str, str, str, str, str]:
        self._seq += 1
        patient_id = f"{self._run_id}P{self._seq:07d}"
        first = self._rng.choice(_FIRST_NAMES)
        last = self._rng.choice(_LAST_NAMES)
        sex = self._rng.choice(["M", "F"])
        birth = datetime(1930, 1, 1) + timedelta(days=self._rng.randint(0, 31000))
        return patient_id, first, last, sex, birth.strftime("%Y%m%d")

    def _admit(self, now: datetime) -> str:
        facility, unit = self._rng.choice(self._units_with_capacity())
        return self._admit_to(facility, unit, now)

    def _admit_to(self, facility: Facility, unit: Unit, now: datetime) -> str:
        """Admit a new patient into a specific unit (assumes it has a free slot)."""
        slot = self._free_slot(facility.code, unit)
        self._occupied[(facility.code, unit.name)].add(slot)

        patient_id, first, last, sex, dob = self._new_patient()
        visit = Visit(
            visit_number=f"{self._run_id}V{self._seq:07d}",
            patient_id=patient_id,
            first_name=first,
            last_name=last,
            sex=sex,
            dob=dob,
            facility_code=facility.code,
            unit=unit.name,
            room=f"{slot:03d}",
            bed="01",
            patient_class=unit.patient_class,
            admit_ts=now,
            bed_slot=slot,
            source_system=self._pick_source(),
        )
        self.visits[visit.visit_number] = visit
        trigger = "A04" if facility.kind == "outpatient" else "A01"
        return build_adt_message(
            trigger,
            visit,
            now,
            self._control_id(),
            emr=emr_by_code(visit.source_system),
        )

    def _discharge(self, now: datetime) -> str:
        """Discharge a random non-pinned visit (falls back to any visit if only pinned exist)."""
        candidates = [
            v
            for v in self.visits.values()
            if (v.facility_code, v.unit) not in _PINNED_SET
        ]
        visit = self._rng.choice(candidates or list(self.visits.values()))
        return self._discharge_visit(visit, now)

    def _discharge_visit(self, visit: Visit, now: datetime) -> str:
        self._occupied[(visit.facility_code, visit.unit)].discard(visit.bed_slot)
        del self.visits[visit.visit_number]
        return build_adt_message(
            "A03",
            visit,
            now,
            self._control_id(),
            discharge_ts=now,
            emr=emr_by_code(visit.source_system),
        )

    def _transfer(self, now: datetime) -> str:
        movable = [
            v
            for v in self.visits.values()
            if v.patient_class in ("I", "E")
            and (v.facility_code, v.unit) not in _PINNED_SET
        ]
        if not movable:
            return self._discharge(now)
        visit = self._rng.choice(movable)
        facility = self._facility(visit.facility_code)
        targets = [
            u
            for u in facility.units
            if u.name != visit.unit
            and (facility.code, u.name) not in _PINNED_SET
            and self._free_slot(facility.code, u) is not None
        ]
        if not targets:
            # No room to move within the facility; discharge instead.
            return self._discharge(now)

        target = self._rng.choice(targets)
        slot = self._free_slot(facility.code, target)
        self._occupied[(visit.facility_code, visit.unit)].discard(visit.bed_slot)
        self._occupied[(facility.code, target.name)].add(slot)
        visit.unit = target.name
        visit.room = f"{slot:03d}"
        visit.bed_slot = slot
        visit.patient_class = target.patient_class
        return build_adt_message(
            "A02", visit, now, self._control_id(), emr=emr_by_code(visit.source_system)
        )

    def _maintain_pins(self, now: datetime) -> str | None:
        """Keep the pinned hot units inside their occupancy band.

        Runs before the normal flow on every event so the dashboard's "facilities near capacity"
        panel always shows a CRITICAL and a WARNING facility: a pin below its floor gets one
        admit; a pin above its ceiling (e.g. after rehydrating a fuller census) gets one
        discharge. Returns the ADT message for that correction, or None when every pin is in band.
        """
        for pin in _PINNED_UNITS:
            occ = len(self._occupied.get((pin.facility, pin.unit), set()))
            if occ < pin.low:
                return self._admit_to(
                    self._facility(pin.facility),
                    self._unit(pin.facility, pin.unit),
                    now,
                )
            if occ > pin.high:
                visit = self._rng.choice(
                    [
                        v
                        for v in self.visits.values()
                        if v.facility_code == pin.facility and v.unit == pin.unit
                    ]
                )
                return self._discharge_visit(visit, now)
        return None

    def _control_id(self) -> str:
        return f"{self._run_id}{self._seq:07d}"

    def generate_event(self, now: datetime | None = None) -> str:
        """Advance state by one ADT event and return the rendered message.

        The event type is chosen probabilistically from what is currently possible: an admit
        (weighted higher when beds are free), a discharge (weighted higher when full), or a
        transfer. The ``now`` time of day tilts the admit/discharge balance toward admits in the
        morning and discharges in the late afternoon. When the network is empty this always
        admits; when it is completely full it always discharges.

        Args:
            now: Event timestamp; defaults to :func:`datetime.now`.

        Returns:
            The HL7v2 message string for the chosen event.
        """
        now = now or datetime.now()
        # Hold the pinned hot units in band first so the near-capacity panel is never empty.
        pinned = self._maintain_pins(now)
        if pinned is not None:
            return pinned
        has_capacity = bool(self._units_with_capacity())
        open_visits = bool(self.visits)

        if not open_visits:
            return self._admit(now)
        if not has_capacity:
            return self._discharge(now)

        occ = self.occupancy_ratio()
        # Occupancy sets the baseline admit/discharge balance; the time-of-day tilt then skews
        # toward admits in the morning and discharges in the late afternoon.
        tilt = admit_discharge_bias(now)
        choices: list[str] = ["admit", "discharge"]
        weights: list[float] = [
            max(0.1, 0.65 - 0.5 * occ + _BIAS_STRENGTH * tilt),
            max(0.1, 0.25 + 0.45 * occ - _BIAS_STRENGTH * tilt),
        ]
        if any(
            v.patient_class in ("I", "E")
            and (v.facility_code, v.unit) not in _PINNED_SET
            for v in self.visits.values()
        ):
            choices.append("transfer")
            weights.append(0.15)

        action = self._rng.choices(choices, weights=weights, k=1)[0]
        return {
            "admit": self._admit,
            "discharge": self._discharge,
            "transfer": self._transfer,
        }[action](now)
