# Databricks notebook source
from pathlib import Path
import os
import shutil
import json
import subprocess

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import VolumeType

# COMMAND ----------

HARD_RESET = True
SEED_SAMPLES = True
INSTALL_LIBRARY = True

# COMMAND ----------

with open("config.json", "r") as f:
    config = json.load(f)

# COMMAND ----------

CATALOG_NAME = config["catalog"]
SCHEMA_NAME = config["schema"]
LANDING_VOLUME_NAME = config["landing_volume_name"]
CHECKPOINTS_VOLUME_NAME = config["checkpoints_volume_name"]
LIBRARY_VOLUME_NAME = config["library_volume_name"]
BRONZE_TABLE_NAME = config["bronze_table_name"]
SILVER_TABLE_NAME = config["silver_table_name"]
GOLD_TABLE_NAME = config["gold_table_name"]

# COMMAND ----------

# create the workspace client
w = WorkspaceClient()


def cleanup():
    # delete the volume
    try:
        w.volumes.delete(name=f"{CATALOG_NAME}.{SCHEMA_NAME}.{LANDING_VOLUME_NAME}")
    except Exception as e:
        print(f"Error deleting volume: {e}")

    # delete the catalog
    try:
        w.catalogs.delete(name=CATALOG_NAME, force=True)
    except Exception as e:
        print(f"Error deleting catalog: {e}")


def init():
    # create the catalog
    print("Creating catalog")
    w.catalogs.create(name=CATALOG_NAME)

    # create the schema
    print("Creating primary schema")
    w.schemas.create(name=SCHEMA_NAME, catalog_name=CATALOG_NAME)

    # create the landing volume
    print("Creating landing volume")
    w.volumes.create(
        name=LANDING_VOLUME_NAME,
        catalog_name=CATALOG_NAME,
        schema_name=SCHEMA_NAME,
        volume_type=VolumeType.MANAGED,
    )

    # create the checkpoints volume
    print("Creating checkpoints volume")
    w.volumes.create(
        name=CHECKPOINTS_VOLUME_NAME,
        catalog_name=CATALOG_NAME,
        schema_name=SCHEMA_NAME,
        volume_type=VolumeType.MANAGED,
    )

    # create the library volume
    print("Creating library volume")
    w.volumes.create(
        name=LIBRARY_VOLUME_NAME,
        catalog_name=CATALOG_NAME,
        schema_name=SCHEMA_NAME,
        volume_type=VolumeType.MANAGED,
    )


# COMMAND ----------

if HARD_RESET:
    cleanup()

init()

if SEED_SAMPLES:
    shutil.copytree(
        Path(".") / ".." / "hl7-samples",
        f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{LANDING_VOLUME_NAME}",
        dirs_exist_ok=True,
    )

if INSTALL_LIBRARY:
    # copy the lib
    subprocess.run(["python3", "-m pip install --upgrade build"])
    subprocess.run("cd .. && python3 -m build", shell=True)

    shutil.copytree(
        Path(".") / ".." / "dist",
        f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{LIBRARY_VOLUME_NAME}/funke",
        dirs_exist_ok=True,
    )
