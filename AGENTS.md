# AGENTS.md — qbittorrent-mcp

MCP server exposing qBittorrent's WebUI API v2 (qBittorrent >= 5.0 wiki spec) as
tools so an LLM can manage torrents: list, properties/trackers/files, add/pause/
resume/delete, categories, tags, RSS and search, plus application settings. Uses
FastMCP, `uv` for deps. Unlike tracearr-mcp this server is read+write.

## Testing
- Offline suite: `make test` (or `uv run pytest`)
- Live integration (needs `QBITTORRENT_URL` plus API key or username/password): `make test-integration`

## Release workflow
Always use the `make bump-*` targets to bump the version (`uv version --bump patch|minor|major`), which updates `pyproject.toml` and `uv.lock` together. Do NOT edit the version by hand.

- Bump: `make bump-patch` (or `bump-minor` / `bump-major`)
- Commit message is **just the version**, e.g. `0.1.2` — nothing else.
- Tag it `v<version>` (e.g. `v0.1.2`).
- Push main and the tag:
  ```
  git push origin main
  git push origin v<version>
  ```
- If a copy is synced under the christopfarr project or deployed to the Proxmox host, follow the pattern in the other `-mcp` servers: sync the project copy, then `ssh root@192.168.50.3 -- 'cd /root/qbittorrent-mcp && git fetch origin && git reset --hard origin/main && uv tool install --force .'`.

## Auth note
Two auth modes, auto-selected in `main()`: if `QBITTORRENT_API_KEY` is set it's
sent as `Authorization: Bearer <key>` (needs qBittorrent >= v5.2.0 / WebAPI
v2.14.1). Otherwise `QBITTORRENT_USERNAME`/`QBITTORRENT_PASSWORD` are used: the
first request lazily POSTs `/auth/login` (with a `Referer` header, which
qBittorrent requires) and httpx's cookie jar carries the SID. A 401/403
mid-session triggers one re-login and a single retry (`_req`); with API-key auth
there is no retry. Keep this behaviour intact in `_req`/`_login`/`_ensure_authed`.

## Design notes
- Keep the whole server in `qbittorrent_mcp.py` unless it outgrows it; one tool
  per endpoint with the `qbittorrent_` prefix. Base path `/api/v2` is hardcoded
  in `build_client`.
- Targets the qBittorrent >= 5.0 WebUI API. Note the 5.0 renames: pause is
  `/torrents/stop`, resume is `/torrents/start`, rename torrent is
  `/torrents/rename`. Do not reintroduce the 4.x names.
- GET endpoints take query params; mutating POST endpoints take form-encoded
  bodies via httpx `data=`. Only `setPreferences`/`setCookies`/RSS `setRule` send
  a `json` form field (JSON-encoded string). `torrents/add` file upload uses
  httpx `files=` with field name `torrents`.
- Response decoding: respect content-type in `_decode` — plain-text "Ok." bodies
  and bare int limits must not go through `r.json()`.
- Tool annotations: `READONLY` (readOnlyHint) for GET, `DESTRUCTIVE`
  (destructiveHint) for delete/shutdown/remove*, `WRITE` for other mutators.
  Destructive docstrings must warn about irreversible parts (e.g. delete_files).
- Return types must be concrete (`JSONObj`/`JSONArr`/`str`/`int`), never bare
  `Any` — bare `Any` makes Client.call_tool's `.data` come back None.
