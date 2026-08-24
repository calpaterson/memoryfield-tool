# `memoryfield-tool`

A CLI tool for reading, writing and exporting
[memoryfields](https://github.com/calpaterson/memoryfield-spec/blob/main/SPEC.md) —
named collections of Markdown pages with YAML frontmatter and optional vector
indexes.  It is aimed both at human and AI agent users.

For the RFC-style specification of the memoryfield format, see
[SPEC.md](https://github.com/calpaterson/memoryfield-spec/blob/main/SPEC.md).

## Install

```sh
uv tool install .
```

or, from a checkout:

```sh
uv run memoryfield-tool --help
```

Requires Python 3.14.  Semantic search needs a local
[ollama](https://ollama.dev) with `nomic-embed-text` pulled; everything else
works without it (search falls back to substring matching).

## Commands

```
create NAME [--location PATH]     Create a new memoryfield (intro index page)
connect NAME LOCATION             Connect an existing directory as a memoryfield
catalog [--field NAME] [--sort]   List pages with frontmatter metadata
validate [--field NAME]           Check a field against the spec
read [--field NAME] PAGES...      Print pages with line numbers
write [--field NAME] PAGE         Write stdin to a page (background reindex)
index [--field NAME]              Build or update the vector index
search [--field NAME] QUERY       Semantic search (substring fallback)
export [--field NAME]             Write the field as a .memoryfield.zip
```

## Configuration

The config file lives at `~/.config/memoryfield-tool.toml` (override with
`MEMORYFIELD_TOOL_CONFIG`).  It maps memoryfield names to locations:

```toml
[memoryfields.notes]
transport = "local"
location = "/home/me/memoryfields/notes"
```

`create` and `connect` add entries.

## Vector index

Indexing writes `<field>/nomic-embed-text-v1.5.sqlite3` inside the field using
the spec's `pages` schema.  Indexes are derived data and can be regenerated
with `index` at any time.  `search` returns the top 20 nearest pages (cosine
distance shown in the output; no hard distance cutoff).  After each `write`,
the index is rebuilt in the background (a detached process; its stderr goes to
`~/.cache/memoryfield-tool/reindex.log`).

## What's next

A `serve` command (spec data server + HTML rendering) is planned.
