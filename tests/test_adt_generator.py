"""Tests for the synthetic ADT generator (funke.demo)."""

from datetime import datetime

from funke.demo.adt import Hospital, Visit, build_adt_message
from funke.parsing.hl7 import HL7v2Msg, HL7v2Schema

SCHEMA = HL7v2Schema()


def _parse(msg: str) -> dict:
    return HL7v2Msg(msg, SCHEMA).segments


def _val(
    segments: dict, name: str, field: int, component: int, subcomponent: int = 1
) -> str:
    """Read the first repetition of a field at segment[0].fields[field][0][comp][sub]."""
    return segments[name][0]["fields"][field][0][component][subcomponent]


def _sample_visit() -> Visit:
    return Visit(
        visit_number="V0001",
        patient_id="P0001",
        first_name="Ada",
        last_name="Lovelace",
        sex="F",
        dob="19151210",
        facility_code="MGEN",
        unit="ICU",
        room="003",
        bed="01",
        patient_class="I",
        admit_ts=datetime(2024, 1, 2, 3, 4, 5),
        bed_slot=3,
    )


def test_admit_message_roundtrips():
    visit = _sample_visit()
    event_ts = datetime(2024, 1, 2, 9, 0, 0)
    seg = _parse(build_adt_message("A01", visit, event_ts, "CTRL1"))

    assert _val(seg, "MSH", 9, 1) == "ADT"
    assert _val(seg, "MSH", 9, 2) == "A01"  # trigger event
    assert _val(seg, "MSH", 4, 1) == "MGEN"  # sending facility
    assert _val(seg, "EVN", 1, 1) == "A01"
    assert _val(seg, "EVN", 2, 1) == "20240102090000"
    assert _val(seg, "PID", 5, 1) == "Lovelace"
    assert _val(seg, "PID", 5, 2) == "Ada"
    assert _val(seg, "PID", 7, 1) == "19151210"
    assert _val(seg, "PID", 8, 1) == "F"
    assert _val(seg, "PV1", 2, 1) == "I"  # patient class
    assert _val(seg, "PV1", 3, 1) == "ICU"  # unit / point-of-care
    assert _val(seg, "PV1", 3, 2) == "003"  # room
    assert _val(seg, "PV1", 3, 3) == "01"  # bed
    assert _val(seg, "PV1", 3, 4) == "MGEN"  # facility
    assert _val(seg, "PV1", 19, 1) == "V0001"  # visit number
    assert _val(seg, "PV1", 44, 1) == "20240102030405"  # admit ts


def test_discharge_message_sets_discharge_time():
    visit = _sample_visit()
    event_ts = datetime(2024, 1, 5, 12, 0, 0)
    seg = _parse(
        build_adt_message("A03", visit, event_ts, "CTRL2", discharge_ts=event_ts)
    )

    assert _val(seg, "MSH", 9, 2) == "A03"
    assert _val(seg, "PV1", 45, 1) == "20240105120000"  # discharge ts


def test_discharge_frees_the_admitted_bed():
    hospital = Hospital(seed=7)
    hospital._admit(datetime(2024, 1, 1, 0, 0, 0))
    visit = next(iter(hospital.visits.values()))
    key = (visit.facility_code, visit.unit)
    assert visit.bed_slot in hospital._occupied[key]

    hospital._discharge(datetime(2024, 1, 1, 1, 0, 0))
    assert hospital.visits == {}
    assert visit.bed_slot not in hospital._occupied[key]


def test_occupancy_never_exceeds_capacity():
    hospital = Hospital(seed=3)
    capacity = hospital.total_capacity()
    for _ in range(5000):
        hospital.generate_event(datetime(2024, 1, 1, 0, 0, 0))
        assert len(hospital.visits) <= capacity
        for (facility, unit_name), slots in hospital._occupied.items():
            assert len(slots) <= hospital._unit(facility, unit_name).bed_capacity


def test_pinned_units_guarantee_critical_and_warning():
    # After a warm-up the pinned units always sit at CRITICAL / WARNING utilizations, so the
    # dashboard's "facilities near capacity" panel is never empty during a demo.
    hospital = Hospital(seed=13)
    for _ in range(3000):
        hospital.generate_event(datetime(2024, 1, 1, 0, 0, 0))

    def util(facility: str, unit: str) -> float:
        return (
            len(hospital._occupied[(facility, unit)])
            / hospital._unit(facility, unit).bed_capacity
        )

    # Both ICUs are CRITICAL; the ED and med-surg floor are WARNING.
    assert util("MGEN", "ICU") >= 0.95
    assert util("LAKE", "ICU") >= 0.95
    assert 0.85 <= util("MGEN", "ED") < 0.95
    assert 0.85 <= util("LAKE", "MEDSURG") < 0.95


def test_seed_open_visits_rehydrates_occupancy():
    # Simulate a prior run: admit some patients and capture the "census" rows.
    prior = Hospital(seed=5)
    for _ in range(30):
        prior.generate_event(datetime(2024, 1, 1, 0, 0, 0))
    census_rows = [
        {
            "visit_number": v.visit_number,
            "facility_code": v.facility_code,
            "unit": v.unit,
            "room": v.room,
            "bed": v.bed,
            "patient_class": v.patient_class,
            "patient_id": v.patient_id,
            "admit_ts": v.admit_ts,
        }
        for v in prior.visits.values()
    ]

    # A restarted generator rehydrates from those rows instead of starting empty.
    restarted = Hospital(seed=1)
    seeded = restarted.seed_open_visits(census_rows)
    assert seeded == len(census_rows)
    assert len(restarted.visits) == len(prior.visits)
    # Occupancy is reconstructed, so a rehydrated visit can be discharged (frees its bed).
    v = next(iter(restarted.visits.values()))
    key = (v.facility_code, v.unit)
    assert v.bed_slot in restarted._occupied[key]
    restarted._discharge(datetime(2024, 1, 2, 0, 0, 0))
    assert len(restarted.visits) == len(census_rows) - 1


def test_generated_stream_exercises_all_events_and_parses():
    hospital = Hospital(seed=11)
    triggers = set()
    for _ in range(4000):
        seg = _parse(hospital.generate_event(datetime(2024, 1, 1, 0, 0, 0)))
        triggers.add(_val(seg, "MSH", 9, 2))
    # A01 (admit), A02 (transfer), A03 (discharge), A04 (outpatient register) all occur.
    assert {"A01", "A02", "A03", "A04"}.issubset(triggers)


def _admit_share_at_hour(hour: int, trials: int = 300) -> float:
    """Fraction of events that are admits when drawn from a fixed mid-occupancy state.

    Each trial fills a fresh hospital to ~half capacity at a neutral time, then draws one event
    at ``hour`` on a Monday, isolating the time-of-day tilt from occupancy feedback.
    """
    neutral = datetime(2024, 1, 1, 0, 0, 0)
    event_ts = datetime(2024, 1, 1, hour, 0, 0)
    admits = 0
    for t in range(trials):
        hospital = Hospital(seed=1000 + t)
        for _ in range(180):  # ~45% of 396 beds -> neither empty nor full
            hospital._admit(neutral)
        while hospital._maintain_pins(neutral) is not None:
            pass  # satisfy the pinned hot units so the measured draw is a normal-flow event
        trigger = _val(_parse(hospital.generate_event(event_ts)), "MSH", 9, 2)
        if trigger in ("A01", "A04"):
            admits += 1
    return admits / trials


def test_morning_skews_admit_vs_evening():
    # Mornings tilt toward admits, late afternoons toward discharges.
    assert _admit_share_at_hour(9) > _admit_share_at_hour(17)
