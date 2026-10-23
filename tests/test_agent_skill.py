"""Checks for the agent skill in .agents/skills/funke-hl7v2.

The skill documents field positions and pitfalls for funke's parsed output. These
tests parse the bundled sample messages and assert the positions the skill relies on,
so a change to the parser or the samples shows up here instead of in an agent's answer.
They also check that the skill folder follows the Agent Skills specification.
"""

import re
from pathlib import Path

import pytest

from funke.parsing.hl7 import HL7v2Msg, HL7v2Schema

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / ".agents" / "skills" / "funke-hl7v2"
SAMPLES = REPO / "data" / "hl7-samples"
ALLOWED_FRONTMATTER = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
}


@pytest.fixture(scope="module")
def schema():
    return HL7v2Schema()


def parse(name: str, schema: HL7v2Schema) -> dict:
    raw = (SAMPLES / name).read_text(encoding="utf-8")
    return HL7v2Msg(raw.lstrip(), schema).segments


def value(segment: dict, field: int, component: int = 1, subcomponent: int = 1):
    """First repetition of a field, as the skill's SQL reads it: fields[f][0][c][s]."""
    return segment["fields"][field][0][component][subcomponent]


def frontmatter() -> dict:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must start with YAML frontmatter"
    keys = {}
    for line in match.group(1).splitlines():
        top = re.match(r"^([a-z-]+):\s*(.*)$", line)
        if top:
            keys[top.group(1)] = top.group(2)
    return keys


def test_frontmatter_follows_agent_skills_spec():
    keys = frontmatter()
    assert set(keys) <= ALLOWED_FRONTMATTER, set(keys) - ALLOWED_FRONTMATTER
    assert keys["name"] == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", keys["name"])
    assert 0 < len(keys["description"]) <= 1024


def test_referenced_files_exist():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"`(references/[a-z0-9-]+\.md)`", text))
    assert refs, "SKILL.md should point to its reference files"
    for ref in refs:
        assert (SKILL_DIR / ref).is_file(), ref


def test_claude_code_link_points_at_the_skill():
    link = REPO / ".claude" / "skills" / "funke-hl7v2"
    assert link.is_symlink()
    assert (link / "SKILL.md").resolve() == (SKILL_DIR / "SKILL.md").resolve()


def test_adt_positions(schema):
    m = parse("ADT_A01 - 1.txt", schema)
    assert value(m["MSH"][0], 9, 1) == "ADT"
    assert value(m["MSH"][0], 9, 2) == "A01"
    assert value(m["PID"][0], 3, 1) == "PATID1234"
    assert value(m["PID"][0], 5, 1) == "EVERYMAN"
    assert value(m["PID"][0], 5, 2) == "ADAM"


def test_pid3_repeats_with_identifier_type(schema):
    m = parse("ADT_A01 - 1.txt", schema)
    ids = m["PID"][0]["fields"][3]
    assert len(ids) > 1
    assert [r[1][1] for r in ids if r[5][1] == "MR"][0] == "PATID1234"


def test_oru_obx_repeats(schema):
    m = parse("ORU_R01 - 1.txt", schema)
    obx = m["OBX"]
    assert len(obx) > 1
    assert (value(obx[0], 3), value(obx[0], 5), value(obx[0], 6)) == (
        "HR",
        "68",
        "/min",
    )
    assert value(obx[0], 11) == "R"
    obr_index = m["OBR"][0]["index"]
    assert all(o["index"] > obr_index for o in obx)


def test_vxu_rxa_positions(schema):
    m = parse("Sample VXU Multiple Admin Message.txt", schema)
    rxa = m["RXA"][0]
    assert value(rxa, 5, 1) == "49281-0215-88"
    assert value(rxa, 5, 3) == "NDC"
    assert (value(rxa, 6), value(rxa, 7)) == ("0.5", "mL")
    assert len(m["RXA"]) > 1


def test_mdm_note_text_is_unescaped(schema):
    m = parse("Sample MDM Message 20240304.txt", schema)
    assert value(m["TXA"][0], 2) == "HP"
    text = "\n".join(value(o, 5) for o in sorted(m["OBX"], key=lambda o: o["index"]))
    assert "\r\n" in text and "\\.br\\" not in text


def test_orders_and_appointments(schema):
    oml = parse("OML_Basic-NG-ExampleMessage.txt", schema)
    assert value(oml["ORC"][0], 1) == "NW"
    assert value(oml["OBR"][0], 4, 2) == "Hepatitis A B C Panel"
    siu = parse("SIU-S12 New Appointment.txt", schema)
    assert value(siu["SCH"][0], 1) == "1209"
    assert value(siu["AIP"][0], 3, 2) == "Pullen"


STRIP = r"^[\x0b\x1c\s]+|[\x0b\x1c\s]+$"  # same pattern as the skill's regexp_replace


def test_mllp_framing_needs_strip(schema):
    with open(
        SAMPLES / "Sample MDM_T02 Message.txt", encoding="utf-8", newline=""
    ) as f:
        raw = f.read()
    assert raw.startswith("\x0b") and raw.rstrip("\r").endswith("\x1c")
    with pytest.raises(ValueError):
        HL7v2Msg(raw, schema)
    m = HL7v2Msg(re.sub(STRIP, "", raw), schema).segments
    assert value(m["MSH"][0], 9, 2) == "T02"


def test_trailing_framing_byte_adds_empty_segment(schema):
    raw = (SAMPLES / "ORU_R01 - 1.txt").read_text(encoding="utf-8")
    assert "" in HL7v2Msg(raw, schema).segments
    assert "" not in HL7v2Msg(re.sub(STRIP, "", raw), schema).segments


def test_batch_file_needs_split(schema):
    raw = (SAMPLES / "WIR IIS Batch HL7 2.5.1 R1.3 Multiple Example.txt").read_text(
        encoding="utf-8"
    )
    assert raw.startswith("FHS|")
    with pytest.raises(ValueError):
        HL7v2Msg(raw, schema)
    normalized = re.sub(r"\r\n?|\n", "\r", re.sub(STRIP, "", raw))
    pieces = [p for p in re.split(r"\r(?=MSH\|)", normalized) if p.startswith("MSH|")]
    pieces = [re.sub(r"\r(BTS|FTS)\|[^\r]*", "", p) for p in pieces]
    assert pieces
    for piece in pieces:
        m = HL7v2Msg(piece, schema).segments
        assert value(m["MSH"][0], 9, 1) == "VXU"
        assert not {"FHS", "BHS", "BTS", "FTS"} & set(m)


def test_concatenated_messages_merge_silently(schema):
    one = (SAMPLES / "ADT_A01 - 1.txt").read_text(encoding="utf-8").strip()
    two = (SAMPLES / "ADT_A01 - 2.txt").read_text(encoding="utf-8").strip()
    merged = HL7v2Msg(one + "\r" + two, schema).segments
    assert len(merged["MSH"]) == 2 and len(merged["PID"]) == 2
    normalized = re.sub(r"\r\n?|\n", "\r", one + "\r" + two)
    pieces = [p for p in re.split(r"\r(?=MSH\|)", normalized) if p.startswith("MSH|")]
    assert [len(HL7v2Msg(p, schema).segments["MSH"]) for p in pieces] == [1, 1]


def test_obx5_can_repeat(schema):
    m = parse("MDM plain text with line breaks.txt", schema)
    assert max(len(o["fields"][5]) for o in m["OBX"]) > 1


def test_nearest_preceding_parent_by_index(schema):
    m = parse("OML_multiOBR-GU_PRU-ExampleMessage.txt", schema)
    for obr in m["OBR"]:
        orcs = [c for c in m["ORC"] if c["index"] < obr["index"]]
        assert orcs, "every OBR in the sample follows an ORC"
