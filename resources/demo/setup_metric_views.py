# Databricks notebook source
# MAGIC %md
# MAGIC # Bed Utilization Metric Views
# MAGIC Creates two Unity Catalog metric views over the gold tables so the dashboard (and
# MAGIC Genie/ad-hoc queries) share consistent, governed definitions of census, capacity,
# MAGIC utilization %, admits, discharges and length of stay.

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "hl7")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
FQN = f"{CATALOG}.{SCHEMA}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## `bed_census_metrics` — occupancy vs capacity (current snapshot)
# MAGIC Built on the `bed_utilization` gold table (one row per facility/unit).

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {FQN}.bed_census_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: {FQN}.bed_utilization
dimensions:
  - name: Facility
    expr: facility_name
  - name: Facility Code
    expr: facility_code
  - name: Facility Kind
    expr: facility_kind
  - name: Unit
    expr: unit
  - name: Patient Class
    expr: patient_class
measures:
  - name: Occupied Beds
    expr: SUM(occupied_beds)
  - name: Bed Capacity
    expr: SUM(bed_capacity)
  - name: Available Beds
    expr: SUM(available_beds)
  - name: Utilization %
    expr: ROUND(100.0 * SUM(occupied_beds) / NULLIF(SUM(bed_capacity), 0), 1)
$$
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## `adt_event_metrics` — patient flow over time
# MAGIC Built on the `adt_events` gold table (one row per ADT message).

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {FQN}.adt_event_metrics
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1
source: {FQN}.adt_events
dimensions:
  - name: Facility Code
    expr: facility_code
  - name: Unit
    expr: unit
  - name: Patient Class
    expr: patient_class
  - name: Event Type
    expr: event_type
  - name: Event Date
    expr: CAST(event_ts AS DATE)
  - name: Event Hour
    expr: DATE_TRUNC('HOUR', event_ts)
measures:
  - name: Admits
    expr: COUNT(*) FILTER (WHERE event_type IN ('A01', 'A04'))
  - name: Discharges
    expr: COUNT(*) FILTER (WHERE event_type = 'A03')
  - name: Transfers
    expr: COUNT(*) FILTER (WHERE event_type = 'A02')
  - name: Events
    expr: COUNT(*)
  - name: Avg Length of Stay (hrs)
    expr: >-
      ROUND(AVG((UNIX_TIMESTAMP(discharge_ts) - UNIX_TIMESTAMP(admit_ts)) / 3600.0)
      FILTER (WHERE event_type = 'A03'), 1)
$$
""")

# COMMAND ----------

# Metric views require MEASURE() with GROUP BY — a plain SELECT * is not valid.
display(
    spark.sql(
        f"SELECT `Facility`, MEASURE(`Occupied Beds`) AS occupied_beds, "
        f"MEASURE(`Utilization %`) AS utilization_pct "
        f"FROM {FQN}.bed_census_metrics GROUP BY `Facility` ORDER BY utilization_pct DESC"
    )
)
