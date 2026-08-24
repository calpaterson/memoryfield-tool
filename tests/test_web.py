import io
import json
import zipfile

import boto3
import pytest
from moto import mock_aws

from memoryfield_tool import assets, config, transport, web


@pytest.fixture
def app(connected):
    _cfg_path, _field_path = connected
    return web.create_app(config.load_config())


def _get(client, url):
    return client.get(url)


def test_landing_lists_field(app, connected):
    _cfg_path, _field_path = connected
    resp = _get(app.test_client(), "/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "/notes/" in html
    assert "notes" in html
    assert "4 pages" in html


def test_unknown_field_404(app):
    assert _get(app.test_client(), "/nope/").status_code == 404
    assert _get(app.test_client(), "/nope/alpha.md").status_code == 404


def test_raw_page_bytes_and_content_type(app, connected):
    _cfg_path, field_path = connected
    resp = _get(app.test_client(), "/notes/alpha.md")
    assert resp.status_code == 200
    assert resp.data == (field_path / "alpha.md").read_bytes()
    assert resp.content_type == "text/markdown; charset=utf-8"


def test_raw_index_md(app, connected):
    _cfg_path, field_path = connected
    resp = _get(app.test_client(), "/notes/index.md")
    assert resp.status_code == 200
    assert resp.data == (field_path / "index.md").read_bytes()


def test_raw_traversal_404(app):
    client = app.test_client()
    assert _get(client, "/notes/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert _get(client, "/notes/alpha.md/..").status_code == 404


def test_raw_symlink_escape_404(app, connected):
    _cfg_path, field_path = connected
    outside = field_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (field_path / "evil.md").symlink_to(outside)
    except OSError, NotImplementedError:
        pytest.skip("symlinks not supported on this platform")
    assert _get(app.test_client(), "/notes/evil.md").status_code == 404


def test_zip_route(app, connected):
    _cfg_path, field_path = connected
    resp = _get(app.test_client(), "/notes.memoryfield.zip")
    assert resp.status_code == 200
    assert resp.content_type == "application/zip"
    assert "attachment; filename=notes.memoryfield.zip" in resp.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
    assert "index.md" in names
    assert "alpha.md" in names


def test_field_without_index_renders_catalog(app, connected):
    _cfg_path, field_path = connected
    (field_path / "index.md").unlink()
    resp = _get(app.test_client(), "/notes/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "alpha.md" in html
    assert "Notes about alpha things." in html


def test_field_with_index_renders_html(app, connected):
    resp = _get(app.test_client(), "/notes/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Free-form intro" in html


def test_page_html_render_title_and_body(app, connected):
    _cfg_path, field_path = connected
    resp = _get(app.test_client(), "/notes/alpha")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Alpha Notes" in html
    assert "Alpha is the first letter." in html


def test_page_html_missing_404(app):
    assert _get(app.test_client(), "/notes/nope").status_code == 404


def test_page_html_link_rewrite(app, connected):
    _cfg_path, field_path = connected
    (field_path / "links.md").write_text(
        "---\ntitle: Links\n---\n\n[x](other.md)\n", encoding="utf-8"
    )
    resp = _get(app.test_client(), "/notes/links")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'href="/notes/other"' in html


def test_nav_lists_both_fields(app, connected, tmp_path):
    _cfg_path, field_dir = connected
    field2 = tmp_path / "field2"
    field2.mkdir()
    (field2 / "work.md").write_text("---\ntitle: Work\n---\n\nwork\n", encoding="utf-8")
    config.save_config(
        config.with_field(
            config.load_config(), config.Field(name="work", transport="local", location=str(field2))
        )
    )
    app2 = web.create_app(config.load_config())
    resp = _get(app2.test_client(), "/notes/alpha")
    html = resp.get_data(as_text=True)
    assert "/notes/" in html
    assert "/work/" in html


def test_pico_href_with_bundled_asset(monkeypatch, tmp_path):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "pico.min.css").write_text("/* pico */", encoding="utf-8")
    monkeypatch.setattr(assets, "_PICO_LOCAL", static_dir / "pico.min.css")
    assert assets.has_bundled_pico() is True
    assert assets.pico_css_href() == "/static/pico.min.css"


def test_pico_href_cdn_fallback(monkeypatch, tmp_path):
    static_dir = tmp_path / "static"
    monkeypatch.setattr(assets, "_PICO_LOCAL", static_dir / "pico.min.css")
    assert assets.has_bundled_pico() is False
    assert assets.pico_css_href() == assets.PICO_CDN_URL


def test_field_search_shape(app, connected, fake_embed):
    _cfg_path, field_path = connected
    from memoryfield_tool import index

    index.build_index(transport.local(field_path), index.index_path(field_path), progress=False)
    resp = _get(app.test_client(), "/notes/search?q=beta")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert set(data.keys()) == {"results"}
    results = data["results"]
    assert len(results) > 0
    r = results[0]
    assert set(r.keys()) == {"filename", "frontmatter", "score"}
    assert any(x["filename"] == "beta.md" for x in results)
    beta = next(x for x in results if x["filename"] == "beta.md")
    assert beta["frontmatter"]["title"] == "Beta Notes"
    assert isinstance(beta["score"], float)


def test_field_search_empty_results(app, connected):
    resp = _get(app.test_client(), "/notes/search?q=zzzz-not-there")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data == {"results": []}


def test_field_search_missing_q_400(app):
    assert _get(app.test_client(), "/notes/search").status_code == 400


def test_field_search_substring_fallback(app, connected):
    _cfg_path, _field_path = connected
    resp = _get(app.test_client(), "/notes/search?q=beta")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    results = data["results"]
    assert any(r["filename"] == "beta.md" for r in results)
    assert all(r["score"] is None for r in results)


@mock_aws
def test_s3_field_serving(config_env):
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="testbucket")
    conn.put_object(
        Bucket="testbucket",
        Key="prefix/index.md",
        Body=b"---\ntitle: Notes\n---\n\n# S3 Notes\n",
    )
    conn.put_object(
        Bucket="testbucket",
        Key="prefix/alpha.md",
        Body=b"---\ntitle: Alpha\n---\n\nalpha body\n",
    )
    field = config.Field(name="notes", transport="s3", location="s3://testbucket/prefix")
    config.save_config(config.with_field(config.load_config(), field))
    app = web.create_app(config.load_config())
    client = app.test_client()

    resp = _get(client, "/notes/")
    assert resp.status_code == 200
    assert b"S3 Notes" in resp.data

    resp = _get(client, "/notes/alpha.md")
    assert resp.status_code == 200
    assert resp.data == b"---\ntitle: Alpha\n---\n\nalpha body\n"
    assert resp.content_type == "text/markdown; charset=utf-8"

    resp = _get(client, "/notes.memoryfield.zip")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
    assert "index.md" in names
    assert "alpha.md" in names

    resp = _get(client, "/notes/search?q=alpha")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert set(data.keys()) == {"results"}
    assert any(r["filename"] == "alpha.md" for r in data["results"])
