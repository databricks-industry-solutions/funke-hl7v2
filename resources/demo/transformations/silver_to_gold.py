"""
Gold layer for the bed-utilization demo.

Turns the parsed ADT event stream (``parsed_messages``) into:
  * ``adt_events``      — one flattened row per ADT message (append, full history).
  * ``facility_dim``    — the fixed facility/unit/bed-capacity reference.
  * ``current_census``  — live occupied beds, maintained by CDC keyed on the visit number
                          (an A03 discharge deletes the visit, freeing the bed).
  * ``bed_utilization`` — occupied vs capacity and utilization % per facility/unit.

This file is globbed into the ``bed_utilization`` gold pipeline via ``transformations/**``.
``parsed_messages`` is produced by the separate ``hl7_ingest`` pipeline, so it is read by
its full UC name; every table defined here is intra-pipeline and stays relative.
"""

import dlt
import pyspark.sql.functions as F

from funke.utils import get_value
from funke.demo.facilities import facility_dim_rows

# ADT trigger events that participate in bed occupancy.
ADT_TRIGGERS = ["A01", "A02", "A03", "A04"]
_HL7_DTM = "yyyyMMddHHmmss"

# parsed_messages is published by the upstream hl7_ingest pipeline into this same schema; a
# cross-pipeline streaming read needs the fully-qualified name.
CATALOG = spark.conf.get("catalog")
SCHEMA = spark.conf.get("schema")
PARSED_MESSAGES = f"{CATALOG}.{SCHEMA}.parsed_messages"


@dlt.table(
    comment="One flattened row per ADT message, extracted from the nested hl7 column."
)
def adt_events():
    hl7 = F.col("hl7")
    return (
        spark.readStream.table(PARSED_MESSAGES)
        .withColumn("event_type", get_value(hl7, "MSH", 0, 9, 0, 2))
        .withColumn("source_system", get_value(hl7, "MSH", 0, 3, 0, 1))
        .withColumn("sending_facility_code", get_value(hl7, "MSH", 0, 4, 0, 1))
        .withColumn(
            "event_ts", F.to_timestamp(get_value(hl7, "EVN", 0, 2, 0, 1), _HL7_DTM)
        )
        .withColumn("patient_class", get_value(hl7, "PV1", 0, 2, 0, 1))
        .withColumn("facility_code", get_value(hl7, "PV1", 0, 3, 0, 4))
        .withColumn("unit", get_value(hl7, "PV1", 0, 3, 0, 1))
        .withColumn("room", get_value(hl7, "PV1", 0, 3, 0, 2))
        .withColumn("bed", get_value(hl7, "PV1", 0, 3, 0, 3))
        .withColumn("visit_number", get_value(hl7, "PV1", 0, 19, 0, 1))
        .withColumn(
            "admit_ts", F.to_timestamp(get_value(hl7, "PV1", 0, 44, 0, 1), _HL7_DTM)
        )
        .withColumn(
            "discharge_ts", F.to_timestamp(get_value(hl7, "PV1", 0, 45, 0, 1), _HL7_DTM)
        )
        .withColumn("patient_id", get_value(hl7, "PID", 0, 3, 0, 1))
        .withColumn("patient_last_name", get_value(hl7, "PID", 0, 5, 0, 1))
        .withColumn("patient_first_name", get_value(hl7, "PID", 0, 5, 0, 2))
        .withColumn("patient_sex", get_value(hl7, "PID", 0, 8, 0, 1))
        .where(F.col("event_type").isin(ADT_TRIGGERS))
        .select(
            F.col("messageId"),
            "event_type",
            "source_system",
            "event_ts",
            "facility_code",
            "sending_facility_code",
            "patient_class",
            "unit",
            "room",
            "bed",
            "visit_number",
            "patient_id",
            "patient_first_name",
            "patient_last_name",
            "patient_sex",
            "admit_ts",
            "discharge_ts",
            "inserted",
        )
    )


@dlt.table(comment="Fixed facility/unit/bed-capacity reference for utilization math.")
def facility_dim():
    return spark.createDataFrame(facility_dim_rows())


# Live census: SCD-1 CDC keyed on visit_number. A03 (discharge) deletes the visit, so the
# table always reflects exactly the beds that are currently occupied (latest location wins).
dlt.create_streaming_table(
    "current_census",
    comment="Currently occupied beds — one row per open visit, discharges removed.",
)
dlt.apply_changes(
    target="current_census",
    source="adt_events",
    keys=["visit_number"],
    sequence_by=F.col("event_ts"),
    apply_as_deletes=F.expr("event_type = 'A03'"),
    stored_as_scd_type=1,
)


@dlt.table(comment="Occupied vs capacity and utilization % per facility/unit.")
def bed_utilization():
    occupied = (
        spark.read.table("current_census")
        .groupBy("facility_code", "unit")
        .agg(F.count("*").alias("occupied_beds"))
    )
    return (
        spark.read.table("facility_dim")
        .join(occupied, ["facility_code", "unit"], "left")
        .withColumn("occupied_beds", F.coalesce(F.col("occupied_beds"), F.lit(0)))
        .withColumn("available_beds", F.col("bed_capacity") - F.col("occupied_beds"))
        .withColumn(
            "utilization_pct",
            F.round(100.0 * F.col("occupied_beds") / F.col("bed_capacity"), 1),
        )
    )
