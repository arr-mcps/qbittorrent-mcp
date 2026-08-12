"""MCP server exposing qBittorrent's WebUI API v2 (https://github.com/qbittorrent/qBittorrent) as tools.

One tool per endpoint (see README for the full list). Targets the qBittorrent >= 5.0
WebUI API (wiki page "WebUI API (qBittorrent 5.0)"). Unlike tracearr-mcp this server
is read+write: the qBittorrent API has a full write surface, so tools are annotated
readOnlyHint, destructiveHint, or plain write accordingly.

Auth is automatic:
  - If QBITTORRENT_API_KEY is set (format `qbt_<28 chars>`, qBittorrent >= v5.2.0 /
    WebAPI v2.14.1), it is sent as `Authorization: Bearer <key>` on every request.
  - Otherwise QBITTORRENT_USERNAME/QBITTORRENT_PASSWORD are used: the first request
    lazily POSTs /auth/login (with a matching Referer header, which qBittorrent
    requires) and httpx's cookie jar carries the SID cookie from then on. If a 403
    shows up mid-session the client re-logs-in once and retries.

Base path /api/v2 is hardcoded in build_client. GET endpoints take query params;
mutating POST endpoints take form-encoded bodies (httpx data=). Note the qBittorrent
5.0 renames: pause is /torrents/stop, resume is /torrents/start, rename torrent is
/torrents/rename.
"""

import base64
import os
import sys
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

READONLY = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

# Concrete return types (not bare `Any`) matter: FastMCP needs a schema to build
# structured content and skips that step for `Any`, which silently makes
# Client.call_tool's `.data` come back None (see tracearr_mcp for the same note).
JSONObj = dict[str, Any]
JSONArr = list[Any]
JSONVal = JSONObj | JSONArr

mcp = FastMCP("qbittorrent-mcp")

_client: httpx.AsyncClient | None = None
_base_url = ""
_api_key: str | None = None
_username: str | None = None
_password: str | None = None
_logged_in = False


def build_client(
    base_url: str,
    api_key: str | None = None,
    username: str | None = None,
    password: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/api/v2",
        headers=headers,
        transport=transport,
    )


async def _login() -> None:
    global _logged_in
    assert _client is not None and _username is not None
    r = await _client.post(
        "/auth/login",
        data={"username": _username, "password": _password},
        headers={"Referer": _base_url},
    )
    if r.status_code == 403:
        raise ToolError("qBittorrent login failed: IP banned (too many failed login attempts)")
    if r.status_code >= 400:
        raise ToolError(f"qBittorrent login failed: HTTP {r.status_code}")
    if "SID" not in _client.cookies:
        raise ToolError("qBittorrent login failed: invalid username or password")
    _logged_in = True


async def _ensure_authed() -> None:
    if _api_key is not None or _username is None:
        return
    if not _logged_in:
        await _login()


def _decode(r: httpx.Response) -> JSONVal | str:
    """qBittorrent returns JSON for list/preferences endpoints and plain text
    (e.g. "Ok.") for most mutations, plus bare ints for a few limit endpoints.
    Respect content-type so a version string like "2.0" is not parsed as JSON."""
    if "json" in r.headers.get("content-type", ""):
        return r.json()
    return r.text


async def _req(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    files: list[Any] | None = None,
) -> JSONVal | str:
    global _logged_in
    assert _client is not None, "client not configured"
    await _ensure_authed()
    r = await _client.request(method, path, params=params, data=data, files=files)
    if r.status_code in (401, 403) and _logged_in and _api_key is None:
        # Cookie session expired mid-run: re-login once and retry the request.
        _logged_in = False
        await _login()
        r = await _client.request(method, path, params=params, data=data, files=files)
    if r.status_code >= 400:
        raise ToolError(f"qBittorrent API {r.status_code}: {r.text}")
    return _decode(r)


def _omit(params: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose values are empty/None so the API's defaults apply."""
    return {k: v for k, v in params.items() if v not in ("", None)}


# --- auth --------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
async def qbittorrent_logout() -> str:
    """Invalidate the current WebUI session. With API-key auth this endpoint is
    not reachable (API keys cannot interact with /auth/*) and the API will return
    an error which is surfaced as-is."""
    return await _req("POST", "/auth/logout")


# --- application ---------------------------------------------------------------

@mcp.tool(annotations=READONLY)
async def qbittorrent_app_version() -> str:
    """The qBittorrent application version, e.g. v5.0.4."""
    return await _req("GET", "/app/version")


@mcp.tool(annotations=READONLY)
async def qbittorrent_app_webapi_version() -> str:
    """The WebAPI version implemented by this qBittorrent, e.g. 2.14.1."""
    return await _req("GET", "/app/webapiVersion")


@mcp.tool(annotations=READONLY)
async def qbittorrent_app_build_info() -> JSONObj:
    """Build info: Qt, libtorrent, Boost and OpenSSL versions plus app bitness."""
    return await _req("GET", "/app/buildInfo")


@mcp.tool(annotations=DESTRUCTIVE)
async def qbittorrent_app_shutdown() -> str:
    """Shut down the qBittorrent application. This stops the whole daemon/WebUI --
    use sparingly, it cannot be undone from here."""
    return await _req("POST", "/app/shutdown")


@mcp.tool(annotations=READONLY)
async def qbittorrent_app_get_preferences() -> JSONObj:
    """All application preferences as a key/value object (locale, limits, paths,
    WebUI settings, etc). See README for the full field list."""
    return await _req("GET", "/app/preferences")


@mcp.tool(annotations=WRITE)
async def qbittorrent_app_set_preferences(json: dict[str, Any]) -> str:
    """Update application preferences. Pass only the keys you want to change, e.g.
    {"max_active_downloads": 5, "save_path": "/downloads"}. String values must be
    quoted; integers and booleans must not."""
    import json as _json

    return await _req("POST", "/app/setPreferences", data={"json": _json.dumps(json)})


@mcp.tool(annotations=READONLY)
async def qbittorrent_app_default_save_path() -> str:
    """The default save path for new torrents, e.g. C:/Users/me/Downloads."""
    return await _req("GET", "/app/defaultSavePath")


@mcp.tool(annotations=READONLY)
async def qbittorrent_app_get_cookies() -> JSONArr:
    """The cookies qBittorrent sends when downloading .torrent files. Each entry
    has name/domain/path/value/expirationDate."""
    return await _req("GET", "/app/cookies")


@mcp.tool(annotations=WRITE)
async def qbittorrent_app_set_cookies(cookies: list[dict[str, Any]]) -> str:
    """Replace the cookies used when downloading .torrent files. cookies is a JSON
    array of {name, domain, path, value, expirationDate} objects."""
    import json as _json

    return await _req("POST", "/app/setCookies", data={"json": _json.dumps(cookies)})


# --- log ----------------------------------------------------------------------

@mcp.tool(annotations=READONLY)
async def qbittorrent_log_main(
    normal: bool | None = None,
    info: bool | None = None,
    warning: bool | None = None,
    critical: bool | None = None,
    last_known_id: int = -1,
) -> JSONArr:
    """The application log as a JSON array of {id, message, timestamp, type}.
    Filter message classes with normal/info/warning/critical (default true for
    all). Pass last_known_id to fetch only messages newer than a given id."""
    return await _req(
        "GET",
        "/log/main",
        _omit(
            {
                "normal": normal,
                "info": info,
                "warning": warning,
                "critical": critical,
                "last_known_id": last_known_id,
            }
        ),
    )


@mcp.tool(annotations=READONLY)
async def qbittorrent_log_peers(last_known_id: int = -1) -> JSONArr:
    """Peer-block log entries as a JSON array of {id, ip, timestamp, blocked,
    reason}. Pass last_known_id to fetch only entries newer than a given id."""
    return await _req("GET", "/log/peers", _omit({"last_known_id": last_known_id}))


# --- sync ---------------------------------------------------------------------

@mcp.tool(annotations=READONLY)
async def qbittorrent_sync_maindata(rid: int = 0) -> JSONObj:
    """Differential state snapshot for UI sync. Pass the rid from the previous
    reply to get only changes; full_update=true means you received everything.
    Includes torrents, categories, tags and server_state."""
    return await _req("GET", "/sync/maindata", _omit({"rid": rid}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_sync_torrent_peers(hash: str, rid: int = 0) -> JSONObj:
    """Differential peers data for one torrent. Pass the rid from the previous
    reply to get only changes."""
    return await _req("GET", "/sync/torrentPeers", _omit({"hash": hash, "rid": rid}))


# --- transfer -----------------------------------------------------------------

@mcp.tool(annotations=READONLY)
async def qbittorrent_transfer_info() -> JSONObj:
    """Global transfer info: download/upload rates and totals, rate limits, DHT
    nodes and connection status."""
    return await _req("GET", "/transfer/info")


@mcp.tool(annotations=READONLY)
async def qbittorrent_transfer_speed_limits_mode() -> int:
    """1 if alternative speed limits are enabled, 0 otherwise."""
    return int(await _req("GET", "/transfer/speedLimitsMode"))


@mcp.tool(annotations=WRITE)
async def qbittorrent_transfer_toggle_speed_limits() -> str:
    """Toggle the alternative speed limits on/off."""
    return await _req("POST", "/transfer/toggleSpeedLimitsMode")


@mcp.tool(annotations=READONLY)
async def qbittorrent_transfer_download_limit() -> int:
    """Global download speed limit in bytes/s (0 if no limit is applied)."""
    return int(await _req("GET", "/transfer/downloadLimit"))


@mcp.tool(annotations=WRITE)
async def qbittorrent_transfer_set_download_limit(limit: int) -> str:
    """Set the global download speed limit in bytes/s (0 removes the limit)."""
    return await _req("POST", "/transfer/setDownloadLimit", data={"limit": limit})


@mcp.tool(annotations=READONLY)
async def qbittorrent_transfer_upload_limit() -> int:
    """Global upload speed limit in bytes/s (0 if no limit is applied)."""
    return int(await _req("GET", "/transfer/uploadLimit"))


@mcp.tool(annotations=WRITE)
async def qbittorrent_transfer_set_upload_limit(limit: int) -> str:
    """Set the global upload speed limit in bytes/s (0 removes the limit)."""
    return await _req("POST", "/transfer/setUploadLimit", data={"limit": limit})


@mcp.tool(annotations=WRITE)
async def qbittorrent_transfer_ban_peers(peers: str) -> str:
    """Ban peers. peers is one or more `host:port` values separated by a pipe,
    e.g. "1.2.3.4:6881|5.6.7.8:6882"."""
    return await _req("POST", "/transfer/banPeers", data={"peers": peers})


# --- torrent management ---------------------------------------------------------

@mcp.tool(annotations=READONLY)
async def qbittorrent_torrents_list(
    filter: str = "",
    category: str = "",
    tag: str = "",
    sort: str = "",
    reverse: bool | None = None,
    limit: int | None = None,
    offset: int | None = None,
    hashes: str = "",
) -> JSONArr:
    """List torrents matching the given filters. filter is one of all,
    downloading, seeding, completed, stopped, active, inactive, running, stalled,
    stalled_uploading, stalled_downloading, errored. category/tag filter by them
    (empty string = "without category/tag"). sort by any response field; reverse
    for descending order. limit/offset for paging; hashes (pipe-separated or
    "all") to select specific torrents."""
    return await _req(
        "GET",
        "/torrents/info",
        _omit(
            {
                "filter": filter,
                "category": category,
                "tag": tag,
                "sort": sort,
                "reverse": reverse,
                "limit": limit,
                "offset": offset,
                "hashes": hashes,
            }
        ),
    )


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrent_properties(hash: str) -> JSONObj:
    """Generic properties of one torrent: save_path, creation/completion dates,
    total uploaded/downloaded, seeding_time, share_ratio, speeds, peer counts,
    isPrivate, etc. 404 if the hash is not found."""
    return await _req("GET", "/torrents/properties", _omit({"hash": hash}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrent_trackers(hash: str) -> JSONArr:
    """Trackers of one torrent: url, status (0 disabled, 1 not contacted yet,
    2 working, 3 updating, 4 not working), tier, peer/seed/leech counts, msg."""
    return await _req("GET", "/torrents/trackers", _omit({"hash": hash}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrent_web_seeds(hash: str) -> JSONArr:
    """Web seeds of one torrent (array of {url})."""
    return await _req("GET", "/torrents/webseeds", _omit({"hash": hash}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrent_contents(hash: str, indexes: str = "") -> JSONArr:
    """Files of one torrent: index, name, size, progress, priority (0 skip, 1
    normal, 6 high, 7 maximal), is_seed, piece_range, availability. Pass
    indexes (pipe-separated) to fetch only those files."""
    return await _req("GET", "/torrents/files", _omit({"hash": hash, "indexes": indexes}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrent_piece_states(hash: str) -> JSONArr:
    """Piece states of one torrent as ints: 0 not downloaded, 1 downloading,
    2 downloaded."""
    return await _req("GET", "/torrents/pieceStates", _omit({"hash": hash}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrent_piece_hashes(hash: str) -> JSONArr:
    """SHA1 hashes of all pieces of one torrent, in order."""
    return await _req("GET", "/torrents/pieceHashes", _omit({"hash": hash}))


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_pause(hashes: str) -> str:
    """Pause (stop) torrents. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/stop", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_resume(hashes: str) -> str:
    """Resume (start) torrents. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/start", data={"hashes": hashes})


@mcp.tool(annotations=DESTRUCTIVE)
async def qbittorrent_torrents_delete(hashes: str, delete_files: bool = False) -> str:
    """Delete torrents. hashes is pipe-separated or "all". With delete_files=true
    the downloaded data is deleted from disk too -- this is irreversible."""
    return await _req(
        "POST",
        "/torrents/delete",
        data={"hashes": hashes, "deleteFiles": delete_files},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_recheck(hashes: str) -> str:
    """Force recheck of torrents. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/recheck", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_reannounce(hashes: str) -> str:
    """Reannounce torrents to their trackers. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/reannounce", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_add(
    urls: str = "",
    torrent_b64: str = "",
    save_path: str = "",
    category: str = "",
    tags: str = "",
    skip_checking: bool | None = None,
    paused: bool | None = None,
    root_folder: bool | None = None,
    rename: str = "",
    up_limit: int | None = None,
    dl_limit: int | None = None,
    ratio_limit: float | None = None,
    seeding_time_limit: int | None = None,
    auto_tmm: bool | None = None,
    sequential_download: bool | None = None,
    first_last_piece_prio: bool | None = None,
) -> str:
    """Add torrents. urls is one or more http(s)/magnet/bc:// links separated by
    newlines. Alternatively (or additionally) pass one raw .torrent file
    base64-encoded in torrent_b64. Optional: save_path, category, tags
    (comma-separated), skip_checking, paused, root_folder, rename, up_limit /
    dl_limit (bytes/s), ratio_limit, seeding_time_limit (minutes), auto_tmm,
    sequential_download, first_last_piece_prio."""
    import json as _json

    form = _omit(
        {
            "urls": urls,
            "savepath": save_path,
            "category": category,
            "tags": tags,
            "skip_checking": skip_checking,
            "paused": paused,
            "root_folder": root_folder,
            "rename": rename,
            "upLimit": up_limit,
            "dlLimit": dl_limit,
            "ratioLimit": ratio_limit,
            "seedingTimeLimit": seeding_time_limit,
            "autoTMM": auto_tmm,
            "sequentialDownload": sequential_download,
            "firstLastPiecePrio": first_last_piece_prio,
        }
    )
    files = None
    if torrent_b64:
        payload = base64.b64decode(torrent_b64)
        files = [("torrents", ("upload.torrent", payload, "application/x-bittorrent"))]
    return await _req("POST", "/torrents/add", data=form, files=files)


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_add_trackers(hash: str, urls: str) -> str:
    """Add trackers to a torrent. urls is one or more tracker URLs separated by
    newlines."""
    return await _req("POST", "/torrents/addTrackers", data={"hash": hash, "urls": urls})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_edit_tracker(hash: str, url: str, new_url: str) -> str:
    """Replace a tracker URL on a torrent with new_url."""
    return await _req(
        "POST",
        "/torrents/editTracker",
        data={"hash": hash, "url": url, "newUrl": new_url},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_remove_trackers(hash: str, urls: str) -> str:
    """Remove trackers from a torrent. urls is one or more URLs separated by a
    pipe."""
    return await _req("POST", "/torrents/removeTrackers", data={"hash": hash, "urls": urls})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_add_peers(hashes: str, peers: str) -> str:
    """Add peers to torrents. hashes is pipe-separated or "all"; peers is one or
    more `host:port` values separated by a pipe."""
    return await _req("POST", "/torrents/addPeers", data={"hashes": hashes, "peers": peers})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_increase_priority(hashes: str) -> str:
    """Increase queue priority of torrents. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/increasePrio", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_decrease_priority(hashes: str) -> str:
    """Decrease queue priority of torrents. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/decreasePrio", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_top_priority(hashes: str) -> str:
    """Move torrents to the top of the queue. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/topPrio", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_bottom_priority(hashes: str) -> str:
    """Move torrents to the bottom of the queue. hashes is pipe-separated or "all"."""
    return await _req("POST", "/torrents/bottomPrio", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_file_priority(hash: str, id: str, priority: int) -> str:
    """Set file priority for a torrent. id is one or more file ids (from
    qbittorrent_torrent_contents) separated by a pipe; priority is 0 (skip),
    1 (normal), 6 (high) or 7 (maximal)."""
    return await _req(
        "POST",
        "/torrents/filePrio",
        data={"hash": hash, "id": id, "priority": priority},
    )


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrents_download_limit(hashes: str) -> JSONObj:
    """Per-torrent download speed limits (bytes/s), keyed by hash. hashes is
    pipe-separated or "all"."""
    return await _req("POST", "/torrents/downloadLimit", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_download_limit(hashes: str, limit: int) -> str:
    """Set download speed limit (bytes/s) for torrents. hashes is pipe-separated
    or "all"; limit 0 means no limit."""
    return await _req(
        "POST",
        "/torrents/setDownloadLimit",
        data={"hashes": hashes, "limit": limit},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_share_limits(
    hashes: str,
    ratio_limit: float = -2,
    seeding_time_limit: int = -2,
    inactive_seeding_time_limit: int = -2,
) -> str:
    """Set share limits for torrents (hashes pipe-separated or "all").
    ratio_limit (share ratio), seeding_time_limit and inactive_seeding_time_limit
    (minutes). -2 = use global limit, -1 = no limit."""
    return await _req(
        "POST",
        "/torrents/setShareLimits",
        data={
            "hashes": hashes,
            "ratioLimit": ratio_limit,
            "seedingTimeLimit": seeding_time_limit,
            "inactiveSeedingTimeLimit": inactive_seeding_time_limit,
        },
    )


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrents_upload_limit(hashes: str) -> JSONObj:
    """Per-torrent upload speed limits (bytes/s), keyed by hash. hashes is
    pipe-separated or "all"."""
    return await _req("POST", "/torrents/uploadLimit", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_upload_limit(hashes: str, limit: int) -> str:
    """Set upload speed limit (bytes/s) for torrents. hashes is pipe-separated
    or "all"; limit 0 means no limit."""
    return await _req(
        "POST",
        "/torrents/setUploadLimit",
        data={"hashes": hashes, "limit": limit},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_location(hashes: str, location: str) -> str:
    """Move torrents to a new download location on disk. hashes is
    pipe-separated or "all"; location is the destination directory."""
    return await _req(
        "POST",
        "/torrents/setLocation",
        data={"hashes": hashes, "location": location},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_name(hash: str, name: str) -> str:
    """Rename a torrent (display name only, does not touch files on disk)."""
    return await _req("POST", "/torrents/rename", data={"hash": hash, "name": name})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_category(hashes: str, category: str) -> str:
    """Set the category of torrents. hashes is pipe-separated or "all"; pass an
    empty category to remove the current category."""
    return await _req(
        "POST",
        "/torrents/setCategory",
        data={"hashes": hashes, "category": category},
    )


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrents_categories() -> JSONObj:
    """All categories as {name: {name, savePath}}."""
    return await _req("GET", "/torrents/categories")


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_create_category(category: str, save_path: str = "") -> str:
    """Create a category with an optional save_path."""
    return await _req(
        "POST",
        "/torrents/createCategory",
        data={"category": category, "savePath": save_path},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_edit_category(category: str, save_path: str) -> str:
    """Change the save_path of an existing category."""
    return await _req(
        "POST",
        "/torrents/editCategory",
        data={"category": category, "savePath": save_path},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_remove_categories(categories: str) -> str:
    """Remove categories. categories is one or more names separated by newlines.
    Torrents in a removed category become uncategorized."""
    return await _req("POST", "/torrents/removeCategories", data={"categories": categories})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_add_tags(hashes: str, tags: str) -> str:
    """Add tags (comma-separated) to torrents (hashes pipe-separated or "all")."""
    return await _req("POST", "/torrents/addTags", data={"hashes": hashes, "tags": tags})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_remove_tags(hashes: str, tags: str) -> str:
    """Remove tags (comma-separated) from torrents (hashes pipe-separated or
    "all"). An empty tags value removes all tags from the torrents."""
    return await _req("POST", "/torrents/removeTags", data={"hashes": hashes, "tags": tags})


@mcp.tool(annotations=READONLY)
async def qbittorrent_torrents_tags() -> JSONArr:
    """All tags as a JSON array of strings."""
    return await _req("GET", "/torrents/tags")


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_create_tags(tags: str) -> str:
    """Create tags. tags is one or more names separated by commas."""
    return await _req("POST", "/torrents/createTags", data={"tags": tags})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_delete_tags(tags: str) -> str:
    """Delete tags. tags is one or more names separated by commas. Torrents keep
    their data but lose the deleted tags."""
    return await _req("POST", "/torrents/deleteTags", data={"tags": tags})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_auto_management(hashes: str, enable: bool) -> str:
    """Enable/disable Automatic Torrent Management for torrents (hashes
    pipe-separated or "all")."""
    return await _req(
        "POST",
        "/torrents/setAutoManagement",
        data={"hashes": hashes, "enable": enable},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_toggle_sequential_download(hashes: str) -> str:
    """Toggle sequential download mode for torrents (hashes pipe-separated or
    "all")."""
    return await _req("POST", "/torrents/toggleSequentialDownload", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_toggle_first_last_piece_priority(hashes: str) -> str:
    """Toggle first/last piece priority for torrents (hashes pipe-separated or
    "all")."""
    return await _req("POST", "/torrents/toggleFirstLastPiecePrio", data={"hashes": hashes})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_force_start(hashes: str, value: bool) -> str:
    """Force-start or un-force-start torrents (hashes pipe-separated or "all")."""
    return await _req("POST", "/torrents/setForceStart", data={"hashes": hashes, "value": value})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_set_super_seeding(hashes: str, value: bool) -> str:
    """Enable/disable super seeding for torrents (hashes pipe-separated or "all")."""
    return await _req("POST", "/torrents/setSuperSeeding", data={"hashes": hashes, "value": value})


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_rename_file(hash: str, old_path: str, new_path: str) -> str:
    """Rename a file inside a torrent (relative paths from the torrent root)."""
    return await _req(
        "POST",
        "/torrents/renameFile",
        data={"hash": hash, "oldPath": old_path, "newPath": new_path},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_torrents_rename_folder(hash: str, old_path: str, new_path: str) -> str:
    """Rename a folder inside a torrent (relative paths from the torrent root)."""
    return await _req(
        "POST",
        "/torrents/renameFolder",
        data={"hash": hash, "oldPath": old_path, "newPath": new_path},
    )


# --- rss ----------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_add_folder(path: str) -> str:
    """Create an RSS folder, e.g. "The Pirate Bay\\Top100"."""
    return await _req("POST", "/rss/addFolder", data={"path": path})


@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_add_feed(url: str, path: str = "") -> str:
    """Add an RSS feed by URL, optionally into a folder path."""
    return await _req("POST", "/rss/addFeed", data={"url": url, "path": path})


@mcp.tool(annotations=DESTRUCTIVE)
async def qbittorrent_rss_remove_item(path: str) -> str:
    """Remove an RSS folder or feed, e.g. "The Pirate Bay\\Top100"."""
    return await _req("POST", "/rss/removeItem", data={"path": path})


@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_move_item(item_path: str, dest_path: str) -> str:
    """Move or rename an RSS folder/feed from item_path to dest_path."""
    return await _req(
        "POST",
        "/rss/moveItem",
        data={"itemPath": item_path, "destPath": dest_path},
    )


@mcp.tool(annotations=READONLY)
async def qbittorrent_rss_items(with_data: bool | None = None) -> JSONObj:
    """All RSS items as a nested object of folder -> feed -> URL. Set with_data
    to also include current feed articles."""
    return await _req("GET", "/rss/items", _omit({"withData": with_data}))


@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_mark_as_read(item_path: str, article_id: str = "") -> str:
    """Mark an RSS feed as read; pass article_id to mark only one article."""
    return await _req(
        "POST",
        "/rss/markAsRead",
        data=_omit({"itemPath": item_path, "articleId": article_id}),
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_refresh_item(item_path: str) -> str:
    """Force-refresh an RSS folder or feed."""
    return await _req("POST", "/rss/refreshItem", data={"itemPath": item_path})


@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_set_rule(rule_name: str, rule_def: dict[str, Any]) -> str:
    """Create or replace an auto-downloading RSS rule. rule_def keys: enabled,
    mustContain, mustNotContain, useRegex, episodeFilter, smartFilter,
    previouslyMatchedEpisodes, affectedFeeds, ignoreDays, lastMatch, addPaused,
    assignedCategory, savePath. e.g. {"enabled": true, "mustContain": "Ubuntu",
    "affectedFeeds": ["https://example.com/rss"]}"""
    import json as _json

    return await _req(
        "POST",
        "/rss/setRule",
        data={"ruleName": rule_name, "ruleDef": _json.dumps(rule_def)},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_rss_rename_rule(rule_name: str, new_rule_name: str) -> str:
    """Rename an auto-downloading rule."""
    return await _req(
        "POST",
        "/rss/renameRule",
        data={"ruleName": rule_name, "newRuleName": new_rule_name},
    )


@mcp.tool(annotations=DESTRUCTIVE)
async def qbittorrent_rss_remove_rule(rule_name: str) -> str:
    """Remove an auto-downloading rule."""
    return await _req("POST", "/rss/removeRule", data={"ruleName": rule_name})


@mcp.tool(annotations=READONLY)
async def qbittorrent_rss_rules() -> JSONObj:
    """All auto-downloading rules as {name: rule definition}."""
    return await _req("GET", "/rss/rules")


@mcp.tool(annotations=READONLY)
async def qbittorrent_rss_matching_articles(rule_name: str) -> JSONObj:
    """All feed articles matching a rule, as {feed name: [article titles]}."""
    return await _req("GET", "/rss/matchingArticles", _omit({"ruleName": rule_name}))


# --- search -------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
async def qbittorrent_search_start(pattern: str, plugins: str = "enabled", category: str = "all") -> JSONObj:
    """Start a search job across the configured plugins and return its id. plugins
    is plugin names separated by `|`, or "all"/"enabled". category limits the
    search (depends on the plugin), or "all"."""
    return await _req(
        "POST",
        "/search/start",
        data={"pattern": pattern, "plugins": plugins, "category": category},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_search_stop(id: int) -> str:
    """Stop a running search job by id."""
    return await _req("POST", "/search/stop", data={"id": id})


@mcp.tool(annotations=READONLY)
async def qbittorrent_search_status(id: int | None = None) -> JSONArr:
    """Status of one search job (id) or all jobs: {id, status: Running|Stopped,
    total}."""
    return await _req("GET", "/search/status", _omit({"id": id}))


@mcp.tool(annotations=READONLY)
async def qbittorrent_search_results(id: int, limit: int | None = None, offset: int | None = None) -> JSONObj:
    """Results of a search job: {results: [{descrLink, fileName, fileSize,
    fileUrl, nbLeechers, nbSeeders, siteUrl}], status, total}. limit caps the
    count (0/negative = no limit); negative offset counts back from the end."""
    return await _req("GET", "/search/results", _omit({"id": id, "limit": limit, "offset": offset}))


@mcp.tool(annotations=DESTRUCTIVE)
async def qbittorrent_search_delete(id: int) -> str:
    """Delete a search job and free its results."""
    return await _req("POST", "/search/delete", data={"id": id})


@mcp.tool(annotations=READONLY)
async def qbittorrent_search_plugins() -> JSONArr:
    """Installed search plugins: enabled, fullName, name, supportedCategories,
    url, version."""
    return await _req("GET", "/search/plugins")


@mcp.tool(annotations=WRITE)
async def qbittorrent_search_install_plugin(sources: str) -> str:
    """Install search plugins. sources is one or more URLs or file paths
    separated by a pipe."""
    return await _req("POST", "/search/installPlugin", data={"sources": sources})


@mcp.tool(annotations=WRITE)
async def qbittorrent_search_uninstall_plugin(names: str) -> str:
    """Uninstall search plugins. names is one or more names separated by a pipe."""
    return await _req("POST", "/search/uninstallPlugin", data={"names": names})


@mcp.tool(annotations=WRITE)
async def qbittorrent_search_enable_plugin(names: str, enable: bool) -> str:
    """Enable or disable search plugins. names is one or more names separated by
    a pipe."""
    return await _req(
        "POST",
        "/search/enablePlugin",
        data={"names": names, "enable": enable},
    )


@mcp.tool(annotations=WRITE)
async def qbittorrent_search_update_plugins() -> str:
    """Update all installed search plugins to their latest versions."""
    return await _req("POST", "/search/updatePlugins")


def main() -> None:
    global _client, _base_url, _api_key, _username, _password
    url = os.environ.get("QBITTORRENT_URL")
    if not url:
        print("QBITTORRENT_URL environment variable is required (e.g. http://localhost:8080)", file=sys.stderr)
        raise SystemExit(1)
    _base_url = url.rstrip("/")
    _api_key = os.environ.get("QBITTORRENT_API_KEY") or None
    _username = os.environ.get("QBITTORRENT_USERNAME") or None
    _password = os.environ.get("QBITTORRENT_PASSWORD") or None
    _client = build_client(_base_url, api_key=_api_key, username=_username, password=_password)
    mcp.run()


if __name__ == "__main__":
    main()
