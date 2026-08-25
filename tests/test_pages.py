import re
from datetime import datetime

import pytest

from memoryfield_tool import frontmatter, transport
from memoryfield_tool.pages import (
    EmptyBody,
    FileExists,
    InvalidFilename,
    InvalidUtf8,
    UuidConflict,
    collect_all_files,
    collect_pages,
    is_page_filename,
    page_infos,
    slugify_title,
    write_page,
)


@pytest.mark.parametrize(
    "title,slug",
    [
        ("Carbon Fibre Woks", "carbon-fibre-woks"),
        ("  Leading/trailing  ", "leading-trailing"),
        ("One Piece (2026)", "one-piece-2026"),
        ("Päivänkaari 7", "paivankaari-7"),
        ("!!!", ""),
    ],
)
def test_slugify_title(title, slug):
    assert slugify_title(title) == slug


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

    names = collect_pages(transport.local(field_dir))
    assert names == ["alpha.md", "beta.md", "gamma.md", "index.md", "listing.md"]
    assert "nested.md" not in names
    assert "notes.txt" not in names
    assert "photo.png" not in names


def test_collect_pages_sorted(field_dir):
    pages = collect_pages(transport.local(field_dir))
    assert pages == ["alpha.md", "beta.md", "gamma.md", "index.md"]


def test_collect_all_files(field_dir):
    (field_dir / "subdir").mkdir()
    (field_dir / "subdir" / "nested.md").write_text("nested\n", encoding="utf-8")
    (field_dir / "image.png").write_bytes(b"\x89PNG")
    (field_dir / "editor~").write_text("debris\n", encoding="utf-8")

    names = collect_all_files(transport.local(field_dir))
    assert "alpha.md" in names
    assert "index.md" in names
    assert "subdir/nested.md" in names
    assert "image.png" in names
    assert "editor~" in names


def test_page_infos(field_dir):
    infos = page_infos(transport.local(field_dir))
    assert [o.key for o in infos] == ["alpha.md", "beta.md", "gamma.md", "index.md"]
    alpha = infos[0]
    assert alpha.size == (field_dir / "alpha.md").stat().st_size
    assert isinstance(alpha.last_modified, datetime)


def test_write_creates_page(field_dir):
    result = write_page(
        transport.local(field_dir), "new.md", b"---\ntitle: New\n---\n\nnew content\n"
    )
    assert result.created is True
    text = (field_dir / "new.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert fm["title"] == "New"
    assert "uuid" in fm
    assert "created" in fm
    assert "updated" in fm
    assert text.endswith("new content\n")


def test_write_overwrite_refused(field_dir):
    (field_dir / "plain.md").write_text("original", encoding="utf-8")
    with pytest.raises(FileExists):
        write_page(transport.local(field_dir), "plain.md", b"new content")
    assert (field_dir / "plain.md").read_text(encoding="utf-8") == "original"


def test_write_force_overwrites(field_dir):
    (field_dir / "plain.md").write_text("old plain content", encoding="utf-8")
    result = write_page(transport.local(field_dir), "plain.md", b"new content", force=True)
    assert result.created is False
    text = (field_dir / "plain.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert "uuid" in fm
    assert "created" in fm
    assert "updated" in fm
    assert text.endswith("new content")


def test_write_append(field_dir):
    (field_dir / "plain.md").write_text("first\n", encoding="utf-8")
    result = write_page(transport.local(field_dir), "plain.md", b"second\n", append=True)
    assert result.created is False
    assert (field_dir / "plain.md").read_text(encoding="utf-8") == "first\nsecond\n"


def test_write_append_to_new_file_creates_frontmatter(field_dir):
    result = write_page(transport.local(field_dir), "fresh.md", b"hello\n", append=True)
    assert result.created is True
    assert result.uuid is not None
    text = (field_dir / "fresh.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert "uuid" in fm
    assert fm["created"] == fm["updated"]
    assert text.endswith("hello\n")


def test_write_invalid_filename_rejected(field_dir):
    with pytest.raises(InvalidFilename):
        write_page(transport.local(field_dir), "Bad Name.md", b"x")
    with pytest.raises(InvalidFilename):
        write_page(transport.local(field_dir), "../escape.md", b"x")


def test_write_invalid_utf8_rejected(field_dir):
    with pytest.raises(InvalidUtf8):
        write_page(transport.local(field_dir), "new.md", b"\xff\xfe\x00\x01")
    assert not (field_dir / "new.md").exists()


def test_write_empty_body_rejected(field_dir):
    with pytest.raises(EmptyBody):
        write_page(transport.local(field_dir), "new.md", b"   \n\n")
    assert not (field_dir / "new.md").exists()


def test_write_uuid_conflict_rejected(field_dir):
    with pytest.raises(UuidConflict):
        write_page(
            transport.local(field_dir),
            "alpha.md",
            b"---\nuuid: 11111111-2222-3333-4444-555555555555\n---\n\nbody\n",
            force=True,
        )


def test_write_uuid_preserved(field_dir):
    old_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    old_uuid = frontmatter.get_frontmatter_field(old_text, "uuid")
    result = write_page(
        transport.local(field_dir),
        "alpha.md",
        b"---\ntitle: New\n---\n\nbody\n",
        force=True,
    )
    assert result.created is False
    new_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    assert frontmatter.get_frontmatter_field(new_text, "uuid") == old_uuid


_UUID6_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-6[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def test_write_auto_fill_bare_body(field_dir):
    result = write_page(transport.local(field_dir), "note.md", b"note body\n")
    assert result.created is True
    text = (field_dir / "note.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert _UUID6_RE.fullmatch(fm["uuid"])
    assert result.uuid == fm["uuid"]
    assert datetime.fromisoformat(fm["created"]) is not None
    assert datetime.fromisoformat(fm["updated"]) is not None
    assert fm["title"] == "note"
    assert "summary" not in fm
    assert text.endswith("note body\n")


def test_write_auto_fill_with_flags(field_dir):
    result = write_page(
        transport.local(field_dir),
        "note.md",
        b"note body\n",
        title="A Title",
        summary="A summary.",
        title_fallback="ignored",
    )
    assert result.created is True
    fm, _ = frontmatter.parse_frontmatter((field_dir / "note.md").read_text(encoding="utf-8"))
    assert fm["title"] == "A Title"
    assert fm["summary"] == "A summary."


def test_write_force_refreshes_updated_preserves_created(field_dir):
    old_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    old_fm, _ = frontmatter.parse_frontmatter(old_text)
    result = write_page(transport.local(field_dir), "alpha.md", b"fresh body\n", force=True)
    assert result.created is False
    new_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    new_fm, _ = frontmatter.parse_frontmatter(new_text)
    assert new_fm["uuid"] == old_fm["uuid"]
    assert new_fm["created"] == old_fm["created"]
    assert new_fm["updated"] != old_fm["updated"]
    assert datetime.fromisoformat(new_fm["updated"]) is not None
    assert new_fm["title"] == old_fm["title"]
    assert new_text.endswith("fresh body\n")


def test_write_created_equals_updated_on_create(field_dir):
    result = write_page(transport.local(field_dir), "new.md", b"content\n")
    assert result.created is True
    text = (field_dir / "new.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert fm["created"] == fm["updated"]


def test_write_append_refreshes_updated_preserves_created(field_dir):
    old_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    old_fm, _ = frontmatter.parse_frontmatter(old_text)
    result = write_page(transport.local(field_dir), "alpha.md", b"\nappended\n", append=True)
    assert result.created is False
    assert result.uuid == old_fm["uuid"]
    new_text = (field_dir / "alpha.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(new_text)
    assert fm["uuid"] == old_fm["uuid"]
    assert fm["created"] == old_fm["created"]
    assert fm["updated"] != old_fm["updated"]
    assert new_text.endswith("appended\n")


def test_write_append_raw_without_frontmatter_stays_raw(field_dir):
    (field_dir / "plain.md").write_text("first\n", encoding="utf-8")
    result = write_page(transport.local(field_dir), "plain.md", b"second\n", append=True)
    assert result.created is False
    assert result.uuid is None
    text = (field_dir / "plain.md").read_text(encoding="utf-8")
    assert text == "first\nsecond\n"
    assert "---" not in text


def test_write_force_normalizes_unquoted_created(field_dir):
    (field_dir / "plain.md").write_text(
        "---\ncreated: 2026-03-01\n---\n\nbody\n", encoding="utf-8"
    )
    write_page(transport.local(field_dir), "plain.md", b"new body\n", force=True)
    text = (field_dir / "plain.md").read_text(encoding="utf-8")
    assert "created: '2026-03-01'" in text
    fm, _ = frontmatter.parse_frontmatter(text)
    assert fm["created"] == "2026-03-01"


def test_write_force_differing_uuid_conflict(field_dir):
    with pytest.raises(UuidConflict):
        write_page(
            transport.local(field_dir),
            "alpha.md",
            b"---\nuuid: 11111111-2222-3333-4444-555555555555\n---\n\nbody\n",
            force=True,
        )


def test_write_append_raw_bytes_uuid_none(field_dir):
    (field_dir / "plain.md").write_text("first\n", encoding="utf-8")
    result = write_page(transport.local(field_dir), "plain.md", b"second\n", append=True)
    assert result.created is False
    assert result.uuid is None
    assert (field_dir / "plain.md").read_text(encoding="utf-8") == "first\nsecond\n"
