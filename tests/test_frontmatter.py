from memoryfield_tool.frontmatter import (
    build_frontmatter,
    fill_frontmatter,
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


def test_fill_bare_body_prepends_block():
    result = fill_frontmatter(
        "plain body\n",
        title="My Page",
        uuid="u-1",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
    )
    fm, has = parse_frontmatter(result)
    assert has is True
    assert fm == {
        "uuid": "u-1",
        "created": "2026-01-01T00:00:00Z",
        "updated": "2026-01-02T00:00:00Z",
        "title": "My Page",
    }
    assert "summary" not in fm
    assert result.endswith("plain body\n")


def test_fill_partial_block_fills_gaps():
    text = "---\ntitle: X\n---\n\nbody\n"
    result = fill_frontmatter(text, title="Ignored", uuid="u-1", created="c-1", updated="u-2")
    fm, _ = parse_frontmatter(result)
    assert fm["title"] == "X"
    assert fm["uuid"] == "u-1"
    assert fm["created"] == "c-1"
    assert fm["updated"] == "u-2"


def test_fill_malformed_yaml_untouched():
    text = "---\ntitle: [unclosed\n---\nbody\n"
    assert fill_frontmatter(text, uuid="u-1") == text


def test_fill_unclosed_markers_untouched():
    text = "---\ntitle: never closed\n"
    assert fill_frontmatter(text, uuid="u-1") == text


def test_fill_no_summary_without_source():
    result = fill_frontmatter("body\n", uuid="u-1")
    fm, _ = parse_frontmatter(result)
    assert "summary" not in fm


def test_fill_summary_flag_adds_summary():
    text = "---\nuuid: u-1\ncreated: c-1\nupdated: u-2\ntitle: T\n---\n\nbody\n"
    result = fill_frontmatter(text, summary="A summary.")
    fm, _ = parse_frontmatter(result)
    assert fm["summary"] == "A summary."


def test_fill_preserve_fills_all_keys():
    preserve = {
        "uuid": "stored-uuid",
        "created": "stored-created",
        "updated": "stored-updated",
        "title": "Stored Title",
        "summary": "Stored summary.",
    }
    result = fill_frontmatter("body\n", preserve=preserve)
    fm, _ = parse_frontmatter(result)
    assert fm == preserve


def test_fill_explicit_flag_beats_preserve():
    preserve = {"title": "Stored", "summary": "Stored summary."}
    result = fill_frontmatter(
        "body\n", title="Flag Title", summary="Flag summary.", preserve=preserve
    )
    fm, _ = parse_frontmatter(result)
    assert fm["title"] == "Flag Title"
    assert fm["summary"] == "Flag summary."


def test_fill_stored_beats_generated():
    preserve = {"uuid": "stored-uuid", "created": "stored-created", "updated": "stored-updated"}
    result = fill_frontmatter(
        "body\n",
        preserve=preserve,
        uuid="fresh-uuid",
        created="fresh-created",
        updated="fresh-updated",
    )
    fm, _ = parse_frontmatter(result)
    assert fm["uuid"] == "stored-uuid"
    assert fm["created"] == "stored-created"
    assert fm["updated"] == "stored-updated"


def test_fill_title_fallback_only_when_all_else_missing():
    preserve = {"title": "Stored"}
    result = fill_frontmatter("body\n", title_fallback="Fallback", preserve=preserve)
    fm, _ = parse_frontmatter(result)
    assert fm["title"] == "Stored"

    result = fill_frontmatter("body\n", title_fallback="Fallback")
    fm, _ = parse_frontmatter(result)
    assert fm["title"] == "Fallback"


def test_fill_complete_block_byte_identical():
    text = "---\ntitle: T\nuuid: u-1\ncreated: c-1\nupdated: u-2\n---\n\nbody\n"
    assert fill_frontmatter(text) == text


def test_fill_explicit_generated_used_when_missing():
    result = fill_frontmatter(
        "body\n", uuid="gen-uuid", created="gen-created", updated="gen-updated"
    )
    fm, _ = parse_frontmatter(result)
    assert fm["uuid"] == "gen-uuid"
    assert fm["created"] == "gen-created"
    assert fm["updated"] == "gen-updated"
