from datetime import date, datetime

import yaml


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter block without markers, body), or (None, text) if no block."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5 :]


def parse_frontmatter(text: str) -> tuple[dict[str, object] | None, bool]:
    if not text.startswith("---\n"):
        return None, False
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, True
    block = text[4:end]
    try:
        result = yaml.safe_load(block)
    except yaml.YAMLError:
        return None, True
    if result is None:
        return {}, True
    if not isinstance(result, dict):
        return {}, True
    return result, True


def page_body(text: str) -> str:
    """The body after a leading frontmatter block, or the whole text when there is none."""
    return _split_frontmatter(text)[1]


def build_frontmatter(fm: dict[str, object]) -> str:
    normalized = dict(fm)
    for field in ("created", "updated"):
        value = normalized.get(field)
        if isinstance(value, (date, datetime)):
            normalized[field] = value.isoformat()
    dumped = str(yaml.safe_dump(normalized, sort_keys=False))
    return "---\n" + dumped + "---\n"


def get_frontmatter_field(text: str, field: str) -> object | None:
    fm, _has = parse_frontmatter(text)
    if fm is None:
        return None
    return fm.get(field)


def set_frontmatter_field(text: str, field: str, value: object) -> str:
    block, body = _split_frontmatter(text)
    if block is None:
        return build_frontmatter({field: value}) + text
    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError:
        parsed = None
    updated: dict[str, object] = parsed if isinstance(parsed, dict) else {}
    updated[field] = value
    return build_frontmatter(updated) + body


def fill_frontmatter(
    text: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    uuid: str | None = None,
    created: str | None = None,
    updated: str | None = None,
    preserve: dict[str, object] | None = None,
    title_fallback: str | None = None,
    refresh_updated: bool = False,
) -> str:
    """Fill missing frontmatter keys, never clobbering present ones.

    Only missing keys are filled, per-key precedence (first match wins):
      - uuid/created/updated: incoming > stored (preserve) > supplied value
      - title: incoming > title flag > stored (preserve) > title_fallback
      - summary: incoming > summary flag > stored (preserve); never inferred

    When ``refresh_updated`` is True and a non-None ``updated`` is supplied,
    ``updated`` is overridden unconditionally (incoming > stored > present);
    ``uuid``/``created``/``title``/``summary`` keep the never-clobber contract.

    Malformed or unclosed frontmatter is left byte-untouched. When nothing is
    missing and no fill values apply, the text is returned unchanged.
    """
    fm, has_markers = parse_frontmatter(text)
    if fm is None and has_markers:
        return text
    src = fm if fm is not None else {}
    _block, body = _split_frontmatter(text)
    base = preserve if preserve is not None else {}

    fills: dict[str, object] = {}
    if src.get("uuid") is None:
        if base.get("uuid") is not None:
            fills["uuid"] = base["uuid"]
        elif uuid is not None:
            fills["uuid"] = uuid
    if src.get("created") is None:
        if base.get("created") is not None:
            fills["created"] = base["created"]
        elif created is not None:
            fills["created"] = created
    if refresh_updated:
        if updated is not None:
            fills["updated"] = updated
    elif src.get("updated") is None:
        if base.get("updated") is not None:
            fills["updated"] = base["updated"]
        elif updated is not None:
            fills["updated"] = updated
    if src.get("title") is None:
        if title is not None:
            fills["title"] = title
        elif base.get("title") is not None:
            fills["title"] = base["title"]
        elif title_fallback is not None:
            fills["title"] = title_fallback
    if src.get("summary") is None:
        if summary is not None:
            fills["summary"] = summary
        elif base.get("summary") is not None:
            fills["summary"] = base["summary"]

    if not fills:
        return text
    merged = dict(src)
    merged.update(fills)
    return build_frontmatter(merged) + body
