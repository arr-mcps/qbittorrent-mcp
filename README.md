# qbittorrent-mcp

Part of the [arr-mcps](https://github.com/SavageCore/arr-mcps) collection.
MCP server exposing [qBittorrent](https://github.com/qbittorrent/qBittorrent)'s
WebUI API v2 (qBittorrent >= 5.0) as tools, so an LLM can manage your torrents:
list, inspect properties/trackers/files, add/pause/resume/delete torrents,
manage categories, tags, RSS feeds and search plugins, and tweak application
settings.

Built with [FastMCP](https://gofastmcp.com).

## Enabling the API on your qBittorrent server

The WebUI API is enabled by default with the WebUI. You need WebUI access
enabled (Tools > Preferences > WebUI) and one of two auth methods:

- **API key** (qBittorrent >= v5.2.0 / WebAPI v2.14.1): generate one in
  **Preferences > WebUI > API Key** (format `qbt_<28 chars>`). This is the
  recommended, stateless option.
- **Username/password**: the WebUI login you'd use in the browser. Works on all
  versions.

## Install

Download a wheel from the [latest release](https://github.com/SavageCore/qbittorrent-mcp/releases/latest)
and install it as a `uv` tool (no repo checkout needed):

```bash
uv tool install qbittorrent_mcp-*.whl
```

This puts a `qbittorrent-mcp` command on your PATH. Register it with Claude Code:

```bash
claude mcp add qbittorrent \
  --env QBITTORRENT_URL=http://localhost:8080 \
  --env QBITTORRENT_API_KEY=<key> \
  -- qbittorrent-mcp
```

Or with username/password:

```bash
claude mcp add qbittorrent \
  --env QBITTORRENT_URL=http://localhost:8080 \
  --env QBITTORRENT_USERNAME=admin \
  --env QBITTORRENT_PASSWORD=<password> \
  -- qbittorrent-mcp
```

### From source

```bash
uv sync
cp .env.example .env   # fill in QBITTORRENT_URL and an auth method
```

```bash
claude mcp add qbittorrent \
  --env QBITTORRENT_URL=http://localhost:8080 \
  --env QBITTORRENT_API_KEY=<key> \
  -- uv run --directory /path/to/qbittorrent-mcp qbittorrent-mcp
```

## Config

| Env var | Required | Default |
|---|---|---|
| `QBITTORRENT_URL` | yes | - |
| `QBITTORRENT_API_KEY` | one of\* | none (preferred) |
| `QBITTORRENT_USERNAME` | one of\* | none (fall-back) |
| `QBITTORRENT_PASSWORD` | one of\* | none (fall-back) |

\* You must set either `QBITTORRENT_API_KEY` or both `QBITTORRENT_USERNAME` and
`QBITTORRENT_PASSWORD`. If `QBITTORRENT_API_KEY` is set it wins; otherwise the
server logs in with the username/password on first use and reuses the session
cookie, re-authenticating automatically if it expires.

## Tools

**10 resource-scoped tools**, each covering multiple qBittorrent WebUI
API v2 endpoints (90 total) via an `operation` parameter. Call a tool
with `operation` set to one of its listed operations and an `arguments`
dict matching that operation's parameters — the tool's own description
(visible to your MCP client) lists every operation, its signature, and a
one-line doc. This keeps the full API surface available while costing a
fraction of the context budget of registering all 90 endpoints as
separate tools.

| Tool | Operations | Kind |
|---|---|---|
| `qbittorrent_torrents` | 22 | reads + writes |
| `qbittorrent_torrent_limits` | 14 | reads + writes |
| `qbittorrent_rss` | 12 | reads + writes |
| `qbittorrent_categories_tags` | 10 | reads + writes |
| `qbittorrent_search` | 10 | reads + writes |
| `qbittorrent_application` | 9 | reads + writes |
| `qbittorrent_transfer` | 8 | reads + writes |
| `qbittorrent_log` | 2 | read-only |
| `qbittorrent_sync` | 2 | read-only |
| `qbittorrent_auth` | 1 | reads + writes |

Example: `qbittorrent_torrents(operation="qbittorrent_torrents_pause", arguments={"hashes": "abc123"})`.
Endpoint-level naming (`qbittorrent_<verb>_<resource>`) is preserved as the
`operation` value, so the full endpoint list is still discoverable from each
group tool's description at runtime.

## Development

```bash
make help  # list all commands
```

| Command | Does |
|---|---|
| `make sync` | `uv sync` |
| `make test` | Offline tests - one per endpoint, mocked HTTP |
| `make test-integration` | Tests against the live instance (needs `QBITTORRENT_URL` + auth env) |
| `make build` | Build wheel + sdist into `dist/` |
| `make bump-patch` / `bump-minor` / `bump-major` | Bump the version in `pyproject.toml` + `uv.lock` |
| `make clean` | Remove build artifacts |

The release workflow (`.github/workflows/release.yml`) builds and publishes to
[Releases](https://github.com/SavageCore/qbittorrent-mcp/releases) whenever a `v*`
tag is pushed - so the usual flow is `make bump-patch`, commit, then tag and
push.

The integration suite is read-only and never modifies your qBittorrent instance.
