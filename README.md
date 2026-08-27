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
connect NAME LOCATION             Connect an existing directory (or s3:// URI)
                                  as a memoryfield
disconnect NAME                Remove a memoryfield from the config (data is
                                  left in place)
catalog [--field NAME] [--sort]   List pages with frontmatter metadata
fields                        List connected fields (name, transport,
                                location, and index.md title)
validate [--field NAME]           Check a field against the spec
read [--field NAME] PAGES...      Print pages with line numbers
edit [--field NAME] PAGE          Open a page in $EDITOR and write it back
write [--field NAME] PAGE         Write stdin to a page (auto frontmatter;
                                  background reindex)
delete [--field NAME] PAGE        Delete a page
path [--field NAME] [PAGE]    Print a field's root path, or a page's full path
rename [--field NAME] OLD NEW Rename a page (preserves uuid/created, refreshes
                              updated; background reindex)
new TITLE [--field NAME] [--name PAGE]   Create a page (generated frontmatter,
                                  slugified filename)
index [--field NAME]              Build or update the vector index
search [--field NAME] QUERY       Semantic search (substring fallback)
export [--field NAME]             Write the field as a .memoryfield.zip
serve [--port N] [--host H]       Serve all fields over HTTP (spec data
      [--allow-writes] [--open]     server + HTML renderer)
```

Commands that act on multiple fields (search, catalog, validate, index,
export) skip unreachable fields with an `error: memoryfield <name>` warning on
stderr instead of aborting; use `disconnect` to drop a stale field.

### Agent-friendly page creation

`write` fills missing frontmatter (`uuid`, `created`, `updated`; `title` from
the filename stem) — no `uuidgen`, no hand-built YAML.  A summary is never
inferred; pass `--summary` to set one.  `write --force` preserves the stored
`uuid`/`created`/`title` and refreshes `updated` (pass `--title` to override)
and rejects a conflicting incoming `uuid`.  `validate --fix` rewrites pages
whose `created`/`updated` are unquoted datetimes, normalizing them to quoted
strings and refreshing `updated`.  `new`
derives the page filename from the title (`--name` overrides) and prints the
created page + uuid.  `memoryfield-tool --schema` prints the full command
reference (commands, flags, defaults, choices) as JSON for agents to
introspect at runtime.

## S3-compatible stores

Fields may live on any S3-compatible object store (AWS S3, Google Cloud
Storage's S3-compatible XML API, MinIO, Cloudflare R2) by connecting a
`s3://bucket/prefix` location:

```sh
memoryfield-tool connect cadentia s3://cadentia-bucket/cadentia \
  --endpoint-url https://storage.googleapis.com --region auto
memoryfield-tool create cadentia --location s3://cadentia-bucket/cadentia \
  --endpoint-url https://storage.googleapis.com
```

- **AWS** uses the default endpoint, so `--endpoint-url` is optional; credentials
  come from the standard `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (and
  `AWS_REGION`) environment variables.
- Credentials can instead be stored per-field in the config: set
  `aws_access_key_id`, `aws_secret_access_key` and (optionally)
  `aws_session_token` for a field via the `connect`/`create` flags
  `--aws-access-key-id`, `--aws-secret-access-key` and `--aws-session-token`.
  Configured keys take precedence over the boto3 default credential chain (env
  vars, `~/.aws/`, IAM roles); keys left unset fall back to that chain.
  `aws_access_key_id` and `aws_secret_access_key` must be set together (the
  session token is optional).  Note that `~/.config/memoryfield-tool.toml` is
  plaintext — when keys are stored there, run
  `chmod 600 ~/.config/memoryfield-tool.toml` and prefer the env/chain approach
  in shared or CI environments.
- **GCS** exposes an S3-compatible API at
  `https://storage.googleapis.com`; create HMAC keys in the GCS console and set
  them in the same `AWS_` environment variables, then pass
  `--endpoint-url https://storage.googleapis.com`.  The `region` defaults to
  `"auto"` automatically for the GCS endpoint (boto3 needs it for signature
  generation); pass `--region` to override.
- The `endpoint_url` and `region` choices are persisted per-field in the config
  and can be overridden at any time.
- `connect` probes the bucket at startup (fail-fast on bad credentials); `serve`
  probes every connected bucket before serving.
- Every command (`read`, `write`, `catalog`, `validate`, `index`, `search`,
  `export`) and the HTTP routes work identically for local and s3 fields.
- `write --append` on s3 is a read-modify-write (S3 has no native append), so
  concurrent appends can lose data; prefer `write --force` (PUT) for anything
  contended.
- `edit` opens any page in $EDITOR (falling back to $VISUAL, then vi) and
  writes back on save; s3 pages are downloaded to a temp file and uploaded
  through the same validation as write. The editor must block until you save
  and quit (e.g. 'code -w', not bare 'code').

## Serving over HTTP (`serve`)

`serve` runs a Flask app (via waitress) for every connected memoryfield,
exposing both the spec's writable data-server endpoints and an awiki-style HTML
renderer.  Field names from the config namespace the routes:

| Route                  | Method | Description                                    |
|------------------------|--------|------------------------------------------------|
| `/`                    | GET    | Landing page listing every field               |
| `/{field}/`            | GET    | Rendered `index.md`, or a catalog listing      |
| `/{field}/{page}`      | GET    | Rendered page HTML                             |
| `/{field}/{page}.md`   | GET    | Raw page bytes (`text/markdown`)               |
| `/{field}.memoryfield.zip` | GET | Full field snapshot as a zip                |
| `/{field}/search?q=`   | GET    | Field-scoped search JSON (`results` array)     |
| `/search?q=`           | GET    | Global search across all fields (results gain `field`) |
| `/{field}/{page}.md`   | PUT    | Create (201) or replace (204) a page           |
| `/{field}/{page}.md`   | DELETE | Remove a page and its index entries (204)      |

Flags:

- `--port N` — default `6211`.
- `--host H` — default `127.0.0.1`.
- `--allow-writes` — enable `PUT`/`DELETE`.  No authentication is implemented,
  so writes are refused unless the host is loopback (`127.0.0.1`, `localhost`,
  `::1`); `--allow-writes` with any other host refuses to start.
- `--open` — open the landing page in a browser.

Notes:

- The config is snapshotted at startup — connect a new field and restart to
  serve it.  `serve` never touches `last_used` (the config stays CLI-owned).
- s3 pages are read live with no caching in v1 (ETag/Last-Modified caching is
  future work).  Buckets are probed at startup, so an unreachable bucket refuses
  to start `serve` rather than 500ing per request.
- A page literally named `search` is shadowed for HTML rendering (the search
  route wins); it is still available raw at `/{field}/search.md`.  Field names
  `search` and `static` are likewise reserved.
- The renderer bundles pico.css at build time (sha256-pinned, never checked
  into git); in a source checkout it falls back to the pinned CDN URL.
- `PUT` reindexes the page synchronously; `DELETE` drops its index rows.  As in
  the CLI, an unavailable embedding model degrades silently to substring
  search.

## Configuration

The config file lives at `~/.config/memoryfield-tool.toml` (override with
`MEMORYFIELD_TOOL_CONFIG`).  It maps memoryfield names to locations:

```toml
[memoryfields.notes]
transport = "local"
location = "/home/me/memoryfields/notes"

[memoryfields.cadentia]
transport = "s3"
location = "s3://cadentia-bucket/cadentia"
endpoint_url = "https://storage.googleapis.com"
region = "auto"
```

`create` and `connect` add entries; `endpoint_url` and `region` are emitted only
when set (legacy configs stay byte-compatible).

## Vector index

Local fields index to `<field>/nomic-embed-text-v1.5.sqlite3` inside the field;
s3 fields index to `~/.cache/memoryfield-tool/indexes/<field>.sqlite3` on the
local machine.  Both use the spec's `pages` schema.  Indexes are derived data
and can be regenerated with `index` at any time — the cache-dir index is
machine-local, so it is not shared across machines (run `index` on each one) and
is not included in exports.  `search` returns the top 20 nearest pages (cosine
distance shown in the output; no hard distance cutoff).  After each `write`,
the index is rebuilt in the background (a detached process; its stderr goes to
`~/.cache/memoryfield-tool/reindex.log`).
