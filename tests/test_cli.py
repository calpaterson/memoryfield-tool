import json
from pathlib import Path

import boto3
from moto import mock_aws

from memoryfield_tool import cli, config, frontmatter, index, transport


def test_create_makes_field(cli_runner, config_env):
    loc = config_env.parent / "demo"
    result = cli_runner.invoke(cli.cli, ["create", "demo", "--location", str(loc)])
    assert result.exit_code == 0
    assert loc.is_dir()
    assert (loc / "index.md").is_file()
    assert not (loc / "getting-started.md").exists()
    cfg = config.load_config()
    assert "demo" in cfg.fields
    assert "Created memoryfield" in result.output
    assert str(loc) in result.output


def test_create_existing_dir_errors(cli_runner, config_env):
    loc = config_env.parent / "demo"
    loc.mkdir()
    result = cli_runner.invoke(cli.cli, ["create", "demo", "--location", str(loc)])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_create_existing_name_errors(cli_runner, connected):
    _cfg_path, _field_path = connected
    loc = config.config_path().parent / "x"
    result = cli_runner.invoke(cli.cli, ["create", "notes", "--location", str(loc)])
    assert result.exit_code == 1
    assert "already connected" in result.output


def test_connect_registers(cli_runner, config_env, field_dir):
    result = cli_runner.invoke(cli.cli, ["connect", "notes", str(field_dir)])
    assert result.exit_code == 0
    cfg = config.load_config()
    assert "notes" in cfg.fields
    assert cfg.fields["notes"].transport == "local"
    assert "Connected memoryfield" in result.output


def test_connect_duplicate_errors(cli_runner, connected):
    _cfg_path, field_path = connected
    result = cli_runner.invoke(cli.cli, ["connect", "notes", str(field_path)])
    assert result.exit_code == 1
    assert "already connected" in result.output


def test_connect_non_directory_errors(cli_runner, config_env, tmp_path):
    result = cli_runner.invoke(cli.cli, ["connect", "notes", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "not a directory" in result.output


def test_connect_bad_name_errors(cli_runner, config_env, field_dir):
    result = cli_runner.invoke(cli.cli, ["connect", "Bad Name", str(field_dir)])
    assert result.exit_code == 1
    assert "invalid memoryfield name" in result.output


def test_catalog_single_field(cli_runner, connected):
    _cfg_path, _field_path = connected
    result = cli_runner.invoke(cli.cli, ["catalog"])
    assert result.exit_code == 0
    assert "| Page | Summary |" in result.output
    assert "alpha.md" in result.output
    assert "Notes about alpha things." in result.output
    assert "| Field |" not in result.output


def test_catalog_multi_field(cli_runner, config_env, field_dir, tmp_path):
    field2 = tmp_path / "field2"
    field2.mkdir()
    (field2 / "work.md").write_text(
        "---\ntitle: Work\nsummary: Work notes\n---\n\nwork\n", encoding="utf-8"
    )
    config_env.write_text(
        f"[memoryfields.notes]\n"
        f'transport = "local"\n'
        f'location = "{field_dir}"\n'
        f'created = "2026-01-01T00:00:00Z"\n'
        f'last_used = "2026-01-01T00:00:00Z"\n'
        f"[memoryfields.work]\n"
        f'transport = "local"\n'
        f'location = "{field2}"\n'
        f'created = "2026-01-01T00:00:00Z"\n'
        f'last_used = "2026-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["catalog"])
    assert result.exit_code == 0
    assert "| Field | Page | Summary |" in result.output
    assert "notes | alpha.md" in result.output
    assert "work | work.md" in result.output


def test_catalog_json(cli_runner, connected):
    _cfg_path, _field_path = connected
    result = cli_runner.invoke(cli.cli, ["catalog", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["field"] == "notes"
    assert data[0]["filename"] == "alpha.md"
    assert data[0]["title"] == "Alpha Notes"


def test_catalog_sort_title(cli_runner, connected):
    _cfg_path, field_path = connected
    beta = field_path / "beta.md"
    beta.write_text(
        beta.read_text(encoding="utf-8").replace("title: Beta Notes", "title: Zulu Notes"),
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["catalog", "--sort", "title"])
    assert result.exit_code == 0
    out = result.output
    assert out.index("alpha.md") < out.index("gamma.md")
    assert out.index("gamma.md") < out.index("beta.md")


def test_catalog_sort_created(cli_runner, connected):
    _cfg_path, field_path = connected
    alpha = field_path / "alpha.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8").replace(
            "created: '2026-01-01T09:00:00Z'", "created: '2026-02-01T09:00:00Z'"
        ),
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["catalog", "--sort", "created"])
    assert result.exit_code == 0
    out = result.output
    assert out.index("alpha.md") < out.index("beta.md")


def test_fields_single(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "index.md").write_text(
        "---\ntitle: My Notes\n---\n\n# Notes\n", encoding="utf-8"
    )
    result = cli_runner.invoke(cli.cli, ["fields"])
    assert result.exit_code == 0
    assert "| Field | Transport | Location | Title |" in result.output
    assert "notes" in result.output
    assert "local" in result.output
    assert str(field_path) in result.output
    assert "My Notes" in result.output


def test_fields_json(cli_runner, connected):
    _cfg_path, _field_path = connected
    result = cli_runner.invoke(cli.cli, ["fields", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    row = data[0]
    assert row["name"] == "notes"
    assert "transport" in row
    assert "location" in row
    assert "title" in row


def test_fields_no_fields(cli_runner, config_env):
    result = cli_runner.invoke(cli.cli, ["fields"])
    assert result.exit_code == 0
    assert "No memoryfields connected." in result.output


def test_path_local_root(cli_runner, connected):
    _cfg_path, field_path = connected
    result = cli_runner.invoke(cli.cli, ["path"])
    assert result.exit_code == 0
    assert result.output.strip() == str(field_path.resolve())


def test_path_local_page(cli_runner, connected):
    _cfg_path, field_path = connected
    result = cli_runner.invoke(cli.cli, ["path", "alpha.md"])
    assert result.exit_code == 0
    assert result.output.strip() == str(field_path.resolve() / "alpha.md")


def test_path_s3_uri(cli_runner, config_env):
    config_env.write_text(
        '[memoryfields.cadentia]\ntransport = "s3"\nlocation = "s3://cadentia-bucket/cadentia"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["path"])
    assert result.exit_code == 0
    assert result.output.strip() == "s3://cadentia-bucket/cadentia"
    result = cli_runner.invoke(cli.cli, ["path", "alpha.md"])
    assert result.exit_code == 0
    assert result.output.strip() == "s3://cadentia-bucket/cadentia/alpha.md"


def test_path_multi_field_requires_field(cli_runner, config_env, field_dir, tmp_path):
    field2 = tmp_path / "field2"
    field2.mkdir()
    config_env.write_text(
        f'[memoryfields.notes]\ntransport = "local"\nlocation = "{field_dir}"\n'
        f'[memoryfields.work]\ntransport = "local"\nlocation = "{field2}"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["path"])
    assert result.exit_code == 1
    assert "specify --field" in result.output


def test_path_invalid_filename_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["path", "../outside.md"])
    assert result.exit_code == 1
    assert "invalid page filename" in result.output


def test_path_no_fields_errors(cli_runner, config_env):
    result = cli_runner.invoke(cli.cli, ["path"])
    assert result.exit_code == 1
    assert "no memoryfields connected" in result.output


def test_read_default_line_numbers(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "note.md").write_text("line1\nline2\nline3\n", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["read", "note.md"])
    assert result.exit_code == 0
    assert "1: line1" in result.output
    assert "2: line2" in result.output
    assert "3: line3" in result.output


def test_read_offset_limit(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "note.md").write_text(
        "".join(f"line{i}\n" for i in range(1, 21)), encoding="utf-8"
    )
    result = cli_runner.invoke(cli.cli, ["read", "note.md", "--offset", "5", "--limit", "3"])
    assert result.exit_code == 0
    assert "5: line5" in result.output
    assert "7: line7" in result.output
    assert "8: line8" not in result.output


def test_read_no_limit(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "note.md").write_text(
        "".join(f"line{i}\n" for i in range(1, 30)), encoding="utf-8"
    )
    result = cli_runner.invoke(cli.cli, ["read", "note.md", "--no-limit"])
    assert result.exit_code == 0
    assert "1: line1" in result.output
    assert "29: line29" in result.output


def test_read_no_line_numbers(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "note.md").write_text("hello\nworld\n", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["read", "note.md", "--no-line-numbers"])
    assert result.exit_code == 0
    assert "hello" in result.output
    assert "1: hello" not in result.output


def test_read_multi_file_labels(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["read", "alpha.md", "beta.md"])
    assert result.exit_code == 0
    assert "### FILE: alpha.md" in result.output
    assert "### FILE: beta.md" in result.output


def test_read_missing_page_errors(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["read", "missing.md"])
    assert result.exit_code == 1
    assert "file not found" in result.output


def test_read_escape_errors(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["read", "../outside.md"])
    assert result.exit_code == 1
    assert "escapes" in result.output


def test_write_creates_page(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    content = "---\ntitle: New\n---\n\nnew content\n"
    result = cli_runner.invoke(cli.cli, ["write", "new.md"], input=content)
    assert result.exit_code == 0
    text = (field_path / "new.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert fm["title"] == "New"
    assert "uuid" in fm
    assert "created" in fm
    assert "updated" in fm
    assert text.endswith("new content\n")
    assert "Wrote" in result.output


def test_write_overwrite_refused(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    (field_path / "plain.md").write_text("original", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["write", "plain.md"], input="new content")
    assert result.exit_code == 1
    assert "file exists" in result.output
    assert (field_path / "plain.md").read_text(encoding="utf-8") == "original"


def test_write_force_overwrites(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    (field_path / "plain.md").write_text("old plain content", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["write", "--force", "plain.md"], input="new content")
    assert result.exit_code == 0
    text = (field_path / "plain.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert "uuid" in fm
    assert "created" in fm
    assert "updated" in fm
    assert text.endswith("new content")


def test_write_append(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    (field_path / "plain.md").write_text("first\n", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["write", "--append", "plain.md"], input="second\n")
    assert result.exit_code == 0
    assert (field_path / "plain.md").read_text(encoding="utf-8") == "first\nsecond\n"


def test_write_dry_run_writes_nothing(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    result = cli_runner.invoke(cli.cli, ["write", "--dry-run", "new.md"], input="hello\n")
    assert result.exit_code == 0
    assert "hello" in result.output
    assert "uuid:" in result.output
    assert "created:" in result.output
    assert "updated:" in result.output
    assert "title: new" in result.output
    assert not (field_path / "new.md").exists()
    assert spawned == []


def test_write_invalid_filename_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["write", "Bad Name.md"], input="x")
    assert result.exit_code == 1
    assert "invalid page filename" in result.output


def test_write_invalid_utf8_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["write", "new.md"], input=b"\xff\xfe\x00\x01")
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_write_empty_body_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["write", "new.md"], input="   \n\n")
    assert result.exit_code == 1
    assert "empty page" in result.output


def test_write_uuid_conflict_rejected(cli_runner, connected):
    result = cli_runner.invoke(
        cli.cli,
        ["write", "--force", "alpha.md"],
        input="---\nuuid: 11111111-2222-3333-4444-555555555555\n---\n\nbody\n",
    )
    assert result.exit_code == 1
    assert "uuid conflict" in result.output


def test_write_uuid_preserved(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    old_text = (field_path / "alpha.md").read_text(encoding="utf-8")
    old_fm, _ = frontmatter.parse_frontmatter(old_text)
    old_uuid = old_fm["uuid"]
    result = cli_runner.invoke(
        cli.cli,
        ["write", "--force", "alpha.md"],
        input="---\ntitle: New\n---\n\nbody\n",
    )
    assert result.exit_code == 0
    new_text = (field_path / "alpha.md").read_text(encoding="utf-8")
    new_fm, _ = frontmatter.parse_frontmatter(new_text)
    assert new_fm["uuid"] == old_uuid
    assert new_fm["created"] == old_fm["created"]
    assert new_fm["updated"] != old_fm["updated"]
    assert new_fm["title"] == "New"


def test_write_touches_no_config(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    config_before = config.load_config()
    cli_runner.invoke(cli.cli, ["write", "new.md"], input="content\n")
    config_after = config.load_config()
    assert config_after == config_before


def test_write_spawns_exactly_once(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    cli_runner.invoke(cli.cli, ["write", "new.md"], input="content\n")
    assert spawned == ["notes"]


def test_write_title_and_summary_flags(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(
        cli.cli,
        ["write", "new.md", "--title", "New Page", "--summary", "About it"],
        input="body\n",
    )
    assert result.exit_code == 0
    fm, _ = frontmatter.parse_frontmatter((field_path / "new.md").read_text(encoding="utf-8"))
    assert fm["title"] == "New Page"
    assert fm["summary"] == "About it"


def test_new_creates_slugged_page(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    result = cli_runner.invoke(cli.cli, ["new", "Carbon Fibre Woks"], input="body\n")
    assert result.exit_code == 0
    page = field_path / "carbon-fibre-woks.md"
    assert page.is_file()
    fm, _ = frontmatter.parse_frontmatter(page.read_text(encoding="utf-8"))
    assert fm["title"] == "Carbon Fibre Woks"
    assert "uuid" in fm
    assert "created" in fm
    assert "updated" in fm
    assert "summary" not in fm
    assert page.read_text(encoding="utf-8").endswith("body\n")
    assert "Created notes/carbon-fibre-woks.md" in result.output
    assert "uuid:" in result.output
    assert spawned == ["notes"]


def test_new_empty_stdin_uses_skeleton(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["new", "Skeleton Page"])
    assert result.exit_code == 0
    text = (field_path / "skeleton-page.md").read_text(encoding="utf-8")
    assert text.endswith("# Skeleton Page\n\n")


def test_new_name_override(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["new", "Custom", "--name", "foo.md"], input="x\n")
    assert result.exit_code == 0
    assert (field_path / "foo.md").is_file()


def test_new_name_without_md_gets_appended(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["new", "Custom", "--name", "bar"], input="x\n")
    assert result.exit_code == 0
    assert (field_path / "bar.md").is_file()


def test_new_existing_slug_errors(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    (field_path / "carbon-fibre-woks.md").write_text("existing\n", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["new", "Carbon Fibre Woks"], input="body\n")
    assert result.exit_code == 1
    assert "page already exists" in result.output


def test_new_unslugable_title_errors(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["new", "!!!"])
    assert result.exit_code == 1
    assert "--name" in result.output


def test_new_summary_flag(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["new", "Topic", "--summary", "A summary"], input="x\n")
    assert result.exit_code == 0
    fm, _ = frontmatter.parse_frontmatter((field_path / "topic.md").read_text(encoding="utf-8"))
    assert fm["summary"] == "A summary"


def test_new_dry_run_writes_nothing(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    result = cli_runner.invoke(cli.cli, ["new", "Draft", "--dry-run"], input="draft body\n")
    assert result.exit_code == 0
    assert "uuid:" in result.output
    assert "created:" in result.output
    assert "title: Draft" in result.output
    assert "draft body" in result.output
    assert not (field_path / "draft.md").exists()
    assert spawned == []


def test_new_multi_field_requires_field(cli_runner, config_env, field_dir, tmp_path):
    field2 = tmp_path / "field2"
    field2.mkdir()
    config_env.write_text(
        f'[memoryfields.notes]\ntransport = "local"\nlocation = "{field_dir}"\n'
        f'[memoryfields.work]\ntransport = "local"\nlocation = "{field2}"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["new", "Topic"], input="x\n")
    assert result.exit_code == 1
    assert "specify --field" in result.output


def test_delete_removes_page(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    (field_path / "plain.md").write_text("plain content\n", encoding="utf-8")
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["delete", "plain.md"])
    assert result.exit_code == 0
    assert not (field_path / "plain.md").exists()
    assert "Deleted notes/plain.md" in result.output


def test_delete_spawns_reindex_once(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    cli_runner.invoke(cli.cli, ["delete", "alpha.md"])
    assert spawned == ["notes"]


def test_delete_removes_index_row(cli_runner, connected, fake_embed, monkeypatch):
    _cfg_path, field_path = connected
    index.build_index(transport.local(field_path), index.index_path(field_path), progress=False)
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["delete", "beta.md"])
    assert result.exit_code == 0
    db = index._open_index(index.index_path(field_path))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert "beta.md" not in names
    assert "alpha.md" in names


def test_delete_missing_page_errors(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["delete", "nope.md"])
    assert result.exit_code == 1
    assert "page not found" in result.output


def test_delete_invalid_filename_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["delete", "Bad Name.md"])
    assert result.exit_code == 1
    assert "invalid page filename" in result.output


def test_delete_escape_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["delete", "../outside.md"])
    assert result.exit_code == 1
    assert "invalid page filename" in result.output


def test_delete_index_refused(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["delete", "index.md"])
    assert result.exit_code == 1
    assert "refusing to delete index.md" in result.output


@mock_aws
def test_delete_s3_removes_object(cli_runner, config_env, monkeypatch):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/temp.md", Body=b"# temp\n")
    monkeypatch.setattr(transport.S3Transport, "probe", lambda self: None)
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    config_env.write_text(
        '[memoryfields.cadentia]\ntransport = "s3"\nlocation = "s3://cadentia-bucket/cadentia"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["delete", "--field", "cadentia", "temp.md"])
    assert result.exit_code == 0
    assert "Deleted cadentia/temp.md" in result.output
    keys = [o["Key"] for o in conn.list_objects_v2(Bucket="cadentia-bucket")["Contents"]]
    assert "cadentia/temp.md" not in keys
    assert "cadentia/index.md" in keys


def test_rename_moves_page(cli_runner, connected, monkeypatch):
    _cfg_path, field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    old_fm, _ = frontmatter.parse_frontmatter(
        (field_path / "alpha.md").read_text(encoding="utf-8")
    )
    result = cli_runner.invoke(cli.cli, ["rename", "alpha.md", "renamed.md"])
    assert result.exit_code == 0
    assert not (field_path / "alpha.md").exists()
    text = (field_path / "renamed.md").read_text(encoding="utf-8")
    fm, _ = frontmatter.parse_frontmatter(text)
    assert "Alpha is the first letter." in text
    assert fm["uuid"] == old_fm["uuid"]
    assert fm["created"] == old_fm["created"]
    assert fm["updated"] != old_fm["updated"]
    assert "Renamed notes/alpha.md -> notes/renamed.md" in result.output


def test_rename_spawns_reindex_once(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    cli_runner.invoke(cli.cli, ["rename", "alpha.md", "renamed.md"])
    assert spawned == ["notes"]


def test_rename_removes_old_index_row(cli_runner, connected, fake_embed, monkeypatch):
    _cfg_path, field_path = connected
    index.build_index(transport.local(field_path), index.index_path(field_path), progress=False)
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    result = cli_runner.invoke(cli.cli, ["rename", "beta.md", "beta2.md"])
    assert result.exit_code == 0
    db = index._open_index(index.index_path(field_path))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert "beta.md" not in names
    assert "alpha.md" in names


def test_rename_missing_source_errors(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["rename", "nope.md", "x.md"])
    assert result.exit_code == 1
    assert "page not found" in result.output


def test_rename_target_exists_errors(cli_runner, connected):
    _cfg_path, field_path = connected
    result = cli_runner.invoke(cli.cli, ["rename", "alpha.md", "beta.md"])
    assert result.exit_code == 1
    assert "page already exists" in result.output
    assert (field_path / "alpha.md").exists()


def test_rename_same_name_errors(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["rename", "alpha.md", "alpha.md"])
    assert result.exit_code == 1
    assert "same page" in result.output


def test_rename_invalid_source_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["rename", "Bad Name.md", "x.md"])
    assert result.exit_code == 1
    assert "invalid source filename" in result.output


def test_rename_invalid_destination_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["rename", "alpha.md", "Bad Name.md"])
    assert result.exit_code == 1
    assert "invalid destination filename" in result.output


def test_rename_escape_rejected(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["rename", "../outside.md", "x.md"])
    assert result.exit_code == 1
    assert "invalid source filename" in result.output


def test_rename_index_refused(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["rename", "index.md", "other.md"])
    assert result.exit_code == 1
    assert "refusing to rename index.md" in result.output


@mock_aws
def test_rename_s3_moves_object(cli_runner, config_env, monkeypatch):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/temp.md", Body=b"# temp\n")
    monkeypatch.setattr(transport.S3Transport, "probe", lambda self: None)
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    config_env.write_text(
        '[memoryfields.cadentia]\ntransport = "s3"\nlocation = "s3://cadentia-bucket/cadentia"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["rename", "--field", "cadentia", "temp.md", "temp2.md"])
    assert result.exit_code == 0
    assert "Renamed cadentia/temp.md -> cadentia/temp2.md" in result.output
    keys = [o["Key"] for o in conn.list_objects_v2(Bucket="cadentia-bucket")["Contents"]]
    assert "cadentia/temp.md" not in keys
    assert "cadentia/temp2.md" in keys
    body = conn.get_object(Bucket="cadentia-bucket", Key="cadentia/temp2.md")["Body"].read()
    assert b"# temp" in body


def test_help_examples_verbatim(cli_runner):
    result = cli_runner.invoke(cli.cli, ["write", "--help"])
    assert result.exit_code == 0
    assert "Examples:" in result.output
    assert "echo '# New page' | memoryfield-tool write new-page.md" in result.output
    assert (
        "echo '# New page' | memoryfield-tool write new-page.md --title 'New Page' "
        "--summary 'About'" in result.output
    )
    assert "memoryfield-tool write --dry-run new-page.md < draft.md" in result.output


def test_schema_output(cli_runner):
    result = cli_runner.invoke(cli.cli, ["--schema"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["tool"] == "memoryfield-tool"
    assert "version" in data
    names = {c["name"] for c in data["commands"]}
    assert {
        "write",
        "new",
        "edit",
        "delete",
        "path",
        "rename",
        "read",
        "search",
        "catalog",
        "validate",
        "index",
        "export",
        "create",
        "connect",
        "fields",
        "serve",
    } <= names
    write = next(c for c in data["commands"] if c["name"] == "write")
    param_names = {p["name"] for p in write["params"]}
    assert "title" in param_names
    assert "summary" in param_names
    catalog = next(c for c in data["commands"] if c["name"] == "catalog")
    sort_by = next(p for p in catalog["params"] if p["name"] == "sort_by")
    assert set(sort_by["choices"]) == {"path", "title", "created", "updated"}


def test_index_builds(cli_runner, connected, fake_embed):
    _cfg_path, field_path = connected
    result = cli_runner.invoke(cli.cli, ["index", "--field", "notes"])
    assert result.exit_code == 0
    assert (field_path / "nomic-embed-text-v1.5.sqlite3").is_file()
    assert "indexed 4 files" in result.output


def test_index_up_to_date(cli_runner, connected, fake_embed):
    _cfg_path, _field_path = connected
    cli_runner.invoke(cli.cli, ["index", "--field", "notes"])
    result = cli_runner.invoke(cli.cli, ["index", "--field", "notes"])
    assert result.exit_code == 0
    assert "all files up to date" in result.output


def test_index_embedding_unavailable(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    monkeypatch.setattr("memoryfield_tool.cli.index.embed.embed_texts", lambda texts: None)
    result = cli_runner.invoke(cli.cli, ["index", "--field", "notes"])
    assert result.exit_code == 0
    assert "embedding unavailable" in result.output


def test_search_text(cli_runner, connected, fake_embed):
    _cfg_path, _field_path = connected
    cli_runner.invoke(cli.cli, ["index", "--field", "notes"])
    result = cli_runner.invoke(cli.cli, ["search", "--field", "notes", "beta"])
    assert result.exit_code == 0
    assert "beta.md" in result.output


def test_search_json(cli_runner, connected):
    _cfg_path, _field_path = connected
    result = cli_runner.invoke(cli.cli, ["search", "--json", "gamma"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert any(r["filename"] == "gamma.md" and r["field"] == "notes" for r in data)


def test_search_multi_field_prefix(cli_runner, config_env, field_dir, tmp_path):
    field2 = tmp_path / "field2"
    field2.mkdir()
    (field2 / "work.md").write_text(
        "---\ntitle: Work\nsummary: Work notes\n---\n\nwork\n", encoding="utf-8"
    )
    config_env.write_text(
        f"[memoryfields.notes]\n"
        f'transport = "local"\n'
        f'location = "{field_dir}"\n'
        f'created = "2026-01-01T00:00:00Z"\n'
        f'last_used = "2026-01-01T00:00:00Z"\n'
        f"[memoryfields.work]\n"
        f'transport = "local"\n'
        f'location = "{field2}"\n'
        f'created = "2026-01-01T00:00:00Z"\n'
        f'last_used = "2026-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["search", "work"])
    assert result.exit_code == 0
    assert "work/work.md" in result.output


def test_validate_clean_exit_0(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["validate", "--field", "notes"])
    assert result.exit_code == 0
    assert "0 errors, 0 warnings" in result.output


def test_validate_errors_exit_1(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "Bad_Name.md").write_text("bad", encoding="utf-8")
    result = cli_runner.invoke(cli.cli, ["validate", "--field", "notes"])
    assert result.exit_code == 1
    assert "1 errors" in result.output
    assert "Bad_Name.md" in result.output


def test_validate_fix_quotes_unquoted_datetimes(cli_runner, connected):
    _cfg_path, field_path = connected
    (field_path / "unquoted.md").write_text(
        "---\n"
        "title: Unquoted\n"
        "uuid: 6aa615f0-486f-48a7-a210-ba4f5ff18c8b\n"
        "created: 2026-03-01\n"
        "updated: 2026-03-02 14:30:00\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    result = cli_runner.invoke(cli.cli, ["validate", "--field", "notes"])
    assert result.exit_code == 1
    assert "must be a quoted string" in result.output

    result = cli_runner.invoke(cli.cli, ["validate", "--fix", "--field", "notes"])
    assert result.exit_code == 0
    assert "fixed 1 page(s)" in result.output

    text = (field_path / "unquoted.md").read_text(encoding="utf-8")
    assert "created: '2026-03-01'" in text
    assert "updated: '2026-" in text

    result = cli_runner.invoke(cli.cli, ["validate", "--field", "notes"])
    assert result.exit_code == 0
    assert "0 errors, 0 warnings" in result.output


def test_export_with_output(cli_runner, connected, tmp_path):
    _cfg_path, _field_path = connected
    out = tmp_path / "notes.memoryfield.zip"
    result = cli_runner.invoke(cli.cli, ["export", "--field", "notes", "--output", str(out)])
    assert result.exit_code == 0
    assert out.is_file()
    assert f"Wrote notes to {out}" in result.output


def test_export_default_name_in_cwd(cli_runner, connected):
    _cfg_path, _field_path = connected
    with cli_runner.isolated_filesystem():
        result = cli_runner.invoke(cli.cli, ["export", "--field", "notes"])
        assert result.exit_code == 0
        assert Path("notes.memoryfield.zip").is_file()


def test_serve_prints_and_calls_waitress(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    calls = {}
    monkeypatch.setattr(
        "memoryfield_tool.cli.waitress_serve",
        lambda app, host, port: calls.update(host=host, port=port),
    )
    result = cli_runner.invoke(cli.cli, ["serve"])
    assert result.exit_code == 0
    assert "Serving 1 memoryfield(s) at http://127.0.0.1:6211" in result.output
    assert calls == {"host": "127.0.0.1", "port": 6211}


def test_serve_custom_port_host(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    calls = {}
    monkeypatch.setattr(
        "memoryfield_tool.cli.waitress_serve",
        lambda app, host, port: calls.update(host=host, port=port),
    )
    result = cli_runner.invoke(cli.cli, ["serve", "--port", "7000", "--host", "localhost"])
    assert result.exit_code == 0
    assert calls == {"host": "localhost", "port": 7000}


def test_serve_allow_writes_non_loopback_refuses(cli_runner, connected):
    result = cli_runner.invoke(cli.cli, ["serve", "--allow-writes", "--host", "0.0.0.0"])
    assert result.exit_code == 1
    assert "non-loopback" in result.output


def test_serve_open_calls_webbrowser(cli_runner, connected, monkeypatch):
    _cfg_path, _field_path = connected
    opened = []
    monkeypatch.setattr("memoryfield_tool.cli.webbrowser.open", opened.append)
    monkeypatch.setattr("memoryfield_tool.cli.waitress_serve", lambda app, host, port: None)
    result = cli_runner.invoke(cli.cli, ["serve", "--open"])
    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:6211"]


def test_serve_no_fields_errors(cli_runner, config_env):
    result = cli_runner.invoke(cli.cli, ["serve"])
    assert result.exit_code == 1
    assert "no memoryfields connected" in result.output


@mock_aws
def test_connect_s3_registers(cli_runner, config_env):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    result = cli_runner.invoke(cli.cli, ["connect", "cadentia", "s3://cadentia-bucket/cadentia"])
    assert result.exit_code == 0
    assert "Connected memoryfield" in result.output
    field = config.load_config().fields["cadentia"]
    assert field.transport == "s3"
    assert field.location == "s3://cadentia-bucket/cadentia"


@mock_aws
def test_connect_s3_no_scheme_errors(cli_runner, config_env):
    result = cli_runner.invoke(cli.cli, ["connect", "cadentia", "cadentia-bucket/cadentia"])
    assert result.exit_code == 1
    assert "not a directory" in result.output


@mock_aws
def test_connect_s3_malformed_uri_errors(cli_runner, config_env):
    result = cli_runner.invoke(cli.cli, ["connect", "cadentia", "s3://UPPER/prefix"])
    assert result.exit_code == 1
    assert "invalid s3 location" in result.output


@mock_aws
def test_connect_s3_unreachable_bucket_errors(cli_runner, config_env):
    result = cli_runner.invoke(cli.cli, ["connect", "cadentia", "s3://no-such-bucket-xyz/cadentia"])
    assert result.exit_code == 1
    assert "cadentia" in result.output


@mock_aws
def test_connect_s3_endpoint_url_persists(cli_runner, config_env, monkeypatch):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    monkeypatch.setattr(transport.S3Transport, "probe", lambda self: None)
    monkeypatch.setattr(transport.S3Transport, "list_objects", lambda self, *, recursive=False: [])
    result = cli_runner.invoke(
        cli.cli,
        [
            "connect",
            "cadentia",
            "s3://cadentia-bucket/cadentia",
            "--endpoint-url",
            "https://storage.googleapis.com",
        ],
    )
    assert result.exit_code == 0
    field = config.load_config().fields["cadentia"]
    assert field.endpoint_url == "https://storage.googleapis.com"


@mock_aws
def test_create_s3(cli_runner, config_env):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    result = cli_runner.invoke(
        cli.cli, ["create", "cadentia", "--location", "s3://cadentia-bucket/cadentia"]
    )
    assert result.exit_code == 0
    assert "Created memoryfield" in result.output
    body = conn.get_object(Bucket="cadentia-bucket", Key="cadentia/index.md")["Body"].read()
    assert b"# cadentia" in body
    field = config.load_config().fields["cadentia"]
    assert field.transport == "s3"
    assert field.location == "s3://cadentia-bucket/cadentia"


@mock_aws
def test_create_s3_existing_index_errors(cli_runner, config_env):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# existing\n")
    result = cli_runner.invoke(
        cli.cli, ["create", "cadentia", "--location", "s3://cadentia-bucket/cadentia"]
    )
    assert result.exit_code == 1
    assert "already contains" in result.output


@mock_aws
def test_connect_s3_persists_credentials(cli_runner, config_env, monkeypatch):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    monkeypatch.setattr(transport.S3Transport, "probe", lambda self: None)
    monkeypatch.setattr(transport.S3Transport, "list_objects", lambda self, *, recursive=False: [])
    result = cli_runner.invoke(
        cli.cli,
        [
            "connect",
            "cadentia",
            "s3://cadentia-bucket/cadentia",
            "--aws-access-key-id",
            "AKIAEXAMPLE",
            "--aws-secret-access-key",
            "secret",
            "--aws-session-token",
            "token",
        ],
    )
    assert result.exit_code == 0
    field = config.load_config().fields["cadentia"]
    assert field.aws_access_key_id == "AKIAEXAMPLE"
    assert field.aws_secret_access_key == "secret"
    assert field.aws_session_token == "token"


@mock_aws
def test_create_s3_persists_credentials(cli_runner, config_env):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    result = cli_runner.invoke(
        cli.cli,
        [
            "create",
            "cadentia",
            "--location",
            "s3://cadentia-bucket/cadentia",
            "--aws-access-key-id",
            "AKIAEXAMPLE",
            "--aws-secret-access-key",
            "secret",
        ],
    )
    assert result.exit_code == 0
    field = config.load_config().fields["cadentia"]
    assert field.aws_access_key_id == "AKIAEXAMPLE"
    assert field.aws_secret_access_key == "secret"
    assert field.aws_session_token is None


@mock_aws
def test_connect_s3_rejects_partial_credentials(cli_runner, config_env, monkeypatch):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    monkeypatch.setattr(transport.S3Transport, "probe", lambda self: None)
    monkeypatch.setattr(transport.S3Transport, "list_objects", lambda self, *, recursive=False: [])
    result = cli_runner.invoke(
        cli.cli,
        [
            "connect",
            "cadentia",
            "s3://cadentia-bucket/cadentia",
            "--aws-secret-access-key",
            "secret",
        ],
    )
    assert result.exit_code == 1
    assert "must be set together" in result.output
