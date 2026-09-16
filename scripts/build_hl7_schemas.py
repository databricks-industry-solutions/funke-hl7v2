# needed to make this work locally
import sys

sys.path.append(".")

import os
from pathlib import Path
import json

from funke.schema import HL7Version, HL7DataTypes, HL7MessageSchema


def parse_xml_schema(schema_dir: Path, output_dir: Path):
    try:
        os.makedirs(output_dir)
    except OSError as e:
        if e.errno == 17:
            pass
        else:
            raise e

    with open(schema_dir / "fields.xsd", "r") as f:
        schema = HL7MessageSchema.from_xml(f.read())

    with open(output_dir / "schema.json", "w") as f:
        json.dump(schema.to_dict(), f, indent=4)

    with open(schema_dir / "datatypes.xsd", "r") as f:
        datatypes = HL7DataTypes.from_xml(f.read())

    with open(output_dir / "datatypes.json", "w") as f:
        json.dump(datatypes.to_dict(), f, indent=4)

    return


def construct_schema_path(base_path: Path, version: HL7Version) -> Path:
    return base_path / f"HL7-xml-{version.name.replace('_', '.').lower()}"


def construct_output_path(base_path: Path, version: HL7Version) -> Path:
    return base_path / version.name.lower()


if __name__ == "__main__":
    for version in HL7Version:
        print(f"Parsing schema for {version=}")
        schema_path = construct_schema_path(Path("./data/hl7-schemas"), version)
        output_path = construct_output_path(Path("./data/hl7-schemas-parsed"), version)
        try:
            parse_xml_schema(schema_path, output_path)
        except OSError as e:
            if e.errno == 2:
                print(f"Error parsing schema for {version}:", e)
