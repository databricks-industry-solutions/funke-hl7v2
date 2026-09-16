"""
This module provides classes and utilities for parsing HL7v2 messages.

It includes functionality to break down HL7v2 messages into their constituent
segments, fields, components, repetitions, and subcomponents, handling
separator characters and escape sequences as defined by the HL7v2 standard.
"""

import json

from dataclasses import dataclass
from functools import reduce
from importlib.resources import files


@dataclass
class HL7v2Encoding:
    """
    Represents the encoding characters used in an HL7v2 message.

    These characters define how fields, components, repetitions, escape sequences,
    and subcomponents are delimited within an HL7v2 message.

    Attributes:
        FIELD (str): The field separator character.
        ENCODINGS (str): A string containing the component, repetition, escape,
                         and subcomponent separator characters in order.
    """

    FIELD: str
    ENCODINGS: str

    def __post_init__(self):
        """
        Initializes the individual separator characters and escape sequences
        based on the provided ENCODINGS string.
        """

        if len(self.ENCODINGS) not in (4, 5):
            raise ValueError(f"Invalid message encoding: {self.ENCODINGS}")

        self.COMPONENT = self.ENCODINGS[0]
        self.REPETITION = self.ENCODINGS[1]
        self.ESCAPE = self.ENCODINGS[2]
        self.SUBCOMPONENT = self.ENCODINGS[3]
        self.TRUNCATION = self.ENCODINGS[4] if len(self.ENCODINGS) > 4 else "#"

        self.ESCAPE_SEQUENCES = {
            "\\.br\\": "\r\n",
            "\\F\\": self.FIELD,
            "\\R\\": self.REPETITION,
            "\\S\\": self.COMPONENT,
            "\\T\\": self.SUBCOMPONENT,
            "\\E\\": self.ESCAPE,
            "\\L\\": self.TRUNCATION,
            "\\X0A\\": "\n",
            "\\X0D\\": "\r",
        }


@dataclass
class HL7v2Schema:
    schema: dict = None
    datatypes: dict = None
    schema_path: str = None
    datatypes_path: str = None

    def __post_init__(self):
        self.schema_path = (
            self.schema_path if self.schema_path else self._data_path("schemas.json")
        )

        self.datatypes_path = (
            self.schema_path if self.schema_path else self._data_path("datatypes.json")
        )

        self.schema = self.schema if self.schema else self._read_json(self.schema_path)
        self.datatypes = (
            self.datatypes if self.datatypes else self._read_json(self.datatypes_path)
        )

    def _stringify_list(self, source: list):
        return [str(i) for i in source]

    def _read_json(self, file_path: str):
        with open(file_path, "r") as json_file:
            return json.load(json_file)

    def _data_path(self, file: str):
        return str(files("funke").joinpath("data", file))

    def get_field_type(self, location: list):
        location = self._stringify_list(location)
        return self.schema.get(location[0], {}).get(location[1], {}).get("type", None)

    def get_component_type(self, location: list):
        location = self._stringify_list(location)
        field_type = self.get_field_type(location)
        component_type = (
            self.datatypes.get(field_type, {})
            .get("fields", {})
            .get(location[2], {})
            .get("type", field_type)
        )

        return component_type

    def is_datatype_complex(self, datatype: str):
        return self.datatypes.get(datatype, {}).get("complex", True)

    def is_element_complex(self, location: list):
        location = self._stringify_list(location)

        match len(location):
            case 2:
                return self.is_datatype_complex(self.get_field_type(location))
            case 3:
                return self.is_datatype_complex(self.get_component_type(location))
            case _:
                return True


@dataclass
class HL7v2Msg:
    """
    Represents a parsed HL7v2 message.

    This class takes a raw HL7v2 message string and parses it into a structured
    representation, allowing easy access to segments, fields, and their sub-elements.

    Attributes:
        msg (str): The raw HL7v2 message string.
    """

    msg: str
    schema: HL7v2Schema = None

    def __post_init__(self):
        """
        Parses the HL7v2 message upon initialization.
        """
        self.lines = [l.strip() for l in self.msg.splitlines()]
        self.encoding = self._parse_encodings()
        self.encoding_hierarchy = {
            1: self.encoding.FIELD,
            2: self.encoding.COMPONENT,
            3: self.encoding.SUBCOMPONENT,
        }
        self.segments = self._map_segments()

    def _parse_encodings(self) -> HL7v2Encoding:
        """
        Parses the MSH segment to extract the field and encoding characters.

        Raises:
            ValueError: If the message does not start with an MSH segment.

        Returns:
            HL7v2Encoding: An object containing the parsed separator characters.
        """

        msh = self.lines[0]

        if not msh.startswith("MSH"):
            raise ValueError(f"Invalid message: first segment should be MSH")

        field_separator = msh[3]
        encoding_chars = msh.split(field_separator)[1]

        return HL7v2Encoding(field_separator, encoding_chars)

    def _map_segments(self) -> dict:
        """
        Maps the message lines into a dictionary of segments.

        Each segment is represented as a dictionary containing its index,
        segment name, and parsed fields.

        Returns:
            dict: A dictionary where keys are segment names (e.g., "MSH", "PID")
                  and values are lists of dictionaries, each representing an
                  occurrence of that segment in the message.
        """
        segments = [
            {
                "index": index,
                "segment": (segment := line.split(self.encoding.FIELD)[0]),
                "fields": self._map_element(line, [segment]),
            }
            for index, line in enumerate(self.lines)
        ]

        segment_set = set([s["segment"] for s in segments])

        mapped_segments = {
            s: [i for i in segments if i["segment"] == s] for s in segment_set
        }

        mapped_segments["MSH"][0]["fields"][2] = [{1: {1: self.encoding.ENCODINGS}}]

        return mapped_segments

    def _map_element(self, element: str, location: list) -> dict | str:
        """
        Recursively parses and maps HL7v2 elements down to the subcomponent level.


        Args:
            element (str): The string content of the element to parse.
            location (list): A list representing the hierarchical path
                                     to the current element (e.g., ["MSH", 1, 2]
                                     for MSH-1-2).

        Returns:
            dict | str: A dictionary representing the parsed sub-elements, or
                        a string if the element is a leaf (subcomponent).
        """

        if (depth := len(location)) < 4:
            separator = self.encoding_hierarchy[depth]

            try:
                parts = self._split_element(element, location, separator)
            except:
                raise ValueError(element, location, separator)

            if depth == 1:
                parts = parts[1:]

                if location[0] == "MSH":
                    parts = [self.encoding.FIELD] + parts

            return {
                (k := i + 1): self._map_parts(p, location + [k])
                for i, p in enumerate(parts)
            }

        else:

            return self._replace_escapes(element)

    def _split_element(self, element: str, location: list, separator: str):
        """
        Splits element if datatype is complex.

        Args:
            element (str): The string of the element to split.
            location (list): A list representing the hierarchical path
                                     to the current element (e.g., ["MSH", 1, 2]
                                     for MSH-1-2).
            separator (str): The separator character to split the element on.

        Returns:
        """

        split = self.schema.is_element_complex(location) if self.schema else True
        return element.split(separator) if split else [element]

    def _map_parts(self, part: str, location: list):
        """
        Helper that recursively maps parts of an element.

        Args:
            part (str): The string of the element part to map.
            location (list): A list representing the hierarchical path
                            to the current element (e.g., ["MSH", 1, 2]
                            for MSH-1-2).

        Returns:
            str: The string with the escape sequences replaced.
        """

        if len(location) == 2:
            field_reps = part.split(self.encoding.REPETITION)
            return [self._map_element(f, location) for f in field_reps]
        else:
            return self._map_element(part, location)

    def _replace_escapes(self, text: str) -> str:
        """
        Replaces HL7v2 escape sequences with their corresponding characters.

        Args:
            text (str): The string to replace the escape sequences in.

        Returns:
            str: The string with the escape sequences replaced.
        """

        return reduce(
            lambda t, e: t.replace(e[0], e[1]),
            self.encoding.ESCAPE_SEQUENCES.items(),
            text,
        )
