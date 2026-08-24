from memoryfield_tool.frontmatter import (
    build_frontmatter,
    get_frontmatter_field,
    parse_frontmatter,
    set_frontmatter_field,
)

VALID = (
    "---\n"
    "title: Carbon Fibre Woks\n"
    "created: '2026-03-01T09:00:00Z'\n"
    "uuid: 6aa615f0-486f-48a7-a210-ba4f5ff18c8b\n"
    "---\n"
    "\n"
    "Carbon fibre woks conduct heat unevenly but...\n"
)


def test_parse_valid():
    fm, has = parse_frontmatter(VALID)
    assert has is True
    assert fm == {
        "title": "Carbon Fibre Woks",
        "created": "2026-03-01T09:00:00Z",
        "uuid": "6aa615f0-486f-48a7-a210-ba4f5ff18c8b",
    }


def test_parse_missing():
    fm, has = parse_frontmatter("# Just a heading\n\nNo frontmatter here.\n")
    assert fm is None
    assert has is False


def test_parse_unclosed_markers():
    fm, has = parse_frontmatter("---\ntitle: never closed\n")
    assert fm is None
    assert has is True


def test_parse_malformed_yaml():
    fm, has = parse_frontmatter("---\ntitle: [unclosed\n---\nbody\n")
    assert fm is None
    assert has is True


def test_parse_non_dict_yaml():
    fm, has = parse_frontmatter("---\n- item1\n- item2\n---\n")
    assert fm == {}
    assert has is True


def test_build_roundtrip_keeps_datetime_as_str():
    fm = {
        "title": "Example",
        "created": "2026-03-01T09:00:00Z",
        "updated": "2026-08-22T14:30:00Z",
    }
    text = build_frontmatter(fm) + "Body here.\n"
    parsed, has = parse_frontmatter(text)
    assert has is True
    assert type(parsed["created"]) is str
    assert type(parsed["updated"]) is str
    assert parsed["created"] == "2026-03-01T09:00:00Z"


def test_build_starts_and_ends_with_markers():
    fm = {"title": "Example"}
    text = build_frontmatter(fm)
    assert text.startswith("---\n")
    assert text.endswith("---\n")


def test_set_insert_into_existing_block():
    result = set_frontmatter_field(VALID, "summary", "A short summary.")
    fm, _ = parse_frontmatter(result)
    assert fm["summary"] == "A short summary."
    assert "title" in fm
    assert result.endswith("Carbon fibre woks conduct heat unevenly but...\n")


def test_set_replace_existing_key():
    result = set_frontmatter_field(VALID, "title", "New Title")
    fm, _ = parse_frontmatter(result)
    assert fm["title"] == "New Title"


def test_set_prepend_when_no_frontmatter():
    text = "# Plain\n\nSome body.\n"
    result = set_frontmatter_field(text, "uuid", "abc-123")
    fm, has = parse_frontmatter(result)
    assert has is True
    assert fm["uuid"] == "abc-123"
    assert result.endswith(text)


def test_get_frontmatter_field():
    assert get_frontmatter_field(VALID, "title") == "Carbon Fibre Woks"
    assert get_frontmatter_field(VALID, "missing") is None
    assert get_frontmatter_field("# no fm\n", "title") is None


def test_unknown_fields_do_not_raise():
    text = "---\ntitle: X\ncustom_field: whatever\nanother: [1, 2]\n---\n"
    fm, has = parse_frontmatter(text)
    assert has is True
    assert fm["custom_field"] == "whatever"
