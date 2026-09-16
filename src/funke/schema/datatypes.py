"""
This module defines classes for representing HL7v2 data types, both simple and complex.

It provides functionality to parse HL7v2 datatype definitions from XML schema files
and convert them into structured Python objects, facilitating the understanding
and validation of HL7v2 message structures.
"""

import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass

from .namespace import _HL7_XML_NAMESPACES


@dataclass
class HL7SimpleDataType:
    """
    Represents a simple HL7v2 data type.

    Attributes:
        name (str): The name of the simple data type (e.g., "ST", "ID").
    """

    name: str

    @classmethod
    def from_xml(cls, element: ET.Element) -> "HL7SimpleDataType":
        """
        Creates an HL7SimpleDataType instance from an XML element.

        Args:
            element (ET.Element): The XML element representing the simple data type.

        Returns:
            HL7SimpleDataType: An instance of HL7SimpleDataType.
        """
        return cls(element.attrib["name"])

    def to_dict(self) -> dict:
        """
        Converts the simple data type to a dictionary representation.

        Returns:
            dict: A dictionary with the data type's name.
        """
        return {"name": self.name}


@dataclass
class HL7ComplexDataTypeElement:
    """
    Represents an element within a complex HL7v2 data type.

    Attributes:
        min_occurences (int): The minimum number of occurrences for this element.
        max_occurences (int): The maximum number of occurrences for this element.
        type_ (HL7SimpleDataType): The simple data type of this element.
    """

    min_occurences: int
    max_occurences: int
    type_: HL7SimpleDataType
    long_name: str

    @classmethod
    def from_xml(
        cls, element: ET.Element, attribute_group: ET.Element
    ) -> "HL7ComplexDataTypeElement":
        """
        Creates an HL7ComplexDataTypeElement instance from XML elements.

        Args:
            element (ET.Element): The XML element representing the complex data type element.
            attribute_group (ET.Element): The XML element representing the attribute group
                                          containing type information.

        Returns:
            HL7ComplexDataTypeElement: An instance of HL7ComplexDataTypeElement.
        """
        min_occurences = element.attrib.get("minOccurs", "0")
        max_occurences = element.attrib.get("maxOccurs", "0")

        return cls(
            min_occurences,
            max_occurences,
            HL7SimpleDataType(
                attribute_group.find(
                    ".//xsd:attribute/[@name='Type']",
                    namespaces=_HL7_XML_NAMESPACES,
                ).attrib["fixed"]
            ),
            attribute_group.find(
                ".//xsd:attribute/[@name='LongName']",
                namespaces=_HL7_XML_NAMESPACES,
            ).attrib["fixed"],
        )

    def to_dict(self) -> dict:
        """
        Converts the complex data type element to a dictionary representation.

        Returns:
            dict: A dictionary with min/max occurrences and the element's type name.
        """
        return {
            "min_occurences": self.min_occurences,
            "max_occurences": self.max_occurences,
            "type": self.type_.name,
            "longName": self.long_name,
        }


@dataclass
class HL7ComplexDataType:
    """
    Represents a complex HL7v2 data type, composed of a sequence of elements.

    Attributes:
        sequence (Dict[int, HL7ComplexDataTypeElement]): A dictionary mapping
                                                        element positions to
                                                        HL7ComplexDataTypeElement instances.
    """

    sequence: Dict[int, HL7ComplexDataTypeElement]

    @classmethod
    def from_xml(
        cls, element: ET.Element, root: ET.ElementTree
    ) -> "HL7ComplexDataType":
        """
        Creates an HL7ComplexDataType instance from XML elements.

        Args:
            element (ET.Element): The XML element representing the complex data type.
            root (ET.ElementTree): The root XML element tree for resolving references.

        Returns:
            HL7ComplexDataType: An instance of HL7ComplexDataType.
        """
        sequence = {}
        for e in element.iterfind(".//xsd:element", namespaces=_HL7_XML_NAMESPACES):
            attr_group_name = f"{e.attrib['ref']}.ATTRIBUTES"
            sequence[int(e.attrib["ref"].split(".")[1])] = (
                HL7ComplexDataTypeElement.from_xml(
                    e,
                    root.find(
                        f".//xsd:attributeGroup/[@name='{attr_group_name}']",
                        namespaces=_HL7_XML_NAMESPACES,
                    ),
                )
            )
        return cls(sequence)

    def to_dict(self) -> dict:
        """
        Converts the complex data type to a dictionary representation.

        Returns:
            dict: A dictionary representing the sequence of elements within the
                  complex data type.
        """
        ret_dict = {}
        for k, v in self.sequence.items():
            ret_dict[k] = v.to_dict()
        return ret_dict


@dataclass
class HL7DataTypes:
    """
    Full definition for the HL7 datatype population.

    This class encapsulates a collection of both simple and complex HL7v2 data types,
    providing methods to load them from XML schema definitions and convert them
    into a dictionary representation.

    Attributes:
        types (Dict[str, Union[HL7SimpleDataType, HL7ComplexDataType]]): A dictionary
                                                                        mapping data
                                                                        type names to
                                                                        their respective
                                                                        HL7SimpleDataType
                                                                        or
                                                                        HL7ComplexDataType
                                                                        instances.
    """

    types: Dict[str, Union[HL7SimpleDataType, HL7ComplexDataType]]

    @classmethod
    def from_xml(cls, xml_content: str) -> "HL7DataTypes":
        """
        Creates an HL7DataTypes instance by parsing XML content containing
        HL7v2 datatype definitions.

        Args:
            xml_content (str): The XML content string defining HL7v2 data types.

        Returns:
            HL7DataTypes: An instance of HL7DataTypes populated with parsed types.
        """
        types = {}
        tree = ET.fromstring(xml_content)
        # parse out simple datatypes first
        for e in tree.iterfind(".//xsd:simpleType", namespaces=_HL7_XML_NAMESPACES):
            # name = e.attrib["name"]
            types[e.attrib["name"]] = HL7SimpleDataType.from_xml(e)

        # now parse out the complex types
        for e in tree.iterfind(".//xsd:complexType", namespaces=_HL7_XML_NAMESPACES):
            # skip the weird ones
            if e.attrib.get("mixed") == "true":
                continue

            # skip the CONTENT ones
            if "CONTENT" in e.attrib.get("name"):
                continue

            types[e.attrib["name"]] = HL7ComplexDataType.from_xml(e, tree)

        return cls(types)

    def to_dict(self) -> dict:
        """
        Converts the collection of HL7 data types into a dictionary representation.

        Each data type name maps to a dict with a "class" ("SIMPLE" or "COMPLEX")
        and its "fields". For example::

            {
                "T": {"class": "SIMPLE", "fields": {}},
                "AD": {"class": "COMPLEX", "fields": {"1": ...}},
            }

        Returns:
            dict: A mapping of data type name to its class and fields.
        """
        ret_dict = {}
        for k, v in self.types.items():
            if isinstance(v, HL7SimpleDataType):
                ret_dict[v.name] = {"class": "SIMPLE", "fields": {}}
            else:
                ret_dict[k] = {"class": "COMPLEX", "fields": v.to_dict()}

        return ret_dict
