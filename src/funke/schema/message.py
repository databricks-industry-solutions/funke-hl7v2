"""
This module defines the schema for HL7v2 messages, including segment and field definitions.

It provides functionality to parse HL7v2 message structure definitions from XML schema files
and represent them as structured Python objects, enabling validation and understanding
of the expected content within different HL7v2 message types.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass

from .namespace import _HL7_XML_NAMESPACES


@dataclass
class HL7Field:
    long_name: str
    type_: str

    @classmethod
    def from_xml(cls, element: ET.Element):
        type_ = element.find(
            ".//xsd:attribute/[@name='Type']",
            namespaces=_HL7_XML_NAMESPACES,
        ).attrib["fixed"]

        long_name = element.find(
            ".//xsd:attribute/[@name='LongName']",
            namespaces=_HL7_XML_NAMESPACES,
        ).attrib["fixed"]
        return cls(long_name, type_)

    def to_dict(self) -> dict:
        return {"type": self.type_, "longName": self.long_name}


@dataclass
class HL7MessageSchema:
    """
    Represents the schema for an HL7v2 message, including its segments and their fields.

    This class provides logic for reading and transforming HL7 v2.X schemas,
    typically from XML definitions, into a structured format that can be used
    for validation or understanding message structure.

    Attributes:
        segments (Dict[str, Dict[int, str]]): A dictionary where keys are segment names
                                              (e.g., "MSH", "PID") and values are
                                              dictionaries mapping field positions
                                              (1-based index) to their data types.
    """

    segments: Dict[str, Dict[int, HL7Field]]

    @classmethod
    def from_xml(cls, xml_content: str) -> "HL7MessageSchema":
        """
        Creates an HL7MessageSchema instance by parsing XML content containing
        HL7v2 message schema definitions.

        Args:
            xml_content (str): The XML content string defining HL7v2 message schema.

        Returns:
            HL7MessageSchema: An instance of HL7MessageSchema populated with parsed segments.
        """
        # get a list of all segment names (using field schema defs)
        tree = ET.fromstring(xml_content)
        segments = {}
        for e in tree.iterfind(".xsd:attributeGroup", namespaces=_HL7_XML_NAMESPACES):
            name_parts = e.attrib["name"].split(".")
            segment = name_parts[0]
            field_number = name_parts[1]
            field = HL7Field.from_xml(e)
            # _type = e.find(
            # ".//xsd:attribute/[@name='Type']",
            # namespaces=_HL7_XML_NAMESPACES,
            # ).attrib["fixed"]
            if segment not in segments:
                segments[segment] = {}
            segments[segment][int(field_number)] = field

        return cls(segments)

    def to_dict(self) -> dict:
        """
        Converts the message schema to a dictionary representation.

        Returns:
            dict: A dictionary representing the segments and their field data types.
        """
        retdict = {}
        for segment, fields in self.segments.items():
            retdict[segment] = {}
            for field_num, field_def in fields.items():
                retdict[segment][field_num] = field_def.to_dict()
        return retdict
