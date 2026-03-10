"""tests/test_dumper_members.py

Unit tests for struct field parsing via castxml ``members`` attribute.
Covers the fallback path added in PR #63 where castxml serialises Field
elements as space-separated IDs in the ``members`` attribute of a Struct
instead of as inline child elements.
"""
import pytest
from xml.etree.ElementTree import fromstring
from abicheck.dumper import _CastxmlParser


def _make_parser(xml_str: str, exported: set[str] | None = None) -> _CastxmlParser:
    root = fromstring(xml_str)
    return _CastxmlParser(root, exported or set(), exported or set())


# ---------------------------------------------------------------------------
# Inline children (classic format) — must continue to work
# ---------------------------------------------------------------------------
INLINE_XML = """<?xml version="1.0"?>
<CastXML>
  <Struct id="_2" name="Rect" context="_1" file="f1" line="1" size="128" align="32">
    <Field id="_4" name="width"  type="_6" offset="0"/>
    <Field id="_5" name="height" type="_6" offset="32"/>
    <Field id="_6" name="depth"  type="_7" offset="64"/>
  </Struct>
  <FundamentalType id="_6" name="int" size="32"/>
  <FundamentalType id="_7" name="float" size="32"/>
  <Namespace id="_1" name="::"/>
  <File id="f1" name="test.h"/>
</CastXML>"""


def test_parse_fields_inline_children():
    p = _make_parser(INLINE_XML)
    types = p.parse_types()
    assert len(types) == 1
    assert types[0].name == "Rect"
    fields = types[0].fields
    assert len(fields) == 3
    assert fields[0].name == "width"
    assert fields[1].name == "height"
    assert fields[2].name == "depth"


# ---------------------------------------------------------------------------
# Members attribute (castxml --castxml-output=1 format) — new fallback path
# ---------------------------------------------------------------------------
MEMBERS_XML = """<?xml version="1.0"?>
<CastXML>
  <Struct id="_2" name="Point" context="_1" file="f1" line="1"
          members="_4 _5" size="64" align="32"/>
  <Field id="_4" name="x" type="_6" offset="0"  context="_2"/>
  <Field id="_5" name="y" type="_6" offset="32" context="_2"/>
  <FundamentalType id="_6" name="int" size="32"/>
  <Namespace id="_1" name="::"/>
  <File id="f1" name="test.h"/>
</CastXML>"""


def test_parse_fields_via_members_attribute():
    """Fields referenced through members= must be resolved via id_map."""
    p = _make_parser(MEMBERS_XML)
    types = p.parse_types()
    assert len(types) == 1
    t = types[0]
    assert t.name == "Point"
    assert len(t.fields) == 2
    assert t.fields[0].name == "x"
    assert t.fields[0].offset_bits == 0
    assert t.fields[1].name == "y"
    assert t.fields[1].offset_bits == 32


MEMBERS_CONST_XML = """<?xml version="1.0"?>
<CastXML>
  <Struct id="_2" name="SensorConfig" context="_1" file="f1" line="1"
          members="_4 _5 _6" size="96" align="32"/>
  <Field id="_4" name="sample_rate" type="_10" offset="0"  context="_2"/>
  <Field id="_5" name="raw_value"   type="_11" offset="32" context="_2"/>
  <Field id="_6" name="cache_hits"  type="_7"  offset="64" context="_2"/>
  <CvQualifiedType id="_10" type="_7" const="1"/>
  <FundamentalType id="_7" name="int" size="32"/>
  <FundamentalType id="_11" name="int" size="32"/>
  <Namespace id="_1" name="::"/>
  <File id="f1" name="test.h"/>
</CastXML>"""


def test_parse_fields_with_cv_qualified_type():
    """const-qualified fields are correctly typed when resolved via members=."""
    p = _make_parser(MEMBERS_CONST_XML)
    types = p.parse_types()
    assert len(types) == 1
    fields = types[0].fields
    assert len(fields) == 3
    assert "const" in fields[0].type.lower()   # sample_rate → const int
    assert fields[1].type == "int"              # raw_value
    assert fields[2].type == "int"              # cache_hits


def test_members_attribute_skips_non_field_ids():
    """Non-Field IDs referenced in members= must be silently ignored."""
    xml = """<?xml version="1.0"?>
<CastXML>
  <Struct id="_2" name="Mixed" context="_1" file="f1" line="1"
          members="_3 _4 _5" size="32" align="32"/>
  <Method id="_3" name="doIt" returns="_7" context="_2"/>
  <Field id="_4" name="value" type="_7" offset="0" context="_2"/>
  <Destructor id="_5" name="~Mixed" context="_2"/>
  <FundamentalType id="_7" name="int" size="32"/>
  <Namespace id="_1" name="::"/>
  <File id="f1" name="test.h"/>
</CastXML>"""
    p = _make_parser(xml)
    types = p.parse_types()
    assert len(types) == 1
    assert len(types[0].fields) == 1
    assert types[0].fields[0].name == "value"


def test_empty_members_attribute_yields_empty_fields():
    """Struct with empty members= attribute should have no fields."""
    xml = """<?xml version="1.0"?>
<CastXML>
  <Struct id="_2" name="Empty" context="_1" file="f1" line="1"
          members="" size="0" align="8"/>
  <Namespace id="_1" name="::"/>
  <File id="f1" name="test.h"/>
</CastXML>"""
    p = _make_parser(xml)
    types = p.parse_types()
    assert len(types) == 1
    assert types[0].fields == []
