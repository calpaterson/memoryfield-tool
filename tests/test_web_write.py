import json

import boto3
import pytest
from moto import mock_aws

from memoryfield_tool import config, index, transport, web


def _frontmatter(text: str) -> dict:
    import yaml

    return yaml.safe_load(text.split("---\n")[1])


@pytest.fixture
def app(connected):
    _cfg_path, _field_path = connected
    return web.create_app(config.load_config())


@pytest.fixture
def write_app(connected):
    _cfg_path, _field_path = connected
    return web.create_app(config.load_config(), allow_writes=True)


def test_put_creates_page(write_app, connected, fake_embed):
    _cfg_path, field_path = connected
    client = write_app.test_client()
    body = b"---\ntitle: New\n---\n\nnew content\n"
    resp = client.put("/notes/new-page.md", data=body)
    assert resp.status_code == 201
    assert resp.headers["Location"] == "/notes/new-page.md"
    assert (field_path / "new-page.md").read_bytes() == body

    db = index._open_index(index.index_path(field_path))
    row = db.execute("SELECT filename FROM pages WHERE filename = 'new-page.md'").fetchone()
    db.close()
    assert row is not None


def test_put_overwrites_204(write_app, connected, fake_embed):
    _cfg_path, field_path = connected
    client = write_app.test_client()
    old_text = (field_path / "alpha.md").read_text(encoding="utf-8")
    old_uuid = _frontmatter(old_text).get("uuid")

    resp = client.put("/notes/alpha.md", data=b"---\ntitle: New Alpha\n---\n\nreplacement\n")
    assert resp.status_code == 204
    assert "Location" not in resp.headers
    new_text = (field_path / "alpha.md").read_text(encoding="utf-8")
    assert "replacement" in new_text
    assert _frontmatter(new_text)["uuid"] == old_uuid


def test_put_uuid_conflict_409(write_app, connected):
    _cfg_path, field_path = connected
    (field_path / "plain.md").write_text(
        "---\nuuid: 11111111-2222-3333-4444-555555555555\n---\n\noriginal\n",
        encoding="utf-8",
    )
    resp = write_app.test_client().put(
        "/notes/plain.md",
        data=b"---\nuuid: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n---\n\nnew\n",
    )
    assert resp.status_code == 409


def test_put_preserves_stored_uuid(write_app, connected):
    _cfg_path, field_path = connected
    (field_path / "plain.md").write_text(
        "---\nuuid: 11111111-2222-3333-4444-555555555555\n---\n\noriginal\n",
        encoding="utf-8",
    )
    resp = write_app.test_client().put(
        "/notes/plain.md",
        data=b"---\ntitle: New\n---\n\nreplacement\n",
    )
    assert resp.status_code == 204
    text = (field_path / "plain.md").read_text(encoding="utf-8")
    assert _frontmatter(text)["uuid"] == "11111111-2222-3333-4444-555555555555"


def test_put_bad_filename_400(write_app, connected):
    resp = write_app.test_client().put("/notes/Bad Name.md", data=b"x")
    assert resp.status_code == 400


def test_put_empty_body_400(write_app, connected):
    resp = write_app.test_client().put("/notes/new-page.md", data=b"   \n\n")
    assert resp.status_code == 400


def test_put_invalid_utf8_415(write_app, connected):
    resp = write_app.test_client().put("/notes/new-page.md", data=b"\xff\xfe\x00\x01")
    assert resp.status_code == 415


def test_delete_removes_page_and_index_row(write_app, connected, fake_embed):
    _cfg_path, field_path = connected
    index.build_index(transport.local(field_path), index.index_path(field_path), progress=False)
    resp = write_app.test_client().delete("/notes/beta.md")
    assert resp.status_code == 204
    assert not (field_path / "beta.md").exists()

    db = index._open_index(index.index_path(field_path))
    names = {r[0] for r in db.execute("SELECT filename FROM pages")}
    db.close()
    assert "beta.md" not in names


def test_delete_missing_404(write_app, connected):
    resp = write_app.test_client().delete("/notes/nope.md")
    assert resp.status_code == 404


def test_writes_disabled_403(app, connected):
    client = app.test_client()
    resp = client.put("/notes/new-page.md", data=b"x")
    assert resp.status_code == 403
    assert b"writes disabled" in resp.data
    resp = client.delete("/notes/alpha.md")
    assert resp.status_code == 403
    assert b"writes disabled" in resp.data


def test_global_search_tags_and_orders(app, connected, tmp_path, fake_embed):
    _cfg_path, field_dir = connected
    from memoryfield_tool import index as idx

    field2 = tmp_path / "field2"
    field2.mkdir()
    (field2 / "work.md").write_text(
        "---\ntitle: Work\nsummary: Work notes\n---\n\nwork stuff\n", encoding="utf-8"
    )
    config.save_config(
        config.with_field(
            config.load_config(),
            config.Field(name="work", transport="local", location=str(field2)),
        )
    )
    idx.build_index(transport.local(field_dir), idx.index_path(field_dir), progress=False)
    idx.build_index(transport.local(field2), idx.index_path(field2), progress=False)

    app2 = web.create_app(config.load_config())
    resp = app2.test_client().get("/search?p=work")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    results = data["results"]
    assert any(r["filename"] == "work.md" and r["field"] == "work" for r in results)
    assert all("field" in r for r in results)
    distances = [r["score"] for r in results]
    assert distances == sorted(distances, reverse=True)


def test_global_search_missing_p_400(app):
    assert app.test_client().get("/search").status_code == 400


def test_field_search_missing_p_400_route(app):
    assert app.test_client().get("/notes/search").status_code == 400


def _s3_write_app(config_env, allow_writes):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="testbucket")
    conn.put_object(
        Bucket="testbucket",
        Key="prefix/index.md",
        Body=b"---\ntitle: Notes\n---\n\n# Notes\n",
    )
    field = config.Field(name="notes", transport="s3", location="s3://testbucket/prefix")
    config.save_config(config.with_field(config.load_config(), field))
    return conn, web.create_app(config.load_config(), allow_writes=allow_writes)


@mock_aws
def test_s3_put_delete(config_env, fake_embed):
    conn, app = _s3_write_app(config_env, allow_writes=True)
    client = app.test_client()

    resp = client.put("/notes/new-page.md", data=b"---\ntitle: New\n---\n\nnew content\n")
    assert resp.status_code == 201
    keys = [
        o["Key"] for o in conn.list_objects_v2(Bucket="testbucket", Prefix="prefix/")["Contents"]
    ]
    assert "prefix/new-page.md" in keys

    resp = client.delete("/notes/new-page.md")
    assert resp.status_code == 204
    keys = [
        o["Key"] for o in conn.list_objects_v2(Bucket="testbucket", Prefix="prefix/")["Contents"]
    ]
    assert "prefix/new-page.md" not in keys


@mock_aws
def test_s3_writes_disabled(config_env):
    conn, app = _s3_write_app(config_env, allow_writes=False)
    client = app.test_client()
    resp = client.put("/notes/new-page.md", data=b"x")
    assert resp.status_code == 403
    assert b"writes disabled" in resp.data
    resp = client.delete("/notes/index.md")
    assert resp.status_code == 403
