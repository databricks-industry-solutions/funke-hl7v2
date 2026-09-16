import pyspark.sql.functions as F
import dlt
from funke.parsing.functions import parse_hl7v2_msg
from funke.parsing.hl7 import HL7v2Schema

hl7v2_schema = HL7v2Schema()


@dlt.table
def parsed_messages():
    """
    Parses raw HL7v2 messages from the 'raw_messages' streaming table,
    extracts HL7 segments using a utility function, and adds an 'inserted' timestamp.

    Returns:
        DataFrame: Parsed messages with extracted HL7 segments and ingestion timestamp.
    """
    return (
        spark.readStream.table("raw_messages")
        .withColumn("hl7", parse_hl7v2_msg(hl7v2_schema)(F.col("content")))
        .withColumn("inserted", F.current_timestamp())
    )
