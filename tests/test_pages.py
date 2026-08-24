import pytest

from memoryfield_tool.pages import collect_all_files, collect_pages, is_page_filename


@pytest.mark.parametrize(
    "name",
    [
        "carbon-fibre.md",
        "alpha.md",
        "a.md",
        "0.md",
        "page-123-x.md",
    ],
)
def test_valid_page_filenames(name):
    assert is_page_filename(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "UPPER.md",
        "with space.md",
        "_under.md",
        ".hidden.md",
        "trailing-.md",
        "noext",
        "with.dot.md",
        "",
    ],
)
def test_invalid_page_filenames(name):
    assert is_page_filename(name) is False


def test_collect_pages_root_md_only(field_dir):
    (field_dir / "listing.md").write_text("catalogue\n", encoding="utf-8")
    (field_dir / "subdir").mkdir()
    (field_dir / "subdir" / "nested.md").write_text("nested\n", encoding="utf-8")
    (field_dir / "notes.txt").write_text("not a page\n", encoding="utf-8")
    (field_dir / "photo.png").write_bytes(b"\x89PNG")

    pages = collect_pages(field_dir)
    names = [p.name for p in pages]
    assert names == ["alpha.md", "beta.md", "gamma.md", "index.md", "listing.md"]
    assert "nested.md" not in names
    assert "notes.txt" not in names
    assert "photo.png" not in names


def test_collect_pages_sorted(field_dir):
    pages = collect_pages(field_dir)
    assert [p.name for p in pages] == ["alpha.md", "beta.md", "gamma.md", "index.md"]


def test_collect_all_files(field_dir):
    (field_dir / "subdir").mkdir()
    (field_dir / "subdir" / "nested.md").write_text("nested\n", encoding="utf-8")
    (field_dir / "image.png").write_bytes(b"\x89PNG")
    (field_dir / "editor~").write_text("debris\n", encoding="utf-8")

    names = [p.name for p in collect_all_files(field_dir)]
    assert "alpha.md" in names
    assert "index.md" in names
    assert "nested.md" in names
    assert "image.png" in names
    assert "editor~" in names
