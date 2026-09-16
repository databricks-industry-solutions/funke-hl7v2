"""
This module defines an enumeration for supported HL7v2 versions.

It provides a structured way to represent different HL7v2 message versions,
which can be used for schema validation, parsing logic, or routing based on version.
"""

from enum import Enum, auto


class HL7Version(Enum):
    """
    Enumeration of supported HL7v2 message versions.

    Each member represents a specific HL7v2 version, allowing for clear
    and type-safe handling of version-dependent logic.
    """

    V2_3 = auto()
    V2_3_1 = auto()
    V2_4 = auto()
    V2_5 = auto()
    V2_5_1 = auto()
    V2_6 = auto()
    V2_7 = auto()
    V2_7_1 = auto()
    V2_8 = auto()
    V2_8_1 = auto()
    V2_8_2 = auto()
    V2_9 = auto()

    @classmethod
    def from_string(cls, version_string: str) -> "HL7Version":
        """
        Converts a string representation of an HL7 version to its corresponding
        HL7Version enum member.

        Args:
            version_string (str): The version string (e.g., "2.3", "2.5.1").

        Returns:
            HL7Version: The corresponding HL7Version enum member.

        Raises:
            KeyError: If the version string does not match any defined HL7Version.
        """
        return cls["V" + version_string.replace(".", "_")]
