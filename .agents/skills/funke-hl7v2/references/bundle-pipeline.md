# Asset Bundle pipeline

The repo's bundle (`databricks.yml`, bundle `hl7_ingest`) deploys a landing Volume, a Lakeflow pipeline that parses new files into Delta and an optional ADT bed-utilization demo.

## What it creates

| Resource | Name | Notes |
|----------|------|-------|
| Schema | `<schema>` (default `hl7`) | `dev_<user>_<schema>` in the `dev` target |
| Volume | `landing` | Drop HL7 files here |
| Pipeline | `HL7 Ingestion` | `raw_messages` (Auto Loader, binary files) then `parsed_messages` (adds `hl7`) |
| Pipeline | `Bed Utilization (Gold)` | Demo: `adt_events`, `facility_dim`, `current_census`, `bed_utilization` |
| Job | `Setup Bed Utilization Metric Views` | Demo: metric views over the gold tables |
| Dashboard | `Hospital Bed Utilization` | Demo, uses `warehouse_id` |
| App | `adt-control-room` | Demo: synthetic ADT generator and live census |

Pipeline and job names get a `[dev <user>]` prefix in the `dev` target; the app name does not, so two users deploying into one workspace collide on it.

## Deploy

From a local clone, inside an activated Python virtual environment (the bundle builds the funke wheel with `python3 -m pip`, which Homebrew and system Python refuse with "externally-managed-environment"):

```bash
python3 -m venv .venv && source .venv/bin/activate
databricks bundle deploy -t dev --var catalog=<catalog> --var warehouse_id=<warehouse-id> -p <profile>
```

Alternatively clone the repo into the workspace and click Deploy in the Asset Bundle editor.

A `dev` deploy (Databricks CLI v1.17.0, 2026-10-22) took a few minutes and started nothing: both pipelines were created idle with `continuous` off and `development: true`, and the app was stopped. The deployment-modes docs do not state that development mode turns `continuous` off, and a `prod` deploy was not tested, so check the pipeline settings and state after every deploy.

## Run

1. Land files in `/Volumes/<catalog>/<schema>/landing/` (in `dev`: `/Volumes/<catalog>/dev_<user>_<schema>/landing/`).
2. Start the ingest pipeline:

```bash
databricks pipelines start-update <hl7-ingestion-pipeline-id> -p <profile>
```

3. Check results: `SELECT count_if(hl7 IS NULL), count(*) FROM <catalog>.<schema>.parsed_messages;`

## Targets

| Target | Mode | Pipelines | Use |
|--------|------|-----------|-----|
| `dev` (default) | development | observed deployed with `continuous` off: an update processed 6 landed files and stopped | Trying it out |
| `prod` | production | YAML sets `continuous: true`: expect it to run and bill until stopped (not tested) | Live feeds |

Stop a continuous pipeline with `databricks pipelines stop <id> -p <profile>`; the demo app can also pause it.

## Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `catalog` | `main` | Pass a catalog where the user can create schemas |
| `schema` | `hl7` | Prefixed in `dev` |
| `warehouse_id` | none | Required; `bundle validate` fails with "no value assigned to required variable warehouse_id" without it |

## Batch files in the pipeline

`landing_to_bronze` reads each file as one message. FHS/BHS batch files land in `raw_messages` but get a NULL `hl7` in `parsed_messages`. Split them before they reach the landing Volume, or parse the NULL rows separately with the batch split in SKILL.md.
