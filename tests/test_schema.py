import json

import pytest

from funke.schema import *


def test_parse_datatypes():
    # temp hardcoding of path, use V2.8 for testing
    xml_content = """
    <xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="urn:hl7-org:v2xml" xmlns:hl7="urn:hl7-org:v2xml" targetNamespace="urn:hl7-org:v2xml" version="1.1">
        <!-- COMPLEX -->
        <xsd:complexType name="SOME_DATA_TYPE">
            <xsd:sequence>
              <xsd:element ref="SOME_DATA_TYPE.1" minOccurs="0" maxOccurs="1" />
              <xsd:element ref="SOME_DATA_TYPE.2" minOccurs="0" maxOccurs="1" />
              <xsd:element ref="SOME_DATA_TYPE.3" minOccurs="0" maxOccurs="1" />
            </xsd:sequence>
        </xsd:complexType>

        <xsd:attributeGroup name="SOME_DATA_TYPE.1.ATTRIBUTES">
            <xsd:attribute name="Type" type="xsd:string" fixed="ST" />
            <xsd:attribute name="LongName" type="xsd:string" fixed="Some field description" />
            <xsd:attribute name="confLength" type="xsd:integer" fixed="30" />
            <xsd:attribute name="truncation" type="xsd:string" fixed="#" />
        </xsd:attributeGroup>

        <xsd:attributeGroup name="SOME_DATA_TYPE.2.ATTRIBUTES">
            <xsd:attribute name="Type" type="xsd:string" fixed="LN" />
            <xsd:attribute name="LongName" type="xsd:string" fixed="Some field description, but different" />
            <xsd:attribute name="confLength" type="xsd:integer" fixed="30" />
            <xsd:attribute name="truncation" type="xsd:string" fixed="#" />
        </xsd:attributeGroup>

        <xsd:attributeGroup name="SOME_DATA_TYPE.3.ATTRIBUTES">
            <xsd:attribute name="Type" type="xsd:string" fixed="IQ" />
            <xsd:attribute name="LongName" type="xsd:string" fixed="Some field description, but even more differenter" />
            <xsd:attribute name="confLength" type="xsd:integer" fixed="30" />
            <xsd:attribute name="truncation" type="xsd:string" fixed="#" />
        </xsd:attributeGroup>

        <!-- SIMPLE -->
        <xsd:simpleType name="ST">
            <xsd:restriction base="xsd:string" />
        </xsd:simpleType>
        <xsd:simpleType name="LN">
            <xsd:restriction base="xsd:string" />
        </xsd:simpleType>
        <xsd:simpleType name="IQ">
            <xsd:restriction base="xsd:string" />
        </xsd:simpleType>
    </xsd:schema>
    """
    parsed = HL7DataTypes.from_xml(xml_content).to_dict()

    print(parsed)

    # simple types are top-level keys marked SIMPLE with no fields
    assert parsed["ST"]["class"] == "SIMPLE"
    assert parsed["LN"]["class"] == "SIMPLE"
    assert parsed["IQ"]["class"] == "SIMPLE"

    # complex types carry their component fields, keyed by position
    assert parsed["SOME_DATA_TYPE"]["class"] == "COMPLEX"
    assert parsed["SOME_DATA_TYPE"]["fields"][2]["type"] == "LN"


def test_parse_fields():
    fields_def_path = "./data/hl7-schemas/HL7-xml-v2.8/fields.xsd"
    xml_content = ""
    with open(fields_def_path, "r") as f:
        xml_content = f.read()

    xml_content = """
    <xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="urn:hl7-org:v2xml" xmlns:hl7="urn:hl7-org:v2xml" targetNamespace="urn:hl7-org:v2xml" version="1.1">
        <xsd:attributeGroup name="SOME_SEGMENT.1.ATTRIBUTES">
            <xsd:attribute name="Item" type="xsd:string" fixed="987654321" />
            <xsd:attribute name="Type" type="xsd:string" fixed="XCN" />
            <xsd:attribute name="Table" type="xsd:string" fixed="ATABLENAME_0091" />
            <xsd:attribute name="LongName" type="xsd:string" fixed="A description that tells you something" />
        </xsd:attributeGroup>
    </xsd:schema>
    """

    parsed = HL7MessageSchema.from_xml(xml_content).to_dict()
    print(parsed)
    assert parsed["SOME_SEGMENT"][1] == {
        "longName": "A description that tells you something",
        "type": "XCN",
    }


def test_version_from_string():
    vstring = "2.3"
    version = HL7Version.from_string(vstring)
    print(version)
    assert version == HL7Version.V2_3

    vstring = "2.8.2"
    version = HL7Version.from_string(vstring)
    print(version)
    assert version == HL7Version.V2_8_2

    # invalid version number
    with pytest.raises(KeyError):
        vstring = "2.10"
        version = HL7Version.from_string(vstring)
        print(version)
