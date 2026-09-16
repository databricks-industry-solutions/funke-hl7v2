"""
The 'funke.schema' package defines the structure and validation rules for HL7v2 messages.

It provides classes and utilities to represent HL7v2 data types, message versions,
and the overall schema of HL7v2 messages, enabling structured processing and validation.
"""

from .datatypes import HL7DataTypes
from .version import HL7Version
from .message import HL7MessageSchema
