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
    write_page,
)


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
    assert result.bytes_written == len(b"---\ntitle: New\n---\n\nnew content\n")
    assert (field_dir / "new.md").read_bytes() == b"---\ntitle: New\n---\n\nnew content\n"


def test_write_overwrite_refused(field_dir):
    (field_dir / "plain.md").write_text("original", encoding="utf-8")
    with pytest.raises(FileExists):
        write_page(transport.local(field_dir), "plain.md", b"new content")
    assert (field_dir / "plain.md").read_text(encoding="utf-8") == "original"


def test_write_force_overwrites(field_dir):
    (field_dir / "plain.md").write_text("old plain content", encoding="utf-8")
    result = write_page(transport.local(field_dir), "plain.md", b"new content", force=True)
    assert result.created is False
    assert (field_dir / "plain.md").read_text(encoding="utf-8") == "new content"


def test_write_append(field_dir):
    (field_dir / "plain.md").write_text("first\n", encoding="utf-8")
    result = write_page(transport.local(field_dir), "plain.md", b"second\n", append=True)
    assert result.created is False
    assert (field_dir / "plain.md").read_text(encoding="utf-8") == "first\nsecond\n"


def test_write_append_to_new_file_creates(field_dir):
    result = write_page(transport.local(field_dir), "fresh.md", b"hello\n", append=True)
    assert result.created is True
    assert (field_dir / "fresh.md").read_text(encoding="utf-8") == "hello\n"


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
