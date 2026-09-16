from pyspark.sql.functions import col
import pyspark.sql.functions as F
import dlt

CATALOG_NAME = spark.conf.get("catalog")
SCHEMA_NAME = spark.conf.get("schema")
LANDING_VOLUME_NAME = spark.conf.get("landing_volume")


@dlt.table
def raw_messages():
    """
    Ingests raw message files from the specified landing volume using Auto Loader,
    decodes the content as UTF-8, and adds metadata columns for tracking:
    - md5Hash: MD5 hash of the decoded content for message tracking.
    - inserted: Timestamp when the record was ingested.
    - messageId: Unique identifier for each message.
    Returns a streaming DataFrame suitable for downstream processing in Delta Live Tables.
    """
    df = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "binaryfile")
        .load(f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{LANDING_VOLUME_NAME}")
        # decode message and add a MD5 hash for tracking message through the pipeliens
        .withColumn("content", F.decode(F.col("content"), "UTF-8"))
        .withColumn("md5Hash", F.md5(F.col("content")))
        .withColumn("inserted", F.current_timestamp())
        .withColumn("messageId", F.expr("uuid()"))
    )
    return df
