# Databricks notebook source
import pyspark.sql.functions as F
from pyspark.sql import types as T

from funke.parsing.functions import parse_hl7v2_msg
from funke.parsing.hl7 import HL7v2Schema

# COMMAND ----------

dbutils.widgets.text("catalog", "dev")
dbutils.widgets.text("schema", "hl7")
dbutils.widgets.text("landing_volume", "landing")
dbutils.widgets.text("checkpoints_volume", "landing")
dbutils.widgets.text("bronze_table", "bronze")
dbutils.widgets.text("silver_table", "bronze")
dbutils.widgets.dropdown("trigger", "availableNow", ["availableNow", "micro"])

CATALOG_NAME = dbutils.widgets.get("catalog")
SCHEMA_NAME = dbutils.widgets.get("schema")
LANDING_VOLUME_NAME = dbutils.widgets.get("landing_volume")
CHECKPOINTS_VOLUME_NAME = dbutils.widgets.get("checkpoints_volume")
BRONZE_TABLE_NAME = dbutils.widgets.get("bronze_table")
SILVER_TABLE_NAME = dbutils.widgets.get("silver_table")
TRIGGER = dbutils.widgets.get("trigger")

checkpoint_path = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{CHECKPOINTS_VOLUME_NAME}/{SILVER_TABLE_NAME}"

trigger_kwargs = {
    "availableNow": True if TRIGGER == "availableNow" else None,
    "processingTime": "5 seconds" if TRIGGER == "micro" else None,
}

# COMMAND ----------

hl7v2_schema = HL7v2Schema()


# COMMAND ----------

(
    spark.readStream.format("delta")
    .table(f"{CATALOG_NAME}.{SCHEMA_NAME}.{BRONZE_TABLE_NAME}")
    .withColumn("hl7", parse_hl7v2_msg(hl7v2_schema)(F.col("content")))
    .withColumn("inserted", F.current_timestamp())
    .writeStream.trigger(**trigger_kwargs)
    .option("checkpointLocation", checkpoint_path)
    .toTable(f"{CATALOG_NAME}.{SCHEMA_NAME}.{SILVER_TABLE_NAME}")
)
