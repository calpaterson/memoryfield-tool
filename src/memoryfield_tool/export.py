import io
import zipfile
from pathlib import Path

import click

from . import config, fields


def export_field(field: config.Field, out: Path | io.BytesIO) -> None:
    """Write the field as a .memoryfield.zip to a Path or binary file-like."""
    if isinstance(out, Path):
        out = out.expanduser()
        if field.transport == "local" and out.resolve().is_relative_to(fields.field_root(field)):
            raise click.ClickException(
                "refusing to write the export inside the field being exported"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
    t = fields.get_transport(field)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for info in t.list_objects(recursive=True):
            zi = zipfile.ZipInfo(info.key, date_time=info.last_modified.timetuple()[:6])
            zf.writestr(zi, t.read_object(info.key), compress_type=zipfile.ZIP_DEFLATED)
