import io
import json
import re
from pathlib import Path

from flask import Flask, Response, abort, render_template_string, request, send_from_directory
from markdown import markdown

from . import assets, catalog, config, export, fields, frontmatter, index, pages, search

MD_LINK_RE = re.compile(r'href="([^"]+?)\.md(#?)"')
_TEMPLATE_FILE = Path(__file__).parent / "templates" / "base.html"
TEMPLATE = _TEMPLATE_FILE.read_text("utf-8")

_WRITES_DISABLED = "writes disabled (serve with --allow-writes)"


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, default=str)


def _page_body(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def create_app(cfg: config.Config, *, allow_writes: bool = False) -> Flask:
    field_list = fields.connected_fields(cfg, None)
    nav_fields = [f.name for f in field_list]
    transports = {f.name: fields.get_transport(f) for f in field_list}
    index_locs = {f.name: fields.index_location(f) for f in field_list}

    def _field_or_404(name: str) -> config.Field:
        field = cfg.fields.get(name)
        if field is None:
            abort(404)
        return field

    def render_page(field: config.Field, page_name: str) -> str | None:
        """Render a markdown page as HTML, or None when missing."""
        t = transports[field.name]
        filename = f"{page_name}.md"
        if not pages.is_page_filename(filename):
            return None
        if not t.exists(filename):
            return None
        text = t.read_object(filename).decode("utf-8")
        fm, _has = frontmatter.parse_frontmatter(text)
        html = markdown(_page_body(text), extensions=["fenced_code", "tables"])
        html = MD_LINK_RE.sub(rf'href="/{field.name}/\1\2"', html)
        title = (fm or {}).get("title", Path(filename).stem)
        return render_template_string(
            TEMPLATE,
            field=field.name,
            title=title,
            fm=fm,
            content=html,
            pico_css=assets.pico_css_href(),
            nav_fields=nav_fields,
        )

    def render_catalog(field: config.Field) -> str:
        t = transports[field.name]
        rows = catalog.catalog_field(t, field_name=field.name)
        md = catalog.catalog_markdown(rows, show_field=False)
        html = markdown(md, extensions=["fenced_code", "tables"])
        return render_template_string(
            TEMPLATE,
            field=field.name,
            title=f"Index of /{field.name}",
            fm=None,
            content=html,
            pico_css=assets.pico_css_href(),
            nav_fields=nav_fields,
        )

    app = Flask(__name__)

    if assets.has_bundled_pico():

        @app.route("/static/pico.min.css")
        def pico_css() -> Response:
            static_dir = Path(__file__).parent / "static"
            return send_from_directory(static_dir, "pico.min.css")

    @app.route("/")
    def landing() -> str:
        items = []
        for f in field_list:
            t = transports[f.name]
            count = len(pages.collect_pages(t))
            items.append(f'<li><a href="/{f.name}/">{f.name}</a> — {count} pages</li>')
        content = "<h1>Memoryfields</h1><ul>" + "".join(items) + "</ul>"
        return render_template_string(
            TEMPLATE,
            field=None,
            title="Memoryfields",
            fm=None,
            content=content,
            pico_css=assets.pico_css_href(),
            nav_fields=nav_fields,
        )

    @app.route("/<field>/", strict_slashes=False)
    def field_index(field: str) -> str:
        f = _field_or_404(field)
        t = transports[f.name]
        if t.exists("index.md"):
            result = render_page(f, "index")
            if result is None:
                abort(404)
            return result
        return render_catalog(f)

    @app.route("/<field>/<page>.md", methods=["GET", "PUT", "DELETE"])
    def page_raw(field: str, page: str) -> Response:
        f = _field_or_404(field)
        t = transports[f.name]
        filename = f"{page}.md"

        if request.method == "GET":
            if not pages.is_page_filename(filename):
                abort(404)
            if not t.exists(filename):
                abort(404)
            return Response(t.read_object(filename), content_type="text/markdown; charset=utf-8")

        if not allow_writes:
            return Response(_WRITES_DISABLED, status=403)

        if not pages.is_page_filename(filename):
            return Response("invalid page filename", status=400)

        if request.method == "PUT":
            body = request.get_data()
            try:
                result = pages.write_page(
                    t, filename, body, force=True, title_fallback=filename.removesuffix(".md")
                )
            except pages.InvalidFilename:
                return Response("invalid page filename", status=400)
            except pages.EmptyBody:
                return Response("refusing to write an empty page", status=400)
            except pages.InvalidUtf8:
                return Response("body is not valid UTF-8", status=415)
            except pages.UuidConflict:
                return Response("uuid conflict", status=409)
            resp = Response(status=201 if result.created else 204)
            if result.created:
                resp.headers["Location"] = f"/{f.name}/{filename}"
            index.reindex_page(t, index_locs[f.name], filename)
            return resp

        if not t.exists(filename):
            return Response("page not found", status=404)
        t.delete_object(filename)
        index.delete_page(index_locs[f.name], filename)
        return Response(status=204)

    @app.route("/<field>/<page>")
    def page_html(field: str, page: str) -> str:
        f = _field_or_404(field)
        result = render_page(f, page)
        if result is None:
            abort(404)
        return result

    @app.route("/<field>.memoryfield.zip")
    def zip_field(field: str) -> Response:
        f = _field_or_404(field)
        buf = io.BytesIO()
        export.export_field(f, buf)
        resp = Response(buf.getvalue(), content_type="application/zip")
        resp.headers["Content-Disposition"] = f"attachment; filename={f.name}.memoryfield.zip"
        return resp

    @app.route("/<field>/search")
    def field_search(field: str) -> Response:
        f = _field_or_404(field)
        q = request.args.get("q")
        if not q:
            return Response(status=400)
        t = transports[f.name]
        results = search.search_field(t, index_locs[f.name], q)
        payload = [
            {
                "filename": r.filename,
                "frontmatter": r.frontmatter,
                "score": round(1 - r.distance, 4) if r.distance is not None else None,
            }
            for r in results
        ]
        return Response(_json_dumps({"results": payload}), content_type="application/json")

    @app.route("/search")
    def global_search() -> Response:
        q = request.args.get("q")
        if not q:
            return Response(status=400)
        results, _errors = search.search_all(field_list, q)
        results.sort(key=lambda t: t[1].distance if t[1].distance is not None else float("inf"))
        payload = [
            {
                "filename": r.filename,
                "frontmatter": r.frontmatter,
                "score": round(1 - r.distance, 4) if r.distance is not None else None,
                "field": fname,
            }
            for fname, r in results
        ]
        return Response(_json_dumps({"results": payload}), content_type="application/json")

    return app
