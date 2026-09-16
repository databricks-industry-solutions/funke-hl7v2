"""
Fixed hospital-network definition shared by the synthetic ADT generator and the gold layer.

The generator uses this model to respect per-unit bed capacity when admitting patients, and
the gold pipeline materializes it as the ``facility_dim`` reference table so utilization can
be computed as occupied beds / capacity. Keeping a single source of truth here guarantees the
generated PV1 locations always resolve to a real facility/unit with a known capacity.

HL7 patient classes (PV1-2) used:
    I  Inpatient
    E  Emergency
    O  Outpatient
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Unit:
    """A staffed nursing unit within a facility.

    Attributes:
        name: Unit code used as PV1-3 point-of-care (e.g. ``ICU``, ``MEDSURG``).
        patient_class: HL7 PV1-2 patient class for visits in this unit (``I``/``E``/``O``).
        bed_capacity: Number of physical beds in the unit.
    """

    name: str
    patient_class: str
    bed_capacity: int


@dataclass(frozen=True)
class Facility:
    """A hospital or clinic in the network.

    Attributes:
        code: Short facility code used in MSH-4 and PV1-3 facility component.
        name: Human-readable facility name.
        kind: ``inpatient`` or ``outpatient`` — drives the patient-flow behavior.
        units: The units (and their capacities) inside the facility.
    """

    code: str
    name: str
    kind: str
    units: tuple[Unit, ...]


# The network: inpatient hospitals with acute units + outpatient clinics/surgery centers.
FACILITIES: tuple[Facility, ...] = (
    Facility(
        code="MGEN",
        name="Metro General Hospital",
        kind="inpatient",
        units=(
            Unit("ICU", "I", 20),
            Unit("MEDSURG", "I", 80),
            Unit("TELEMETRY", "I", 40),
            Unit("ED", "E", 30),
        ),
    ),
    Facility(
        code="LAKE",
        name="Lakeside Medical Center",
        kind="inpatient",
        units=(
            Unit("ICU", "I", 12),
            Unit("MEDSURG", "I", 60),
            Unit("MATERNITY", "I", 25),
            Unit("ED", "E", 24),
        ),
    ),
    Facility(
        code="NRGH",
        name="Northgate Rehabilitation Hospital",
        kind="inpatient",
        units=(Unit("REHAB", "I", 40),),
    ),
    Facility(
        code="DTWN",
        name="Downtown Community Clinic",
        kind="outpatient",
        units=(Unit("OPCLINIC", "O", 30),),
    ),
    Facility(
        code="WSSC",
        name="Westside Surgery Center",
        kind="outpatient",
        units=(
            Unit("DAYSURG", "O", 20),
            Unit("RECOVERY", "O", 15),
        ),
    ),
)


def facility_dim_rows() -> list[dict]:
    """Flatten the network into rows for the ``facility_dim`` reference table.

    Returns:
        One dict per (facility, unit) with keys ``facility_code``, ``facility_name``,
        ``facility_kind``, ``unit``, ``patient_class`` and ``bed_capacity``.
    """
    return [
        {
            "facility_code": f.code,
            "facility_name": f.name,
            "facility_kind": f.kind,
            "unit": u.name,
            "patient_class": u.patient_class,
            "bed_capacity": u.bed_capacity,
        }
        for f in FACILITIES
        for u in f.units
    ]
