# Databricks notebook source
dbutils.widgets.text("catalog", "dev")
dbutils.widgets.text("schema", "hl7")
dbutils.widgets.text("landing_volume", "landing")
dbutils.widgets.text("checkpoints_volume", "landing")
dbutils.widgets.text("bronze_table", "raw_messages")
dbutils.widgets.text("silver_table", "parsed_messages")

CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
LANDING_VOLUME_NAME = dbutils.widgets.get("landing_volume")
CHECKPOINTS_VOLUME_NAME = dbutils.widgets.get("checkpoints_volume")
BRONZE_TABLE_NAME = dbutils.widgets.get("bronze_table")
SILVER_TABLE_NAME = dbutils.widgets.get("silver_table")

# COMMAND ----------

import pyspark.sql.functions as F
from pyspark.sql import DataFrame, Column
import json

# COMMAND ----------

# MAGIC %md
# MAGIC # Example automatic parsing

# COMMAND ----------

with open("../../data/hl7-schemas-parsed/v2_8_1/schema.json", "r") as f:
    schema_v2_8_1 = json.load(f)

with open("../../data/hl7-schemas-parsed/v2_8_1/datatypes.json", "r") as f:
    datatypes_v2_8_1 = json.load(f)


def compile_message_schema(raw_schema: dict, raw_datatypes: dict) -> dict:
    """
    segment: [
    {field, component, subcomponent, field_name, component_name}
    ]
    """
    message_schema = {}

    for segment, segment_def in raw_schema.items():
        field_list = []
        for field_number, field_def in segment_def.items():
            field = field_number
            type_ = field_def["type"]

            # if this field is defined as a simple type, just add a single entry
            # TODO: Handle composite types (FT, TX, varies)
            if type_ in raw_datatypes["SIMPLE"] or type_ in ["FT", "TX", "varies"]:
                field_list.append(
                    {
                        "field": field,
                        "component": 1,
                        "subcomponent": 1,
                        "fieldName": field_def["longName"],
                        "componentName": field_def["longName"],
                    }
                )
            else:
                type_def = raw_datatypes["COMPLEX"][type_]
                for component_number, component_def in type_def.items():
                    component = int(component_number)
                    field_list.append(
                        {
                            "field": field,
                            "component": component,
                            "subcomponent": 1,
                            "fieldName": field_def["longName"],
                            "componentName": component_def["longName"],
                        }
                    )
        message_schema[segment] = field_list

    return message_schema


# construct a column name based on the long name
def construct_column_name(field_name: str) -> str:
    title_case = field_name.title()
    camel_case = title_case[0].lower() + title_case[1:]
    return (
        camel_case.replace(" ", "")
        .replace("[", "")
        .replace("]", "")
        .replace(".", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace("/", "")
        .replace("'", "")
    )


def get_segment(message: Column, segment: str, repetition: int = 0) -> Column:
    return message.getItem(segment).getItem(repetition)


def get_field(segment: Column, field: int, repetition: int = 0) -> Column:
    return segment.getItem("fields").getItem(field).getItem(repetition)


def get_component(field: Column, component: int) -> Column:
    return field.getItem(component)


def get_subcomponent(component: Column, subcomponent: int) -> Column:
    return component.getItem(subcomponent)


def get_value(
    root: Column,
    segment: str,
    segment_repetition: int,
    field: int,
    field_repetition: int,
    component: int,
    subcomponent: int = 1,
) -> str:
    return get_subcomponent(
        get_component(
            get_field(
                get_segment(root, segment, segment_repetition), field, field_repetition
            ),
            component,
        ),
        subcomponent,
    )


def compile_select_list(
    root: Column,
    segment: str,
    segment_repetition: int,
    message_schema: dict,
    naming_convention: str = "long",
):
    select_list = []
    for field in message_schema[segment]:
        if naming_convention == "long":
            alias = (
                construct_column_name(field["fieldName"])
                + "_"
                + construct_column_name(field["componentName"])
            )
        else:
            alias = f"{segment}_{field['field']}_{field['component']}_1"

        select_list.append(
            get_value(
                root,
                segment,
                segment_repetition,
                field["field"],
                0,
                field["component"],
                1,
            ).alias(alias)
        )
    return select_list

# COMMAND ----------

hl7_df = spark.read.table(f"{CATALOG_NAME}.{SCHEMA_NAME}.{SILVER_TABLE_NAME}")
select_list = compile_select_list(
    F.col("hl7"),
    "MSH",
    0,
    compile_message_schema(schema_v2_8_1, datatypes_v2_8_1),
    "long",
)
(
    hl7_df.select(select_list)
    .withColumn("segmentRepetition", F.lit(0))
    # .where("MSH_9_2_1 = 'A01'")
    .where("messageType_triggerEvent = 'A01'")
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC # Example basic parsing (recommended method)

# COMMAND ----------

# example gold table using pyspark
silver_df = spark.read.table(f"{CATALOG_NAME}.{SCHEMA_NAME}.{SILVER_TABLE_NAME}")
gold_df = (
    silver_df.withColumn("messageType", silver_df.hl7.MSH[0].fields[9][0][1][1])
    .withColumn("messageEventType", silver_df.hl7.MSH[0].fields[9][0][2][1])
    .withColumn("sendingFacility", silver_df.hl7.MSH[0].fields[4][0][2][1])
    .withColumn("eventTimestamp", silver_df.hl7.EVN[0].fields[2][0][1][1])
    .withColumn("patientId", silver_df.hl7.PID[0].fields[2][0][1][1])
    .withColumn("patientClass", silver_df.hl7.PV1[0].fields[2][0][1][1])
    .withColumn("patientFirstName", silver_df.hl7.PID[0].fields[5][0][2][1])
    .withColumn("patientLastName", silver_df.hl7.PID[0].fields[5][0][1][1])
    .withColumn("patientGender", silver_df.hl7.PID[0].fields[8][0][1][1])
    .withColumn("patientBirthDate", silver_df.hl7.PID[0].fields[7][0][1][1])
    .select(
        [
            F.col("md5Hash").alias("messageId"),
            "messageType",
            "messageEventType",
            "sendingFacility",
            "eventTimestamp",
            "patientId",
            "patientClass",
            "patientFirstName",
            "patientLastName",
            "patientGender",
            "patientBirthDate",
        ]
    )
    .where(F.col("messageType").isNotNull())
)

gold_df.display()

# COMMAND ----------

# example gold table using SQL
spark.sql(
    f"""
SELECT
  md5Hash AS messageId,
  hl7.MSH[0].fields[9][0][1][1] AS messageType,
  hl7.MSH[0].fields[9][0][2][1] AS messageEventType,
  hl7.MSH[0].fields[4][0][2][1] AS sendingFacility,
  hl7.EVN[0].fields[2][0][1][1] AS eventTimestamp,
  hl7.PID[0].fields[2][0][1][1] AS patientId,
  hl7.PV1[0].fields[2][0][1][1] AS patientClass,
  hl7.PID[0].fields[5][0][2][1] AS patientFirstName,
  hl7.PID[0].fields[5][0][1][1] AS patientLastName,
  hl7.PID[0].fields[8][0][1][1] AS patientGender,
  hl7.PID[0].fields[7][0][1][1] AS patientBirthDate
FROM
  {CATALOG_NAME}.{SCHEMA_NAME}.{SILVER_TABLE_NAME}
WHERE
  hl7.MSH[0].fields[9][0][1][1] IS NOT NULL
"""
).display()
