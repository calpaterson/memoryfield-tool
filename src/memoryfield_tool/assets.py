from pathlib import Path

PICO_CDN_URL = "https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css"
_PICO_LOCAL = Path(__file__).parent / "static" / "pico.min.css"


def has_bundled_pico() -> bool:
    """True when the build hook produced the bundled pico.min.css (absent in dev)."""
    return _PICO_LOCAL.is_file()


def pico_css_href() -> str:
    """The stylesheet URL: bundled asset when present, else the pinned CDN fallback."""
    if has_bundled_pico():
        return "/static/pico.min.css"
    return PICO_CDN_URL
