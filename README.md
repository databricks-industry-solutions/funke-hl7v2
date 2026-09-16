<img src=https://raw.githubusercontent.com/databricks-industry-solutions/.github/main/profile/solacc_logo.png width="600px">

# funke — native HL7v2 parsing for the Databricks Lakehouse

[![DBR](https://img.shields.io/badge/DBR-16.4-red?logo=databricks&style=for-the-badge)](https://docs.databricks.com/release-notes/runtime/CHANGE_ME.html)
[![CLOUD](https://img.shields.io/badge/CLOUD-ALL-blue?logo=googlecloud&style=for-the-badge)](https://databricks.com/try-databricks)

## Business Problem
Customers often face significant challenges in directly utilizing Health Level Seven (HL7v2) messages from their Electronic Health Record (EHR) systems within a modern data lakehouse environment. Traditional approaches often involve complex workarounds such as converting messages to FHIR (Fast Healthcare Interoperability Resources) or relying on third-party vendors to flatten the hierarchical HL7 structure into a tabular format. These methods can introduce delays, increase costs, and limit direct access to the rich, granular data contained within HL7 messages.

This project provides a robust, native solution for ingesting and parsing HL7v2 messages directly into the Databricks Lakehouse, enabling healthcare organizations to unlock the full potential of their clinical data for analytics, machine learning, and operational insights.

## Features
- **Comprehensive HL7v2 Parsing:** Leverages the `funke` Python library to parse HL7v2 messages, breaking down complex structures into individual segments, fields, components, repetitions, and subcomponents. It intelligently handles message separators and escape sequences as defined in the HL7v2 standard.
- **Databricks Lakehouse Integration:** Designed for seamless deployment and execution on the Databricks platform, utilizing Delta Lake for reliable and scalable storage of parsed HL7 data.
- **Medallion Architecture Support:** Implements a clear data ingestion pipeline, starting from a raw "landing" zone to a structured "bronze" layer, facilitating further transformations into "silver" and "gold" layers for various analytical use cases.
- **Scalable Data Ingestion:** Built to handle large volumes of HL7 messages, ensuring efficient and performant data processing within the Lakehouse.

## Getting Started
1. Clone this repo into your Databricks workspace
2. Open the directory in the Asset Bundle editor
3. Click _Deploy_
4. Upload HL7 messages to the automatically created `landing` volume and click _Run_ on the pipeline

## Using the `funke` library directly

The pipeline above installs `funke` for you (the Asset Bundle builds and attaches the wheel).
To use the parser on its own — in a notebook, a job, or locally — install it from source:

```bash
git clone <this-repo> && cd <this-repo>
pip install .              # add the [local] extra to also pull in PySpark: pip install ".[local]"
```

Parse a single message in plain Python:

```python
from funke.parsing.hl7 import HL7v2Msg

raw = "MSH|^~\\&|...\rPID|...\r..."   # a raw HL7v2 message string
msg = HL7v2Msg(raw)
msg.segments   # -> parsed segments, addressable as fields[field][rep][component][subcomponent]
```

Parse a whole DataFrame column with the provided Spark UDF (this is exactly what the
bronze → silver pipeline does):

```python
import pyspark.sql.functions as F
from funke.parsing.functions import parse_hl7v2_msg
from funke.parsing.hl7 import HL7v2Schema

parse = parse_hl7v2_msg(HL7v2Schema())
parsed_df = raw_df.withColumn("hl7", parse(F.col("content")))
```

## Reference Architecture

<img width="631" height="128" alt="507301026-2bd0dd56-dc7b-4374-b49a-bbd1f9dd279b" src="https://github.com/user-attachments/assets/85c299ff-dc44-401f-ae7b-f22cea01b385" />

Funke provides a declarative pipeline with two tables:
- `raw_messages` is the initial landing spot for new HL7 messages. It stores the message as plain text alongside some basic metadata about the ingestion (timestamps, hashes, size, etc.)
- `parsed_messages` is the second stage of message parsing. It transforms the raw message text into a native spark datatype (below).

```python
# Spark type for an HL7v2 field
HL7v2FieldType = T.MapType(
    T.IntegerType(),
    T.ArrayType(
        T.MapType(
            T.IntegerType(),
            T.MapType(T.IntegerType(), T.StringType()),
        )
    ),
)

# Spark type for a complete HL7v2 message
HL7v2Type = T.MapType(
    T.StringType(),
    T.ArrayType(
        T.StructType(
            [
                T.StructField("index", T.IntegerType()),
                T.StructField("segment", T.StringType()),
                T.StructField("fields", HL7v2FieldType),
            ]
        )
    ),
    True,
)
```

## Example
The following two snippets show an example of normalizing a simple ADT message in both PySpark and Spark SQL

### PySpark
```python
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
```

### Spark SQL
```sql
-- example gold table using sql
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
```

## Project support
Please note the code in this project is provided for your exploration only, and are not formally supported by Databricks with Service Level Agreements (SLAs). They are provided AS-IS and we do not make any guarantees of any kind. Please do not submit a support ticket relating to any issues arising from the use of these projects. The source in this project is provided subject to the Databricks [License](./LICENSE.md). All included or referenced third party libraries are subject to the licenses set forth below.

Any issues discovered through the use of this project should be filed as GitHub Issues on the Repo. They will be reviewed as time permits, but there are no formal SLAs for support.

## License

&copy; 2025 Databricks, Inc. All rights reserved. The source in this notebook is provided subject to the Databricks License [https://databricks.com/db-license-source]. All included or referenced third party libraries are subject to the licenses set forth below.

| library | description | license | source |
|---|---|---|---|
| v2-to-fhir | Test HL7v2 messages | Apache v2 | https://github.com/HL7/v2-to-fhir |
