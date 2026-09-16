# Databricks notebook source
import uuid
import os
import shutil
import json

# COMMAND ----------

CATALOG_NAME = "main"
SCHEMA_NAME = "hl7"
LANDING_VOLUME_NAME = "landing"

# COMMAND ----------

from datetime import datetime
import random

hour_ET = datetime.now().hour - 4

distance_from_noon = abs(hour_ET - 12)
print(distance_from_noon)

N = random.randint(0, 1 + 100 * (12 - distance_from_noon))
print(f"Generating {N=} files")

# COMMAND ----------

# make N copies of each file in the samples dir, give them a UUID as the name, copy to the landing volume
landing_directory = f"/Volumes/{CATALOG_NAME}/{SCHEMA_NAME}/{LANDING_VOLUME_NAME}"
starter_files = os.listdir("../../data/hl7-samples/")
for file in starter_files:
    # skip any workspace files that we dont care about
    if not (file.endswith(".hl7") or file.endswith(".txt")):
        continue

    for i in range(random.randint(0, N)):
        # create a new name, slap .hl7 on the end of it
        new_file_name = str(uuid.uuid4()) + ".hl7"
        print(f"{i=}\tDuplicating {file} as {new_file_name}")

        # ship it off
        shutil.copy(
            "../../data/hl7-samples/" + file,
            os.path.join(landing_directory, new_file_name),
        )
