---
name: funke-hl7v2
description: HL7v2 message parsing on Databricks with funke (ADT, ORU, ORM, OML, VXU, MDM, SIU, DFT). Parses raw HL7v2 files from a Unity Catalog Volume into a nested Spark column in Delta, then extracts segments, fields, components and repeating segments (OBX results, RXA immunizations) with SQL or PySpark. Covers the notebook install on serverless, the Asset Bundle pipeline (raw_messages, parsed_messages), FHS/BHS batch files and silent NULL parses. Not for FHIR, X12 claims or C-CDA documents, and not an MLLP listener.
license: Databricks License (see LICENSE.md)
compatibility: Databricks workspace with Unity Catalog and serverless or classic compute. Works with Agent Skills clients such as Genie Code, Claude Code, Codex and Cursor.
metadata:
  author: Rohan Parikh
  version: "0.1.0"
  category: Payer and provider
  summary: "Parse HL7v2 messages into Delta with funke and query segments, fields and repeating segments with SQL."
---

# funke-hl7v2

## Overview

funke parses HL7v2 messages into a native nested Spark type, so HL7 feeds (admissions, lab results, orders, immunizations, documents) can be stored in Delta and queried with SQL without converting to FHIR first. This skill takes a user from raw message files in a Unity Catalog Volume to a parsed Delta table and the fields they need, and covers the streaming pipeline that ships with the repo.

## When to Use

- A user has HL7v2 message files (from Epic Bridges, Cloverleaf, Rhapsody, Mirth or another interface engine) in a Volume and wants them in Delta
- A user needs specific fields out of HL7: patient identifiers and demographics, visits, lab results, orders, vaccinations or clinical note text
- A user has repeating segments (several OBX results per ORU message, several RXA doses per VXU) and needs one row per segment
- A user receives FHS/BHS batch files and wants each message parsed
- A user wants continuous ingestion from a landing Volume with the funke Asset Bundle pipeline
- funke is already deployed and the user asks a data question about the HL7 feed

## Prerequisites

- **Data**: HL7v2 messages landed as files in a Unity Catalog Volume, one message per file or FHS/BHS batch files. funke reads files; it does not receive messages over MLLP.
- **Compute**: a notebook on serverless or classic compute (Python 3.10 or later). Queries on parsed tables run on any SQL warehouse.
- **Permissions**: READ VOLUME on the source Volume; USE CATALOG, USE SCHEMA and CREATE TABLE where results are written. The bundle also needs CREATE SCHEMA and the ability to create pipelines, jobs, dashboards and apps.
- **Install**: funke is not on PyPI. Install it from GitHub (Workflow Step 3).

## Quick Start

```python
%pip install --no-build-isolation git+https://github.com/databricks-industry-solutions/funke-hl7v2.git
%restart_python
```

```python
import pyspark.sql.functions as F
from funke.parsing.functions import parse_hl7v2_msg
from funke.parsing.hl7 import HL7v2Schema
from funke.utils import get_value

raw = (spark.read.format("binaryFile").load("/Volumes/<catalog>/<schema>/<volume>/<folder>")
       .withColumn("content", F.regexp_replace(F.decode("content", "UTF-8"), r"^[\x0b\x1c\s]+|[\x0b\x1c\s]+$", "")))
parsed = raw.withColumn("hl7", parse_hl7v2_msg(HL7v2Schema())(F.col("content")))
parsed.write.mode("overwrite").saveAsTable("<catalog>.<schema>.hl7_parsed")

hl7 = F.col("hl7")
parsed.select(
    get_value(hl7, "MSH", 0, 9, 0, 1).alias("message_type"),
    get_value(hl7, "MSH", 0, 9, 0, 2).alias("trigger_event"),
    get_value(hl7, "PID", 0, 3, 0, 1).alias("patient_id"),
).display()
```

## Workflow

### Step 1: Check whether funke is already deployed

Look for the bundle's tables and pipeline before proposing an install. If they exist, query `parsed_messages` (Step 5) instead of rebuilding.

```sql
SHOW TABLES IN <catalog>.<schema> LIKE 'parsed_messages|raw_messages|adt_events';
```

```bash
databricks pipelines list-pipelines -p <profile> | grep -i "HL7 Ingestion"
```

With the bundle's default `dev` target, the schema is `dev_<user>_<schema>` (default schema `hl7`) and the pipeline is `[dev <user>] HL7 Ingestion`.

### Step 2: Inspect the files

Confirm each file starts with `MSH` and holds one message. Files that start with `FHS`/`BHS`, or that concatenate several messages, need the split in Common Recipes: without it a batch parses to NULL and concatenated messages merge into one parse that mixes patients, with no error.

```sql
SELECT left(regexp_replace(decode(content, 'UTF-8'), '^[\\x0b\\x1c\\s]+', ''), 3) AS first_segment, count(*) AS files
FROM read_files('/Volumes/<catalog>/<schema>/<volume>/<folder>', format => 'binaryFile')
GROUP BY 1;
```

```sql
SELECT path, size(regexp_extract_all(decode(content, 'UTF-8'), '(^|[\\r\\n\\x0b\\x1c])MSH\\|', 0)) AS messages
FROM read_files('/Volumes/<catalog>/<schema>/<volume>/<folder>', format => 'binaryFile')
WHERE size(regexp_extract_all(decode(content, 'UTF-8'), '(^|[\\r\\n\\x0b\\x1c])MSH\\|', 0)) > 1;
```

### Step 3: Install funke

In a notebook, install with `--no-build-isolation`; without it, pip's isolated build fails ("Could not find a version that satisfies the requirement setuptools") when the workspace package index does not serve `setuptools`.

```python
%pip install --no-build-isolation git+https://github.com/databricks-industry-solutions/funke-hl7v2.git
%restart_python
```

Without pip: clone the repo as a Git folder and add its `src` to the path before importing. This was tested in serverless notebooks; on classic compute or in jobs prefer `%pip` or an environment dependency, because a path change may not reach the workers.

```python
import sys
sys.path.insert(0, "/Workspace/<path-to-funke-git-folder>/src")
```

The library must reach the Spark workers. `%pip` and job or pipeline environment `dependencies` do; `pip install --target /tmp/...` installs on the driver only and the UDF fails with `No module named 'funke'`.

### Step 4: Parse into Delta

Decode the bytes, strip whitespace and MLLP framing bytes (`0x0B` before and `0x1C` after a message, often left in files saved by interface engines; a leading one makes the parse fail) and apply the UDF. Check for NULL parses every time: the UDF returns NULL instead of raising.

```python
parsed = raw.withColumn("hl7", parse_hl7v2_msg(HL7v2Schema())(F.col("content")))
parsed.write.mode("append").saveAsTable("<catalog>.<schema>.hl7_parsed")
spark.sql("SELECT count_if(hl7 IS NULL) AS failed, count(*) AS total FROM <catalog>.<schema>.hl7_parsed").display()
```

### Step 5: Extract fields

`hl7` is a map from segment name to an array of segments. Each segment has `index` (line position in the message), `segment` and `fields`.

| Level | Index base | Example for PID-5.1 (family name) |
|-------|-----------|-----------------------------------|
| Segment name | map key | `hl7.PID` |
| Segment repetition | 0 | `hl7.PID[0]` |
| Field number | 1 | `.fields[5]` |
| Field repetition | 0 | `[0]` |
| Component | 1 | `[1]` |
| Subcomponent | 1 | `[1]` |

```sql
SELECT
  hl7.MSH[0].fields[9][0][1][1]  AS message_type,    -- MSH-9.1
  hl7.MSH[0].fields[9][0][2][1]  AS trigger_event,   -- MSH-9.2
  hl7.PID[0].fields[3][0][1][1]  AS patient_id,      -- PID-3.1, first identifier
  hl7.PID[0].fields[5][0][1][1]  AS family_name,     -- PID-5.1
  hl7.PID[0].fields[5][0][2][1]  AS given_name,      -- PID-5.2
  hl7.PV1[0].fields[19][0][1][1] AS visit_number     -- PV1-19.1
FROM <catalog>.<schema>.hl7_parsed
WHERE hl7 IS NOT NULL;
```

In PySpark, `get_value(hl7, segment, segment_rep, field, field_rep, component, subcomponent=1)` takes the same positions. A missing segment or component returns NULL. A missing array element raises `INVALID_ARRAY_INDEX` on SQL warehouses and serverless (ANSI mode), so use `get(array, i)` whenever an array may be empty, such as the result of `filter()`.

### Step 6: Expand repeating segments

Messages with several OBX, RXA, OBR or NK1 segments need one row per segment. Explode the segment array.

```sql
SELECT path, obx.index AS segment_index,
  obx.fields[3][0][1][1] AS observation_code,   -- OBX-3.1
  obx.fields[5][0][1][1] AS value,              -- OBX-5
  obx.fields[6][0][1][1] AS units,              -- OBX-6.1
  obx.fields[11][0][1][1] AS result_status      -- OBX-11
FROM <catalog>.<schema>.hl7_parsed
LATERAL VIEW explode(hl7.OBX) AS obx
WHERE hl7.MSH[0].fields[9][0][1][1] = 'ORU';
```

More message types (ADT, ORU with parent OBR, VXU, MDM, ORM/OML, SIU): `references/recipes.md`.

### Step 7: Run it continuously

For a landing Volume that keeps receiving files, deploy the repo's Asset Bundle (Lakeflow pipeline `HL7 Ingestion` producing `raw_messages` and `parsed_messages`). Steps, variables and pitfalls: `references/bundle-pipeline.md`.

## Key Parameters

| Parameter | Default | Options | Effect |
|-----------|---------|---------|--------|
| `HL7v2Schema()` | bundled HL7 schema | custom `schema_path` | Schema used while splitting elements |
| `get_value(..., subcomponent)` | `1` | `1` to n | Subcomponent to return |
| Bundle `--var catalog` | `main` | any catalog with CREATE SCHEMA | Target catalog |
| Bundle `--var schema` | `hl7` | any name | Target schema (prefixed `dev_<user>_` in `dev`) |
| Bundle `--var warehouse_id` | none (required) | SQL warehouse ID | Dashboard and app warehouse |
| Bundle target `-t` | `dev` | `dev`, `prod` | The YAML sets `continuous: true`; a `dev` deploy was observed to turn it off (check the pipeline after deploying) |

## Common Recipes

### Recipe: Split files with several messages

When to use: files start with `FHS` or `BHS`, or Step 2 finds more than one MSH in a file. Without splitting, batches parse to NULL and concatenated messages merge into one parse.

```python
messages = (raw
    .withColumn("msg", F.explode(F.split(F.regexp_replace("content", r"\r\n?|\n", "\r"), r"\r(?=MSH\|)")))
    .where(F.col("msg").startswith("MSH|"))
    .withColumn("msg", F.regexp_replace("msg", r"\r(BTS|FTS)\|[^\r]*", ""))
    .withColumn("hl7", parse_hl7v2_msg(HL7v2Schema())(F.col("msg"))))
```

### Recipe: Pick an identifier by type

When to use: PID-3 repeats (MRN, account number, enterprise ID) and the user needs one type. PID-3.5 is the identifier type code.

```sql
SELECT get(filter(hl7.PID[0].fields[3], r -> r[5][1] = 'MR'), 0)[1][1] AS mrn
FROM <catalog>.<schema>.hl7_parsed;
```

### Recipe: Incremental parsing with Auto Loader

When to use: a notebook or job should pick up only new files without the bundle.

```python
(spark.readStream.format("cloudFiles").option("cloudFiles.format", "binaryFile")
    .load("/Volumes/<catalog>/<schema>/<volume>/<folder>")
    .withColumn("content", F.regexp_replace(F.decode("content", "UTF-8"), r"^[\x0b\x1c\s]+|[\x0b\x1c\s]+$", ""))
    .withColumn("hl7", parse_hl7v2_msg(HL7v2Schema())(F.col("content")))
    .writeStream.option("checkpointLocation", "/Volumes/<catalog>/<schema>/<volume>/_checkpoints/hl7")
    .trigger(availableNow=True).toTable("<catalog>.<schema>.hl7_parsed"))
```

## Expected Outputs

- A Delta table with the source path, raw message text and the parsed `hl7` column, plus a count of NULL parses
- SQL or PySpark that extracts the requested fields, with HL7 positions commented (for example `PID-5.1`)
- One row per repeating segment where the request needs it (results, doses, orders)

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `hl7` is NULL for some rows | Batch envelope, leading MLLP byte or blank line, or a malformed message; the UDF swallows the error | Strip `^[\x0b\x1c\s]+`, split batch files, inspect `content` of NULL rows |
| `INVALID_ARRAY_INDEX` | Array element missing under ANSI mode | Use `get(array, i)` for arrays that may be empty |
| `No module named 'funke'` in the UDF | Library installed on the driver only | Use `%pip` or an environment dependency |
| `Could not find a version that satisfies the requirement setuptools` | Package index does not serve build dependencies | `%pip install --no-build-isolation ...` or the Git folder path |
| `bundle deploy` fails with "externally-managed-environment" | Wheel build runs `python3 -m pip` on Homebrew or system Python | Deploy from an activated virtual environment |
| `no value assigned to required variable warehouse_id` | Bundle variable not set | `--var warehouse_id=<id>` |
| Patient ID column empty | Reading PID-2, a backward-compatibility field | Use PID-3 (Recipe: Pick an identifier by type) |
| Unexpected segment keys such as `''` | Trailing MLLP byte `0x1C`, blank lines or wrapped lines inside a message | Strip framing bytes before parsing; ignore unknown keys; fix line wrapping upstream |

## Guardrails

1. HL7 messages contain PHI. Write results only to governed Unity Catalog schemas, never print raw messages into shared outputs, and use the `phi-deidentifier` skill (Vital Skills) or equivalent before sharing.
2. Ask before deploying the bundle or starting pipelines. The pipelines are defined as continuous and bill until stopped; after any deploy, check whether they are continuous and running, and stop them if the user did not ask for live ingestion.
3. Parsed output is a data representation, not clinical validation.
4. Do not edit generated files under `src/funke/data/`; regenerate them with `just build-schema`.
5. Avoid retrying a failing install or deploy more than 3 times; collect the error and point the user to the repo's GitHub Issues.

## Bundled Resources

- `references/recipes.md` - SQL recipes by message type (ADT, ORU with parent OBR, VXU, MDM, ORM/OML, SIU)
- `references/bundle-pipeline.md` - Asset Bundle deploy, variables, targets and pipeline behavior

## References

- [funke-hl7v2](https://github.com/databricks-industry-solutions/funke-hl7v2) - library, pipeline and samples (README sections "Getting Started" and "Using the funke library directly")
- [HL7 Version 2 product brief](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185) - message, segment and field definitions
- [Agent Skills specification](https://agentskills.io/specification) - format this skill follows
