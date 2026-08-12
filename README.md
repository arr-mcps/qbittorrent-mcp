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

One tool per WebUI API endpoint, grouped by API section. Read-only GET endpoints
are marked **R**; mutating POST endpoints are marked **W**; destructive ones
(delete torrents, shutdown, remove categories/tags/rules/search jobs) are marked
**D** and carry warnings in their docstrings.

### Application

| Tool | Endpoint |
|---|---|
| `qbittorrent_app_version` (R) | `GET /api/v2/app/version` |
| `qbittorrent_app_webapi_version` (R) | `GET /api/v2/app/webapiVersion` |
| `qbittorrent_app_build_info` (R) | `GET /api/v2/app/buildInfo` |
| `qbittorrent_app_shutdown` (D) | `POST /api/v2/app/shutdown` |
| `qbittorrent_app_get_preferences` (R) | `GET /api/v2/app/preferences` |
| `qbittorrent_app_set_preferences` (W) | `POST /api/v2/app/setPreferences` |
| `qbittorrent_app_default_save_path` (R) | `GET /api/v2/app/defaultSavePath` |
| `qbittorrent_app_get_cookies` (R) | `GET /api/v2/app/cookies` |
| `qbittorrent_app_set_cookies` (W) | `POST /api/v2/app/setCookies` |

### Auth

| Tool | Endpoint |
|---|---|
| `qbittorrent_logout` (W) | `POST /api/v2/auth/logout` |

### Log

| Tool | Endpoint |
|---|---|
| `qbittorrent_log_main` (R) | `GET /api/v2/log/main` |
| `qbittorrent_log_peers` (R) | `GET /api/v2/log/peers` |

### Sync

| Tool | Endpoint |
|---|---|
| `qbittorrent_sync_maindata` (R) | `GET /api/v2/sync/maindata` |
| `qbittorrent_sync_torrent_peers` (R) | `GET /api/v2/sync/torrentPeers` |

### Transfer

| Tool | Endpoint |
|---|---|
| `qbittorrent_transfer_info` (R) | `GET /api/v2/transfer/info` |
| `qbittorrent_transfer_speed_limits_mode` (R) | `GET /api/v2/transfer/speedLimitsMode` |
| `qbittorrent_transfer_toggle_speed_limits` (W) | `POST /api/v2/transfer/toggleSpeedLimitsMode` |
| `qbittorrent_transfer_download_limit` (R) | `GET /api/v2/transfer/downloadLimit` |
| `qbittorrent_transfer_set_download_limit` (W) | `POST /api/v2/transfer/setDownloadLimit` |
| `qbittorrent_transfer_upload_limit` (R) | `GET /api/v2/transfer/uploadLimit` |
| `qbittorrent_transfer_set_upload_limit` (W) | `POST /api/v2/transfer/setUploadLimit` |
| `qbittorrent_transfer_ban_peers` (W) | `POST /api/v2/transfer/banPeers` |

### Torrent management

| Tool | Endpoint |
|---|---|
| `qbittorrent_torrents_list` (R) | `GET /api/v2/torrents/info` |
| `qbittorrent_torrent_properties` (R) | `GET /api/v2/torrents/properties` |
| `qbittorrent_torrent_trackers` (R) | `GET /api/v2/torrents/trackers` |
| `qbittorrent_torrent_web_seeds` (R) | `GET /api/v2/torrents/webseeds` |
| `qbittorrent_torrent_contents` (R) | `GET /api/v2/torrents/files` |
| `qbittorrent_torrent_piece_states` (R) | `GET /api/v2/torrents/pieceStates` |
| `qbittorrent_torrent_piece_hashes` (R) | `GET /api/v2/torrents/pieceHashes` |
| `qbittorrent_torrents_pause` (W) | `POST /api/v2/torrents/stop` |
| `qbittorrent_torrents_resume` (W) | `POST /api/v2/torrents/start` |
| `qbittorrent_torrents_delete` (D) | `POST /api/v2/torrents/delete` |
| `qbittorrent_torrents_recheck` (W) | `POST /api/v2/torrents/recheck` |
| `qbittorrent_torrents_reannounce` (W) | `POST /api/v2/torrents/reannounce` |
| `qbittorrent_torrents_add` (W) | `POST /api/v2/torrents/add` |
| `qbittorrent_torrents_add_trackers` (W) | `POST /api/v2/torrents/addTrackers` |
| `qbittorrent_torrents_edit_tracker` (W) | `POST /api/v2/torrents/editTracker` |
| `qbittorrent_torrents_remove_trackers` (W) | `POST /api/v2/torrents/removeTrackers` |
| `qbittorrent_torrents_add_peers` (W) | `POST /api/v2/torrents/addPeers` |
| `qbittorrent_torrents_increase_priority` (W) | `POST /api/v2/torrents/increasePrio` |
| `qbittorrent_torrents_decrease_priority` (W) | `POST /api/v2/torrents/decreasePrio` |
| `qbittorrent_torrents_top_priority` (W) | `POST /api/v2/torrents/topPrio` |
| `qbittorrent_torrents_bottom_priority` (W) | `POST /api/v2/torrents/bottomPrio` |
| `qbittorrent_torrents_file_priority` (W) | `POST /api/v2/torrents/filePrio` |
| `qbittorrent_torrents_download_limit` (R) | `POST /api/v2/torrents/downloadLimit` |
| `qbittorrent_torrents_set_download_limit` (W) | `POST /api/v2/torrents/setDownloadLimit` |
| `qbittorrent_torrents_set_share_limits` (W) | `POST /api/v2/torrents/setShareLimits` |
| `qbittorrent_torrents_upload_limit` (R) | `POST /api/v2/torrents/uploadLimit` |
| `qbittorrent_torrents_set_upload_limit` (W) | `POST /api/v2/torrents/setUploadLimit` |
| `qbittorrent_torrents_set_location` (W) | `POST /api/v2/torrents/setLocation` |
| `qbittorrent_torrents_set_name` (W) | `POST /api/v2/torrents/rename` |
| `qbittorrent_torrents_set_category` (W) | `POST /api/v2/torrents/setCategory` |
| `qbittorrent_torrents_categories` (R) | `GET /api/v2/torrents/categories` |
| `qbittorrent_torrents_create_category` (W) | `POST /api/v2/torrents/createCategory` |
| `qbittorrent_torrents_edit_category` (W) | `POST /api/v2/torrents/editCategory` |
| `qbittorrent_torrents_remove_categories` (W) | `POST /api/v2/torrents/removeCategories` |
| `qbittorrent_torrents_add_tags` (W) | `POST /api/v2/torrents/addTags` |
| `qbittorrent_torrents_remove_tags` (W) | `POST /api/v2/torrents/removeTags` |
| `qbittorrent_torrents_tags` (R) | `GET /api/v2/torrents/tags` |
| `qbittorrent_torrents_create_tags` (W) | `POST /api/v2/torrents/createTags` |
| `qbittorrent_torrents_delete_tags` (W) | `POST /api/v2/torrents/deleteTags` |
| `qbittorrent_torrents_set_auto_management` (W) | `POST /api/v2/torrents/setAutoManagement` |
| `qbittorrent_torrents_toggle_sequential_download` (W) | `POST /api/v2/torrents/toggleSequentialDownload` |
| `qbittorrent_torrents_toggle_first_last_piece_priority` (W) | `POST /api/v2/torrents/toggleFirstLastPiecePrio` |
| `qbittorrent_torrents_set_force_start` (W) | `POST /api/v2/torrents/setForceStart` |
| `qbittorrent_torrents_set_super_seeding` (W) | `POST /api/v2/torrents/setSuperSeeding` |
| `qbittorrent_torrents_rename_file` (W) | `POST /api/v2/torrents/renameFile` |
| `qbittorrent_torrents_rename_folder` (W) | `POST /api/v2/torrents/renameFolder` |

`qbittorrent_torrent_properties` is the key observability tool: it returns
`seeding_time`, `share_ratio`, `total_uploaded`, `save_path`, and friends for a
single torrent hash.

### RSS

| Tool | Endpoint |
|---|---|
| `qbittorrent_rss_add_folder` (W) | `POST /api/v2/rss/addFolder` |
| `qbittorrent_rss_add_feed` (W) | `POST /api/v2/rss/addFeed` |
| `qbittorrent_rss_remove_item` (D) | `POST /api/v2/rss/removeItem` |
| `qbittorrent_rss_move_item` (W) | `POST /api/v2/rss/moveItem` |
| `qbittorrent_rss_items` (R) | `GET /api/v2/rss/items` |
| `qbittorrent_rss_mark_as_read` (W) | `POST /api/v2/rss/markAsRead` |
| `qbittorrent_rss_refresh_item` (W) | `POST /api/v2/rss/refreshItem` |
| `qbittorrent_rss_set_rule` (W) | `POST /api/v2/rss/setRule` |
| `qbittorrent_rss_rename_rule` (W) | `POST /api/v2/rss/renameRule` |
| `qbittorrent_rss_remove_rule` (D) | `POST /api/v2/rss/removeRule` |
| `qbittorrent_rss_rules` (R) | `GET /api/v2/rss/rules` |
| `qbittorrent_rss_matching_articles` (R) | `GET /api/v2/rss/matchingArticles` |

### Search

| Tool | Endpoint |
|---|---|
| `qbittorrent_search_start` (W) | `POST /api/v2/search/start` |
| `qbittorrent_search_stop` (W) | `POST /api/v2/search/stop` |
| `qbittorrent_search_status` (R) | `GET /api/v2/search/status` |
| `qbittorrent_search_results` (R) | `GET /api/v2/search/results` |
| `qbittorrent_search_delete` (D) | `POST /api/v2/search/delete` |
| `qbittorrent_search_plugins` (R) | `GET /api/v2/search/plugins` |
| `qbittorrent_search_install_plugin` (W) | `POST /api/v2/search/installPlugin` |
| `qbittorrent_search_uninstall_plugin` (W) | `POST /api/v2/search/uninstallPlugin` |
| `qbittorrent_search_enable_plugin` (W) | `POST /api/v2/search/enablePlugin` |
| `qbittorrent_search_update_plugins` (W) | `POST /api/v2/search/updatePlugins` |

### Write & destructive tools

Unlike tracearr-mcp, this server exposes qBittorrent's full read+write surface.
Destructive tools (`qbittorrent_app_shutdown`, `qbittorrent_torrents_delete`,
`qbittorrent_rss_remove_item`, `qbittorrent_rss_remove_rule`,
`qbittorrent_search_delete`) are annotated `destructiveHint` so clients can gate
them, and their docstrings call out the irreversible parts (e.g. `delete_files`
in `qbittorrent_torrents_delete`). Everything else that mutates state is a plain
write tool.

### Notes

- Many write tools take a `hashes` argument: pass one hash, several separated by
  `|`, or `all` for every torrent.
- qBittorrent 5.0 renamed a few endpoints versus 4.x: pause is `/torrents/stop`,
  resume is `/torrents/start`, and rename torrent is `/torrents/rename`. This
  server targets qBittorrent >= 5.0.
- `qbittorrent_torrents_add` accepts newline-separated magnet/URLs in `urls`, or
  a single base64-encoded `.torrent` file in `torrent_b64`.
- API-key auth cannot hit `/auth/*` endpoints (including logout) — qBittorrent
  rejects those, and the error is surfaced as-is.

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
