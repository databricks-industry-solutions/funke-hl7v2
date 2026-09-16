"""Made-up EMR source systems for the multi-EMR ADT demo.

A real hospital network ingests ADT feeds from several different EMR vendors, and no two emit
identical HL7v2 — they differ in version, custom Z-segments, and field conventions. Each
:class:`EmrProfile` here captures one fictional vendor's *safe* quirks (things the downstream
``funke`` parser and gold layer tolerate): the sending-application id (MSH-3, the source flag),
the HL7 version (MSH-12), the PID-5 name style, receiving app/facility, and an optional
proprietary Z-segment. Timestamps and delimiters are deliberately left standard so the gold
pipeline's fixed parsing keeps working.

The :class:`~funke.demo.adt.Hospital` engine assigns one profile per visit at admit time (by the
control-room mixer weights) and reuses it for that visit's transfer/discharge, so an encounter
stays consistent under a single source system.
"""

from dataclasses import dataclass
from datetime import datetime

# HL7 separators (kept local to avoid a circular import with funke.demo.adt).
_FIELD_SEP = "|"
_COMPONENT_SEP = "^"
_DTM_FORMAT = "%Y%m%d%H%M%S"


def _middle_initial(visit_number: str) -> str:
    """Deterministic middle initial for EMRs that render one (no extra Visit state needed)."""
    return chr(65 + (sum(ord(c) for c in visit_number) % 26))


@dataclass(frozen=True)
class EmrProfile:
    """One fictional EMR vendor's HL7v2 rendering conventions.

    Attributes:
        code: MSH-3 sending-application id — the source-system flag stamped on every message.
        display_name: Human-friendly name for the control-room UI.
        hl7_version: MSH-12 version string (cosmetic to the parser, visibly heterogeneous).
        name_style: PID-5 formatting — ``upper_last_first`` / ``last_first_middle`` / ``last_first``.
        receiving_app: MSH-5 receiving application.
        receiving_facility: MSH-6 receiving facility.
        z_segment: Optional proprietary Z-segment name to append (``ZPI``/``ZBE``), or ``None``.
    """

    code: str
    display_name: str
    hl7_version: str
    name_style: str
    receiving_app: str
    receiving_facility: str
    z_segment: str | None = None

    def render_name(self, visit) -> str:
        """Render PID-5 (patient name) in this EMR's style."""
        if self.name_style == "upper_last_first":
            return (
                f"{visit.last_name.upper()}{_COMPONENT_SEP}{visit.first_name.upper()}"
            )
        if self.name_style == "last_first_middle":
            initial = _middle_initial(visit.visit_number)
            return (
                f"{visit.last_name}{_COMPONENT_SEP}{visit.first_name}"
                f"{_COMPONENT_SEP}{initial}"
            )
        return f"{visit.last_name}{_COMPONENT_SEP}{visit.first_name}"

    def z_segments(self, visit, event_ts: datetime) -> list[str]:
        """Return this EMR's proprietary Z-segment lines (empty if it emits none)."""
        if self.z_segment == "ZPI":
            # Proprietary patient-info extension: source account, source system, patient class.
            return [
                _FIELD_SEP.join(
                    ["ZPI", visit.patient_id, self.code, visit.patient_class]
                )
            ]
        if self.z_segment == "ZBE":
            # Proprietary bed/movement extension: assigned location + event time.
            location = _COMPONENT_SEP.join([visit.unit, visit.room, visit.bed])
            return [_FIELD_SEP.join(["ZBE", location, event_ts.strftime(_DTM_FORMAT)])]
        return []


# The fictional EMR network. Codes are made up; none is a real vendor.
EMRS: tuple[EmrProfile, ...] = (
    EmrProfile(
        code="AURORACARE",
        display_name="AuroraCare",
        hl7_version="2.3",
        name_style="upper_last_first",
        receiving_app="AURORA",
        receiving_facility="AURORA_HUB",
    ),
    EmrProfile(
        code="MERIDIAN",
        display_name="Meridian EHR",
        hl7_version="2.5.1",
        name_style="last_first_middle",
        receiving_app="MERIDIAN",
        receiving_facility="MRDN_INTAKE",
        z_segment="ZPI",
    ),
    EmrProfile(
        code="VITALCORE",
        display_name="VitalCore",
        hl7_version="2.7",
        name_style="last_first",
        receiving_app="VITALCORE",
        receiving_facility="VC_ADT",
        z_segment="ZBE",
    ),
    EmrProfile(
        code="CAREPOINT",
        display_name="CarePoint",
        hl7_version="2.4",
        name_style="last_first",
        receiving_app="CAREPOINT",
        receiving_facility="CP_CENTRAL",
    ),
)

_BY_CODE = {e.code: e for e in EMRS}
# Fallback profile when no EMR is specified (e.g. a rehydrated visit with unknown source). The
# engine always passes an explicit profile per visit, so this only affects that fallback path;
# use the plainest style (mixed-case name, no Z-segment) so unattributed messages look neutral.
DEFAULT_EMR = _BY_CODE["CAREPOINT"]


def emr_by_code(code: str) -> EmrProfile:
    """Look up a profile by MSH-3 code, falling back to :data:`DEFAULT_EMR`."""
    return _BY_CODE.get(code, DEFAULT_EMR)
