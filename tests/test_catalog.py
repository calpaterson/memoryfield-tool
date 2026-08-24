from memoryfield_tool import catalog, transport


def test_catalog_field_extracts_frontmatter(field_dir):
    rows = catalog.catalog_field(transport.local(field_dir))
    names = [r["filename"] for r in rows]
    assert names == ["alpha.md", "beta.md", "gamma.md", "index.md"]

    alpha = rows[0]
    assert alpha["title"] == "Alpha Notes"
    assert alpha["summary"] == "Notes about alpha things."
    assert alpha["created"] == "2026-01-01T09:00:00Z"
    assert alpha["updated"] == "2026-01-02T09:00:00Z"
    assert "field" not in alpha


def test_catalog_field_field_key_present_when_named(field_dir):
    rows = catalog.catalog_field(transport.local(field_dir), field_name="notes")
    assert all(r["field"] == "notes" for r in rows)


def test_catalog_field_no_frontmatter(field_dir):
    (field_dir / "plain.md").write_text("# Just a heading\n", encoding="utf-8")
    rows = catalog.catalog_field(transport.local(field_dir))
    plain = next(r for r in rows if r["filename"] == "plain.md")
    assert plain["title"] == ""
    assert plain["summary"] == ""


def _row(filename, title="", created="", updated=""):
    return {
        "filename": filename,
        "title": title,
        "summary": "s",
        "created": created,
        "updated": updated,
        "field": "notes",
    }


def test_catalog_sort_path():
    rows = [_row("beta.md"), _row("alpha.md"), _row("gamma.md")]
    sorted_rows = catalog.catalog_sort(rows, "path")
    assert [r["filename"] for r in sorted_rows] == ["alpha.md", "beta.md", "gamma.md"]


def test_catalog_sort_title_case_insensitive():
    rows = [_row("a.md", title="Zulu"), _row("b.md", title="alpha")]
    sorted_rows = catalog.catalog_sort(rows, "title")
    assert [r["filename"] for r in sorted_rows] == ["b.md", "a.md"]


def test_catalog_sort_created_descending():
    rows = [
        _row("old.md", created="2026-01-01T00:00:00Z"),
        _row("new.md", created="2026-02-01T00:00:00Z"),
    ]
    sorted_rows = catalog.catalog_sort(rows, "created")
    assert [r["filename"] for r in sorted_rows] == ["new.md", "old.md"]


def test_catalog_sort_updated_descending():
    rows = [
        _row("old.md", updated="2026-01-01T00:00:00Z"),
        _row("new.md", updated="2026-02-01T00:00:00Z"),
    ]
    sorted_rows = catalog.catalog_sort(rows, "updated")
    assert [r["filename"] for r in sorted_rows] == ["new.md", "old.md"]


def test_catalog_markdown_no_field_column():
    rows = [_row("alpha.md", title="Alpha")]
    md = catalog.catalog_markdown(rows)
    assert md.splitlines()[0] == "| Page | Summary |"
    assert "| Field |" not in md


def test_catalog_markdown_with_field_column():
    rows = [_row("alpha.md", title="Alpha")]
    md = catalog.catalog_markdown(rows, show_field=True)
    lines = md.splitlines()
    assert lines[0] == "| Field | Page | Summary |"
    assert lines[2] == "| notes | alpha.md | s |"


def test_catalog_markdown_summary_truncated():
    rows = [_row("alpha.md", title="Alpha", created="") for _ in range(1)]
    rows[0]["summary"] = "y" * 200
    md = catalog.catalog_markdown(rows)
    assert "..." in md
    assert "y" * 160 not in md
