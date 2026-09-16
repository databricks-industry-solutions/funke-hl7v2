# Databricks notebook source
import pyspark.sql.functions as F

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

checkpoint_path = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{CHECKPOINTS_VOLUME_NAME}/{BRONZE_TABLE_NAME}"
landing_path = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{LANDING_VOLUME_NAME}"

trigger_kwargs = {
    "availableNow": True if TRIGGER == "availableNow" else None,
    "processingTime": "5 seconds" if TRIGGER == "micro" else None,
}

# COMMAND ----------

# read in the messages as they land in the volume
df = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "binaryfile")
    .option("cloudFiles.schemaLocation", checkpoint_path)
    .load(landing_path)
    # decode message and add a MD5 hash for tracking message through the pipeliens
    .withColumn("content", F.decode(F.col("content"), "UTF-8"))
    .withColumn("md5Hash", F.md5(F.col("content")))
    .withColumn("inserted", F.current_timestamp())
)

# write out to the bronze table
(
    df.writeStream.option("checkpointLocation", checkpoint_path)
    .trigger(**trigger_kwargs)
    .toTable(f"{CATALOG_NAME}.{SCHEMA_NAME}.{BRONZE_TABLE_NAME}")
)
