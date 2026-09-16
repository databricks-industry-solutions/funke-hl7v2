"""
The 'funke.utils' package provides utility functions to support HL7v2 message processing.

These utilities include functions for extracting specific information from HL7v2 messages
using PySpark, facilitating data manipulation and transformation within a Databricks
environment.
"""

from pyspark.sql import Column
import pyspark.sql.functions as F


def parse_hl7_version(message: Column) -> Column:
    """
    Extracts the HL7 version from an HL7 message represented as a PySpark Column.

    This function parses the MSH segment of an HL7 message to identify the
    version information (MSH.12). It dynamically determines the field separator
    from the MSH segment itself.

    Args:
        message (Column): A PySpark Column containing the HL7 message string.

    Returns:
        Column: A PySpark Column containing the extracted HL7 version string
                (e.g., "2.3", "2.5.1").
    """
    # pull out the field sep, split based on the extracted field, take the 12th
    # field, convert to format used in the HL7Version enum
    return F.split_part(message, F.regexp_extract(message, "(?<=MSH)(.)", 1), F.lit(12))


def get_segment(message: Column, segment: str, repetition: int = 0) -> Column:
    return message.getItem(segment).getItem(repetition)


def get_field(segment: Column, field: int, repetition: int = 0) -> Column:
    return segment.getItem("fields").getItem(field).getItem(repetition)


def get_component(field: Column, component: int) -> Column:
    return field.getItem(component)


def get_subcomponent(component: Column, subcomponent: int) -> Column:
    return component.getItem(subcomponent)


def get_value(
    root: Column,
    segment: str,
    segment_repetition: int,
    field: int,
    field_repetition: int,
    component: int,
    subcomponent: int = 1,
) -> str:
    return get_subcomponent(
        get_component(
            get_field(
                get_segment(root, segment, segment_repetition),
                field,
                field_repetition,
            ),
            component,
        ),
        subcomponent,
    )
