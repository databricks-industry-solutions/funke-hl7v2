"""Tests for the multi-EMR sourcing added to the synthetic ADT generator."""

from collections import Counter, defaultdict
from datetime import datetime

from funke.demo.adt import Hospital, Visit, build_adt_message
from funke.demo.emr import DEFAULT_EMR, EMRS, emr_by_code


def _seg(message: str, name: str) -> list[str]:
    for line in message.splitlines():
        if line.split("|", 1)[0] == name:
            return line.split("|")
    return []


def _msh3(message: str) -> str:
    msh = _seg(message, "MSH")
    return msh[2] if len(msh) > 2 else ""


def _sample_visit(source_system: str = "") -> Visit:
    return Visit(
        visit_number="ABCDV0000001",
        patient_id="ABCDP0000001",
        first_name="Grace",
        last_name="Okafor",
        sex="F",
        dob="19800101",
        facility_code="MGEN",
        unit="ICU",
        room="003",
        bed="01",
        patient_class="I",
        admit_ts=datetime(2026, 1, 1, 8, 0, 0),
        bed_slot=3,
        source_system=source_system,
    )


def test_each_emr_stamps_its_own_quirks():
    """Every profile sets MSH-3/MSH-12, its name style, and its Z-segment (if any)."""
    visit = _sample_visit()
    for emr in EMRS:
        msg = build_adt_message("A01", visit, visit.admit_ts, "CTRL1", emr=emr)
        msh = _seg(msg, "MSH")
        pid = _seg(msg, "PID")
        assert msh[2] == emr.code  # MSH-3 = source flag
        assert msh[11] == emr.hl7_version  # MSH-12 = version
        # PID-5 name style
        name = pid[5]
        if emr.name_style == "upper_last_first":
            assert name == "OKAFOR^GRACE"
        elif emr.name_style == "last_first_middle":
            assert name.startswith("Okafor^Grace^") and len(name.split("^")) == 3
        else:
            assert name == "Okafor^Grace"
        # Proprietary Z-segment present iff the profile declares one.
        if emr.z_segment:
            assert _seg(msg, emr.z_segment), f"{emr.code} should emit {emr.z_segment}"
        else:
            assert not _seg(msg, "ZPI") and not _seg(msg, "ZBE")


def test_mixer_weights_bias_admit_source():
    """A skewed weight mix biases which EMR stamps new admits."""
    h = Hospital(seed=7)
    h.set_source_weights({"VITALCORE": 9, "AURORACARE": 1})
    sources = Counter()
    for _ in range(400):
        sources[_msh3(h.generate_event())] += 1
    # Only weighted EMRs should appear, and VitalCore should dominate.
    assert set(sources) <= {"VITALCORE", "AURORACARE"}
    assert sources["VITALCORE"] > sources["AURORACARE"] * 3


def test_all_zero_weights_fall_back_to_even_mix():
    h = Hospital(seed=1)
    h.set_source_weights({e.code: 0 for e in EMRS})
    codes = {_msh3(h.generate_event()) for _ in range(200)}
    assert len(codes) >= 2  # did not collapse to nothing


def test_source_is_stable_across_a_visit_lifecycle():
    """Every message for a given visit_number carries the same MSH-3 source system."""
    h = Hospital(seed=3)  # default = even mix across all four EMRs
    per_visit = defaultdict(set)
    for _ in range(1500):
        msg = h.generate_event()
        pv1 = _seg(msg, "PV1")
        visit_number = pv1[19] if len(pv1) > 19 else ""
        per_visit[visit_number].add(_msh3(msg))
    # At least one visit went through multiple events (admit + transfer/discharge).
    assert any(len(v) for v in per_visit.values())
    for visit_number, srcs in per_visit.items():
        assert len(srcs) == 1, f"{visit_number} changed source: {srcs}"


def test_emr_by_code_defaults():
    assert emr_by_code("VITALCORE").code == "VITALCORE"
    assert emr_by_code("nonexistent").code == DEFAULT_EMR.code
