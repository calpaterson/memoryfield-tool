import re
import tempfile
from pathlib import Path

import boto3
from moto import mock_aws

from memoryfield_tool import cli, frontmatter


def test_edit_modifies_and_preserves_uuid(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    old_text = (field_path / "alpha.md").read_text(encoding="utf-8")
    old_uuid = frontmatter.get_frontmatter_field(old_text, "uuid")
    script = editor_script('echo "EDITED" >> "$1"')
    result = cli_runner.invoke(cli.cli, ["edit", "--editor", str(script), "alpha.md"])
    assert result.exit_code == 0
    new_text = (field_path / "alpha.md").read_text(encoding="utf-8")
    assert new_text.endswith("EDITED\n")
    assert frontmatter.get_frontmatter_field(new_text, "uuid") == old_uuid
    assert spawned == ["notes"]
    assert "Wrote" in result.output
    assert "to notes/alpha.md" in result.output


def test_edit_no_changes(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    spawned = []
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", spawned.append)
    before = (field_path / "alpha.md").read_bytes()

    created: list[str] = []
    real_mkstemp = tempfile.mkstemp

    def _recording_mkstemp(*args, **kwargs):
        fd, p = real_mkstemp(*args, **kwargs)
        created.append(p)
        return fd, p

    monkeypatch.setattr("memoryfield_tool.cli.tempfile.mkstemp", _recording_mkstemp)

    script = editor_script("true")
    result = cli_runner.invoke(cli.cli, ["edit", "--editor", str(script), "alpha.md"])
    assert result.exit_code == 0
    assert "no changes to notes/alpha.md" in result.output
    assert (field_path / "alpha.md").read_bytes() == before
    assert spawned == []
    assert len(created) == 1
    assert not Path(created[0]).exists()


def test_edit_editor_failure_keeps_temp(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    before = (field_path / "alpha.md").read_bytes()
    script = editor_script("exit 3")
    result = cli_runner.invoke(cli.cli, ["edit", "--editor", str(script), "alpha.md"])
    assert result.exit_code == 1
    assert "exited with status 3" in result.output
    match = re.search(r"(/tmp/memoryfield-edit-\S+\.md)", result.output)
    assert match is not None
    temp_path = Path(match.group(1))
    assert temp_path.is_file()
    try:
        assert (field_path / "alpha.md").read_bytes() == before
    finally:
        temp_path.unlink(missing_ok=True)


def test_edit_missing_page_errors(cli_runner, connected, editor_script):
    script = editor_script("true")
    result = cli_runner.invoke(cli.cli, ["edit", "--editor", str(script), "nope.md"])
    assert result.exit_code == 1
    assert "page not found" in result.output


def test_edit_binary_rejected(cli_runner, connected, editor_script):
    _cfg_path, field_path = connected
    (field_path / "bin.md").write_bytes(b"\xff\xfe\x00")
    script = editor_script("true")
    result = cli_runner.invoke(cli.cli, ["edit", "--editor", str(script), "bin.md"])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_edit_empty_result_rejected(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    before = (field_path / "alpha.md").read_bytes()
    script = editor_script(': > "$1"')
    result = cli_runner.invoke(cli.cli, ["edit", "--editor", str(script), "alpha.md"])
    assert result.exit_code == 1
    assert "empty page" in result.output
    match = re.search(r"(/tmp/memoryfield-edit-\S+\.md)", result.output)
    assert match is not None
    temp_path = Path(match.group(1))
    assert temp_path.is_file()
    try:
        assert (field_path / "alpha.md").read_bytes() == before
    finally:
        temp_path.unlink(missing_ok=True)


def test_edit_requires_terminal_without_editor(cli_runner, connected, monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    result = cli_runner.invoke(cli.cli, ["edit", "alpha.md"])
    assert result.exit_code == 1
    assert "interactive and needs a terminal" in result.output


def test_edit_uses_editor_env(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    script = editor_script('echo "EDITED" >> "$1"')
    monkeypatch.setenv("EDITOR", str(script))
    result = cli_runner.invoke(cli.cli, ["edit", "alpha.md"])
    assert result.exit_code == 0
    assert (field_path / "alpha.md").read_text(encoding="utf-8").endswith("EDITED\n")


def test_edit_visual_precedes_editor(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    visual = editor_script('echo "VISUAL-EDITED" >> "$1"')
    editor = editor_script('echo "EDITOR-EDITED" >> "$1"')
    monkeypatch.setenv("VISUAL", str(visual))
    monkeypatch.setenv("EDITOR", str(editor))
    result = cli_runner.invoke(cli.cli, ["edit", "alpha.md"])
    assert result.exit_code == 0
    text = (field_path / "alpha.md").read_text(encoding="utf-8")
    assert text.endswith("VISUAL-EDITED\n")
    assert "EDITOR-EDITED" not in text


def test_edit_editor_with_args(cli_runner, connected, editor_script, monkeypatch):
    _cfg_path, field_path = connected
    script = editor_script('for last; do :; done\necho "EDITED" >> "$last"')
    monkeypatch.setenv("EDITOR", f"{script} --flag")
    result = cli_runner.invoke(cli.cli, ["edit", "alpha.md"])
    assert result.exit_code == 0
    assert (field_path / "alpha.md").read_text(encoding="utf-8").endswith("EDITED\n")


@mock_aws
def test_edit_s3_page(cli_runner, config_env, editor_script, monkeypatch):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="cadentia-bucket")
    conn.put_object(Bucket="cadentia-bucket", Key="cadentia/index.md", Body=b"# hi\n")
    conn.put_object(
        Bucket="cadentia-bucket",
        Key="cadentia/alpha.md",
        Body=b"---\ntitle: Alpha\n---\n\nbody\n",
    )
    config_env.write_text(
        '[memoryfields.cadentia]\ntransport = "s3"\nlocation = "s3://cadentia-bucket/cadentia"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("memoryfield_tool.cli.reindex.spawn_background_index", lambda name: None)
    script = editor_script('echo "EDITED" >> "$1"')
    result = cli_runner.invoke(
        cli.cli,
        ["edit", "--editor", str(script), "--field", "cadentia", "alpha.md"],
    )
    assert result.exit_code == 0
    got = conn.get_object(Bucket="cadentia-bucket", Key="cadentia/alpha.md")["Body"].read()
    assert b"EDITED" in got
    assert b"uuid:" in got  # write_page preserved/filled frontmatter
