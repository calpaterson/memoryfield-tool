import zipfile
from pathlib import Path

import click

from . import config, fields, pages


def export_field(field: config.Field, out_path: Path) -> Path:
    root = fields.field_root(field)
    out = out_path.expanduser()
    out_resolved = out.resolve()
    if out_resolved.is_relative_to(root):
        raise click.ClickException("refusing to write the export inside the field being exported")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in pages.collect_all_files(root):
            zf.write(f, f.relative_to(root))
    return out
