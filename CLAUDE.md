# CLAUDE.md

This file has two halves: **behavioral guidelines** (sections 1–4, general working style)
and **project context** (the `funke` project facts and conventions further down).

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# Project Context: `funke`

## Overview

`funke` is a native **HL7v2** message parser for the Databricks Lakehouse. It parses raw
HL7v2 messages into Spark-native nested types (segments → fields → components → repetitions →
subcomponents) without first converting to FHIR or relying on third-party flattening.

It ships two things:
- The `funke` Python library under `src/funke/`.
- A Databricks Asset Bundle (`databricks.yml`, bundle `hl7_ingest`) that runs a medallion
  pipeline (landing → bronze → silver → gold), producing the Delta tables `raw_messages`
  and `parsed_messages`.

This is a Databricks Industry Solutions Accelerator — provided AS-IS, with no SLA.

## Tech Stack

- Python ≥ 3.10; PySpark ≥ 3.5; pytest ≥ 8.4 for tests. Packaged via setuptools
  (`pyproject.toml`, `src/` layout). Deployed via Databricks Asset Bundles (DAB).
- Tooling: `just` (command runner), `direnv` (environment management), `black` (formatter).

## Repository Layout

- `src/funke/` — the library: `parsing/` (HL7 parse logic + Spark types), `schema/`
  (HL7v2 schema/datatypes/message models), `utils/` (PySpark Column helpers),
  `data/` (generated `schemas.json`, `datatypes.json`).
- `notebooks/jobs/` — pipeline transformations (`landing_to_bronze.py`,
  `bronze_to_silver.py`, `silver_to_gold.py`); `notebooks/demo/` — test-data generator.
- `resources/` — DAB resource YAML (pipeline, volumes, schemas) + transformation source.
- `scripts/build_hl7_schemas.py` — regenerates the JSON schema files under `src/funke/data/`.
- `tests/` — pytest suite (`test_utils.py`, `test_schema.py`, `conftest.py`).

## Environment Setup (direnv)

The repo has a committed `.envrc` that activates the project virtualenv and loads local env
vars from `.env` (gitignored — holds DB/Databricks secrets). After cloning, run
`direnv allow` once; the environment then loads automatically on `cd` into the repo.

## Commands (just)

- Install dev: `just dev-install` (`pip install --editable .[test]`)
- Run tests: `just test` (or `pytest tests/`)
- Format code: `just fmt` (runs `black`)
- Rebuild HL7 schemas: `just build-schema` (regenerate after schema-source changes)
- Deploy pipeline: `databricks bundle deploy` (dev target is default); the DAB builds the
  `lib_funke` wheel automatically.

## Conventions

- **Commits: Conventional Commit style is required.** Format `<type>(<scope>): <subject>`
  using `feat`, `fix`, `docs`, `style`, `refactor`, `test`, or `chore`.
- **Formatting: run `black` on changed Python before committing** (e.g. `just fmt`).
- Testing: add/adjust pytest tests under `tests/` for library changes; tests import from
  `src` via the configured `pythonpath`. **Run pytest from the repo root** —
  `tests/test_schema.py` reads schema XSDs via a relative path.
- Docstrings: match the existing **Google-style docstrings** (Args/Returns/Raises) on public
  classes and functions.
- Patterns: parsing objects use **dataclasses with `__post_init__`** (`HL7v2Encoding`,
  `HL7v2Schema`, `HL7v2Msg`). HL7 addressing is
  `segment[rep].fields[field][rep][component][subcomponent]` (1-based at
  field/component/subcomponent); use the helpers in `funke/utils`.
- After changing the HL7 schema source (XSDs under `data/hl7-schemas/`), regenerate JSON
  with `just build-schema`; don't hand-edit generated files in `src/funke/data/`.
- **Pipeline-code duplication gotcha:** the transformation notebooks exist in BOTH
  `notebooks/jobs/` and `resources/ingestion/transformations/`. The deployed Lakeflow
  pipeline globs the **`resources/ingestion/transformations/`** copies (per
  `hl7_ingest.pipeline.yml`). Edits meant to affect the running pipeline must go there.
- Databricks notebook files use `# Databricks notebook source` / `# COMMAND ----------` cell
  markers and `dbutils.widgets` for parameters — keep that format.
- Ignore `src/funke.egg-info/` — it's stale build metadata that no longer matches the current
  `pyproject.toml`.
