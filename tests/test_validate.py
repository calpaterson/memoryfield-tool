from memoryfield_tool import transport, validate


def _levels(issues):
    return [(i.level, i.filename) for i in issues]


def test_valid_field_no_issues(field_dir):
    assert validate.validate_field(transport.local(field_dir)) == []


def test_empty_field_error(tmp_path):
    field = tmp_path / "empty"
    field.mkdir()
    issues = validate.validate_field(transport.local(field))
    assert any(i.level == "error" and i.message == "field contains no pages" for i in issues)


def test_subdir_md_files_not_flagged(field_dir):
    sub = field_dir / "subdir"
    sub.mkdir()
    (sub / "nested.md").write_text("nested\n", encoding="utf-8")
    (sub / "conflict.sync-conflict-2026.md").write_text("nested\n", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert all(
        i.filename not in ("subdir/nested.md", "subdir/conflict.sync-conflict-2026.md")
        for i in issues
    )


def test_bad_filename_error(field_dir):
    (field_dir / "Bad_Name.md").write_text("bad\n", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert any(i.level == "error" and i.filename == "Bad_Name.md" for i in issues)


def test_invalid_utf8_error(field_dir):
    (field_dir / "binary.md").write_bytes(b"\xff\xfe\x00\x01\x02")
    issues = validate.validate_field(transport.local(field_dir))
    assert any(i.level == "error" and i.filename == "binary.md" for i in issues)


def test_broken_yaml_error(field_dir):
    (field_dir / "badfm.md").write_text("---\ntitle: [unclosed\n---\n", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert any(
        i.level == "error" and i.filename == "badfm.md" and "frontmatter" in i.message
        for i in issues
    )


def test_oversized_warning(field_dir):
    (field_dir / "big.md").write_text("---\ntitle: Big\n---\n\n" + "x" * 9000, encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert any(
        i.level == "warning" and i.filename == "big.md" and "8192" in i.message for i in issues
    )


def test_missing_recommended_fields_warning(field_dir):
    (field_dir / "partial.md").write_text("---\ntitle: Only Title\n---\n\nbody\n", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    matches = [i for i in issues if i.filename == "partial.md" and i.level == "warning"]
    assert len(matches) == 1
    for field in ("uuid", "created", "updated"):
        assert field in matches[0].message


def test_long_summary_warning(field_dir):
    (field_dir / "summary.md").write_text(
        "---\ntitle: S\nsummary: " + "y" * 1100 + "\n---\n\nbody\n", encoding="utf-8"
    )
    issues = validate.validate_field(transport.local(field_dir))
    assert any(
        i.level == "warning" and i.filename == "summary.md" and "max 1000" in i.message
        for i in issues
    )


def test_medium_summary_no_warning(field_dir):
    (field_dir / "summary.md").write_text(
        "---\ntitle: S\nsummary: " + "y" * 500 + "\n---\n\nbody\n", encoding="utf-8"
    )
    issues = validate.validate_field(transport.local(field_dir))
    assert all("summary too long" not in i.message for i in issues)


def test_wrong_named_sqlite3_error(field_dir):
    (field_dir / "wrong-name.sqlite3").write_bytes(b"sqlite")
    issues = validate.validate_field(transport.local(field_dir))
    assert any(i.level == "error" and i.filename == "wrong-name.sqlite3" for i in issues)


def test_asset_files_never_flagged(field_dir):
    (field_dir / "photo.png").write_bytes(b"\x89PNG\r\n")
    (field_dir / "video.mp4").write_bytes(b"frag")
    issues = validate.validate_field(transport.local(field_dir))
    assert all(i.filename not in ("photo.png", "video.mp4") for i in issues)


def test_non_md_files_not_pages(field_dir):
    (field_dir / ".DS_Store").write_text("junk", encoding="utf-8")
    (field_dir / "foo.md~").write_text("junk", encoding="utf-8")
    (field_dir / "desktop.ini").write_text("junk", encoding="utf-8")
    (field_dir / "Thumbs.db").write_text("junk", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert all(
        i.filename not in (".DS_Store", "foo.md~", "desktop.ini", "Thumbs.db") for i in issues
    )


def test_sync_conflict_md_treated_as_page(field_dir):
    (field_dir / "sync.sync-conflict-2026-08-24.md").write_text("junk", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert any(
        i.filename == "sync.sync-conflict-2026-08-24.md" and i.level == "error" for i in issues
    )


def test_broken_internal_link_warning(field_dir):
    (field_dir / "links.md").write_text(
        "---\ntitle: Links\n---\n\n[ok](beta.md) and [broken](/does-not-exist.md)\n",
        encoding="utf-8",
    )
    issues = validate.validate_field(transport.local(field_dir))
    broken = [i for i in issues if i.filename == "links.md" and "broken link" in i.message]
    assert len(broken) == 1
    assert "/does-not-exist.md" in broken[0].message


def test_external_links_not_flagged(field_dir):
    body = "[example](https://example.com) [rel](//cdn.example/x) [id](#anchor)\n"
    (field_dir / "ext.md").write_text(f"---\ntitle: Ext\n---\n\n{body}", encoding="utf-8")
    issues = validate.validate_field(transport.local(field_dir))
    assert all("broken link" not in i.message for i in issues)


def test_unquoted_datetime_error(field_dir):
    (field_dir / "unquoted.md").write_text(
        "---\ntitle: U\ncreated: 2026-03-01\nupdated: 2026-03-02 14:30:00\n---\n\nbody\n",
        encoding="utf-8",
    )
    issues = validate.validate_field(transport.local(field_dir))
    created = [i for i in issues if i.filename == "unquoted.md" and "created" in i.message]
    updated = [i for i in issues if i.filename == "unquoted.md" and "updated" in i.message]
    assert len(created) == 1
    assert created[0].level == "error"
    assert len(updated) == 1
    assert updated[0].level == "error"
