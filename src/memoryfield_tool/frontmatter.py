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


def build_frontmatter(fm: dict[str, object]) -> str:
    dumped = str(yaml.safe_dump(fm, sort_keys=False))
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
