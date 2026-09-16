"""
This module defines XML namespaces used in HL7v2 schema definitions.

These namespaces are crucial for correctly parsing and interpreting XML-based
HL7v2 schema files, ensuring that elements and attributes are identified
within their proper contexts.
"""

_HL7_XML_NAMESPACES = {
    "xsd": "http://www.w3.org/2001/XMLSchema",
    "hl7": "urn:hl7-org:v2xml",
}
