"""Offline tests: one per qBittorrent WebUI API endpoint, plus auth and error paths.

No network. Each tool call is checked against the exact HTTP request it should
produce (method, path, query params / form fields) via httpx.MockTransport, using
FastMCP's in-memory Client (see https://gofastmcp.com/development/tests).

Auth mode in this suite: API key (bearer) for the per-endpoint tests, plus
dedicated tests for the cookie-login fallback and the 403 re-login retry.
"""

import json
from urllib.parse import parse_qs

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

import qbittorrent_mcp

HASH = "8c212779b4abde7c6bc608063a0d008b7e40ce32"
HASH2 = "54eddd830a5b58480a6143d616a97e3a6c23c439"


class Recorder:
    """Captures the requests made during a test and replays a canned response."""

    def __init__(self):
        self.requests = []
        self.response = httpx.Response(200, text="Ok.", headers={"content-type": "text/plain"})
        self.override = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.override is not None:
            return self.override(request)
        return self.response

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def path(self) -> str:
        return self.last.url.path

    @property
    def method(self) -> str:
        return self.last.method

    @property
    def params(self):
        return self.last.url.params

    @property
    def headers(self):
        return self.last.headers

    @property
    def form(self) -> dict[str, list[str]]:
        return parse_qs(self.last.content.decode(), keep_blank_values=True)


@pytest.fixture
def recorder():
    return Recorder()


@pytest_asyncio.fixture
async def server(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = qbittorrent_mcp.build_client("http://qbit.example.com", api_key="qbt_test-key-0123456789abcdef0123456789", transport=transport)
    monkeypatch.setattr(qbittorrent_mcp, "_client", client)
    monkeypatch.setattr(qbittorrent_mcp, "_base_url", "http://qbit.example.com")
    monkeypatch.setattr(qbittorrent_mcp, "_api_key", "qbt_test-key-0123456789abcdef0123456789")
    monkeypatch.setattr(qbittorrent_mcp, "_username", None)
    monkeypatch.setattr(qbittorrent_mcp, "_password", None)
    monkeypatch.setattr(qbittorrent_mcp, "_logged_in", False)
    yield qbittorrent_mcp.mcp
    await client.aclose()


_OP_GROUP = {op: group for group, ops in qbittorrent_mcp._GROUPS.items() for op in ops}


async def call(server, tool, **kwargs):
    """Call `tool` (an operation name) through the portmanteau group tool
    that now hosts it, so every existing per-operation test keeps working
    unmodified aside from this helper."""
    async with Client(server) as c:
        return await c.call_tool(_OP_GROUP[tool], {"operation": tool, "arguments": kwargs})


# --- auth --------------------------------------------------------------------

async def test_1_logout(server, recorder):
    await call(server, "qbittorrent_logout")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/auth/logout"


# --- application ---------------------------------------------------------------

async def test_2_app_version(server, recorder):
    recorder.response = httpx.Response(200, text="v5.0.4", headers={"content-type": "text/plain"})
    result = await call(server, "qbittorrent_app_version")
    assert recorder.method == "GET"
    assert recorder.path == "/api/v2/app/version"
    assert result.data == "v5.0.4"


async def test_3_app_webapi_version(server, recorder):
    recorder.response = httpx.Response(200, text="2.14.1", headers={"content-type": "text/plain"})
    result = await call(server, "qbittorrent_app_webapi_version")
    assert recorder.path == "/api/v2/app/webapiVersion"
    assert result.data == "2.14.1"


async def test_4_app_build_info(server, recorder):
    recorder.response = httpx.Response(200, json={"qt": "6.7", "libtorrent": "2.0.11", "boost": "1.84", "openssl": "3.2.1", "bitness": 64})
    result = await call(server, "qbittorrent_app_build_info")
    assert recorder.path == "/api/v2/app/buildInfo"
    assert result.data["bitness"] == 64


async def test_5_app_shutdown(server, recorder):
    await call(server, "qbittorrent_app_shutdown")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/app/shutdown"


async def test_6_app_get_preferences(server, recorder):
    recorder.response = httpx.Response(200, json={"save_path": "/downloads", "queueing_enabled": False})
    result = await call(server, "qbittorrent_app_get_preferences")
    assert recorder.path == "/api/v2/app/preferences"
    assert result.data["save_path"] == "/downloads"


async def test_7_app_set_preferences(server, recorder):
    await call(server, "qbittorrent_app_set_preferences", json={"max_active_downloads": 5})
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/app/setPreferences"
    assert json.loads(recorder.form["json"][0]) == {"max_active_downloads": 5}


async def test_8_app_default_save_path(server, recorder):
    recorder.response = httpx.Response(200, text="C:/Users/me/Downloads", headers={"content-type": "text/plain"})
    result = await call(server, "qbittorrent_app_default_save_path")
    assert recorder.path == "/api/v2/app/defaultSavePath"
    assert result.data == "C:/Users/me/Downloads"


async def test_9_app_get_cookies(server, recorder):
    recorder.response = httpx.Response(200, json=[{"name": "Example", "domain": "example.com"}])
    result = await call(server, "qbittorrent_app_get_cookies")
    assert recorder.path == "/api/v2/app/cookies"
    assert result.data[0]["name"] == "Example"


async def test_10_app_set_cookies(server, recorder):
    cookies = [{"name": "Example", "domain": "example.com", "path": "/", "value": "foo=bar", "expirationDate": 1507969127}]
    await call(server, "qbittorrent_app_set_cookies", cookies=cookies)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/app/setCookies"
    assert json.loads(recorder.form["json"][0]) == cookies


# --- log ----------------------------------------------------------------------

async def test_11_log_main(server, recorder):
    recorder.response = httpx.Response(200, json=[{"id": 0, "message": "started", "timestamp": 1507969127, "type": 1}])
    result = await call(server, "qbittorrent_log_main", last_known_id=5)
    assert recorder.path == "/api/v2/log/main"
    assert recorder.params["last_known_id"] == "5"
    assert result.data[0]["id"] == 0


async def test_12_log_peers(server, recorder):
    recorder.response = httpx.Response(200, json=[{"id": 0, "ip": "1.2.3.4", "timestamp": 1507969127, "blocked": True, "reason": "filter"}])
    result = await call(server, "qbittorrent_log_peers")
    assert recorder.path == "/api/v2/log/peers"
    assert result.data[0]["blocked"] is True


# --- sync ---------------------------------------------------------------------

async def test_13_sync_maindata(server, recorder):
    recorder.response = httpx.Response(200, json={"rid": 15, "full_update": True, "torrents": {}})
    result = await call(server, "qbittorrent_sync_maindata", rid=14)
    assert recorder.path == "/api/v2/sync/maindata"
    assert recorder.params["rid"] == "14"
    assert result.data["full_update"] is True


async def test_14_sync_torrent_peers(server, recorder):
    recorder.response = httpx.Response(200, json={"rid": 0, "peers": {}})
    await call(server, "qbittorrent_sync_torrent_peers", hash=HASH)
    assert recorder.path == "/api/v2/sync/torrentPeers"
    assert recorder.params["hash"] == HASH


# --- transfer -----------------------------------------------------------------

async def test_15_transfer_info(server, recorder):
    recorder.response = httpx.Response(200, json={"dl_info_speed": 0, "up_info_speed": 0, "connection_status": "connected"})
    result = await call(server, "qbittorrent_transfer_info")
    assert recorder.path == "/api/v2/transfer/info"
    assert result.data["connection_status"] == "connected"


async def test_16_transfer_speed_limits_mode(server, recorder):
    recorder.response = httpx.Response(200, text="1", headers={"content-type": "text/plain"})
    result = await call(server, "qbittorrent_transfer_speed_limits_mode")
    assert recorder.path == "/api/v2/transfer/speedLimitsMode"
    assert result.data == 1


async def test_17_transfer_toggle_speed_limits(server, recorder):
    await call(server, "qbittorrent_transfer_toggle_speed_limits")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/transfer/toggleSpeedLimitsMode"


async def test_18_transfer_download_limit(server, recorder):
    recorder.response = httpx.Response(200, text="0", headers={"content-type": "text/plain"})
    result = await call(server, "qbittorrent_transfer_download_limit")
    assert recorder.path == "/api/v2/transfer/downloadLimit"
    assert result.data == 0


async def test_19_transfer_set_download_limit(server, recorder):
    await call(server, "qbittorrent_transfer_set_download_limit", limit=1048576)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/transfer/setDownloadLimit"
    assert recorder.form["limit"] == ["1048576"]


async def test_20_transfer_upload_limit(server, recorder):
    recorder.response = httpx.Response(200, text="1048576", headers={"content-type": "text/plain"})
    result = await call(server, "qbittorrent_transfer_upload_limit")
    assert recorder.path == "/api/v2/transfer/uploadLimit"
    assert result.data == 1048576


async def test_21_transfer_set_upload_limit(server, recorder):
    await call(server, "qbittorrent_transfer_set_upload_limit", limit=524288)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/transfer/setUploadLimit"
    assert recorder.form["limit"] == ["524288"]


async def test_22_transfer_ban_peers(server, recorder):
    await call(server, "qbittorrent_transfer_ban_peers", peers="1.2.3.4:6881|5.6.7.8:6882")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/transfer/banPeers"
    assert recorder.form["peers"] == ["1.2.3.4:6881|5.6.7.8:6882"]


# --- torrent management ---------------------------------------------------------

async def test_23_torrents_list(server, recorder):
    recorder.response = httpx.Response(200, json=[{"hash": HASH, "name": "debian", "state": "pausedUP"}])
    result = await call(server, "qbittorrent_torrents_list", filter="seeding", sort="ratio")
    assert recorder.method == "GET"
    assert recorder.path == "/api/v2/torrents/info"
    assert recorder.params["filter"] == "seeding"
    assert recorder.params["sort"] == "ratio"
    assert result.data[0]["hash"] == HASH


async def test_24_torrent_properties(server, recorder):
    recorder.response = httpx.Response(200, json={"save_path": "/Downloads", "seeding_time": 1128, "share_ratio": 0.0007, "isPrivate": True})
    result = await call(server, "qbittorrent_torrent_properties", hash=HASH)
    assert recorder.path == "/api/v2/torrents/properties"
    assert recorder.params["hash"] == HASH
    assert result.data["seeding_time"] == 1128
    assert result.data["share_ratio"] == 0.0007


async def test_25_torrent_trackers(server, recorder):
    recorder.response = httpx.Response(200, json=[{"url": "http://t.rack", "status": 2, "num_peers": 100}])
    result = await call(server, "qbittorrent_torrent_trackers", hash=HASH)
    assert recorder.path == "/api/v2/torrents/trackers"
    assert recorder.params["hash"] == HASH
    assert result.data[0]["status"] == 2


async def test_26_torrent_web_seeds(server, recorder):
    recorder.response = httpx.Response(200, json=[{"url": "http://some_url/"}])
    result = await call(server, "qbittorrent_torrent_web_seeds", hash=HASH)
    assert recorder.path == "/api/v2/torrents/webseeds"
    assert result.data[0]["url"] == "http://some_url/"


async def test_27_torrent_contents(server, recorder):
    recorder.response = httpx.Response(200, json=[{"index": 0, "name": "a.iso", "size": 100, "progress": 0.5, "priority": 1}])
    result = await call(server, "qbittorrent_torrent_contents", hash=HASH, indexes="0|2")
    assert recorder.path == "/api/v2/torrents/files"
    assert recorder.params["hash"] == HASH
    assert recorder.params["indexes"] == "0|2"
    assert result.data[0]["index"] == 0


async def test_28_torrent_piece_states(server, recorder):
    recorder.response = httpx.Response(200, json=[0, 0, 2, 1])
    result = await call(server, "qbittorrent_torrent_piece_states", hash=HASH)
    assert recorder.path == "/api/v2/torrents/pieceStates"
    assert result.data == [0, 0, 2, 1]


async def test_29_torrent_piece_hashes(server, recorder):
    recorder.response = httpx.Response(200, json=["54eddd830a5b58480a6143d616a97e3a6c23c439"])
    result = await call(server, "qbittorrent_torrent_piece_hashes", hash=HASH)
    assert recorder.path == "/api/v2/torrents/pieceHashes"
    assert result.data == ["54eddd830a5b58480a6143d616a97e3a6c23c439"]


async def test_30_torrents_pause(server, recorder):
    await call(server, "qbittorrent_torrents_pause", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/stop"
    assert recorder.form["hashes"] == [HASH]


async def test_31_torrents_resume(server, recorder):
    await call(server, "qbittorrent_torrents_resume", hashes="all")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/start"
    assert recorder.form["hashes"] == ["all"]


async def test_32_torrents_delete(server, recorder):
    await call(server, "qbittorrent_torrents_delete", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/delete"
    assert recorder.form["hashes"] == [HASH]
    assert recorder.form["deleteFiles"] == ["false"]

    await call(server, "qbittorrent_torrents_delete", hashes=HASH, delete_files=True)
    assert recorder.form["deleteFiles"] == ["true"]


async def test_33_torrents_recheck(server, recorder):
    await call(server, "qbittorrent_torrents_recheck", hashes=f"{HASH}|{HASH2}")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/recheck"
    assert recorder.form["hashes"] == [f"{HASH}|{HASH2}"]


async def test_34_torrents_reannounce(server, recorder):
    await call(server, "qbittorrent_torrents_reannounce", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/reannounce"
    assert recorder.form["hashes"] == [HASH]


async def test_35_torrents_add_urls(server, recorder):
    await call(server, "qbittorrent_torrents_add", urls="magnet:?xt=urn:btih:abc", paused=True)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/add"
    assert recorder.form["urls"] == ["magnet:?xt=urn:btih:abc"]
    assert recorder.form["paused"] == ["true"]
    assert "savepath" not in recorder.form


async def test_36_torrents_add_file(server, recorder):
    await call(server, "qbittorrent_torrents_add", torrent_b64="dGVzdC10b3JyZW50")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/add"
    assert b'test-torrent' in recorder.last.content
    assert b'name="torrents"' in recorder.last.content


async def test_37_torrents_add_trackers(server, recorder):
    await call(server, "qbittorrent_torrents_add_trackers", hash=HASH, urls="http://t.rack/announce\nudp://t.rack:3333")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/addTrackers"
    assert recorder.form["hash"] == [HASH]
    assert recorder.form["urls"] == ["http://t.rack/announce\nudp://t.rack:3333"]


async def test_38_torrents_edit_tracker(server, recorder):
    await call(server, "qbittorrent_torrents_edit_tracker", hash=HASH, url="http://old.t", new_url="http://new.t")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/editTracker"
    assert recorder.form == {"hash": [HASH], "url": ["http://old.t"], "newUrl": ["http://new.t"]}


async def test_39_torrents_remove_trackers(server, recorder):
    await call(server, "qbittorrent_torrents_remove_trackers", hash=HASH, urls="http://t1.t|http://t2.t")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/removeTrackers"
    assert recorder.form["urls"] == ["http://t1.t|http://t2.t"]


async def test_40_torrents_add_peers(server, recorder):
    await call(server, "qbittorrent_torrents_add_peers", hashes=HASH, peers="1.2.3.4:6881")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/addPeers"
    assert recorder.form["hashes"] == [HASH]
    assert recorder.form["peers"] == ["1.2.3.4:6881"]


async def test_41_torrents_increase_priority(server, recorder):
    await call(server, "qbittorrent_torrents_increase_priority", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/increasePrio"
    assert recorder.form["hashes"] == [HASH]


async def test_42_torrents_decrease_priority(server, recorder):
    await call(server, "qbittorrent_torrents_decrease_priority", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/decreasePrio"


async def test_43_torrents_top_priority(server, recorder):
    await call(server, "qbittorrent_torrents_top_priority", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/topPrio"


async def test_44_torrents_bottom_priority(server, recorder):
    await call(server, "qbittorrent_torrents_bottom_priority", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/bottomPrio"


async def test_45_torrents_file_priority(server, recorder):
    await call(server, "qbittorrent_torrents_file_priority", hash=HASH, id="0|1", priority=6)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/filePrio"
    assert recorder.form == {"hash": [HASH], "id": ["0|1"], "priority": ["6"]}


async def test_46_torrents_download_limit(server, recorder):
    recorder.response = httpx.Response(200, json={HASH: 338944})
    result = await call(server, "qbittorrent_torrents_download_limit", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/downloadLimit"
    assert recorder.form["hashes"] == [HASH]
    assert result.data[HASH] == 338944


async def test_47_torrents_set_download_limit(server, recorder):
    await call(server, "qbittorrent_torrents_set_download_limit", hashes=HASH, limit=131072)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setDownloadLimit"
    assert recorder.form["limit"] == ["131072"]


async def test_48_torrents_set_share_limits(server, recorder):
    await call(server, "qbittorrent_torrents_set_share_limits", hashes=HASH, ratio_limit=1.0, seeding_time_limit=60)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setShareLimits"
    assert recorder.form["ratioLimit"] == ["1.0"]
    assert recorder.form["seedingTimeLimit"] == ["60"]
    assert recorder.form["inactiveSeedingTimeLimit"] == ["-2"]


async def test_49_torrents_upload_limit(server, recorder):
    recorder.response = httpx.Response(200, json={HASH: 123})
    result = await call(server, "qbittorrent_torrents_upload_limit", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/uploadLimit"
    assert result.data[HASH] == 123


async def test_50_torrents_set_upload_limit(server, recorder):
    await call(server, "qbittorrent_torrents_set_upload_limit", hashes=HASH, limit=1024)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setUploadLimit"


async def test_51_torrents_set_location(server, recorder):
    await call(server, "qbittorrent_torrents_set_location", hashes=HASH, location="/mnt/nfs/media")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setLocation"
    assert recorder.form["location"] == ["/mnt/nfs/media"]


async def test_52_torrents_set_name(server, recorder):
    await call(server, "qbittorrent_torrents_set_name", hash=HASH, name="New Name")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/rename"
    assert recorder.form == {"hash": [HASH], "name": ["New Name"]}


async def test_53_torrents_set_category(server, recorder):
    await call(server, "qbittorrent_torrents_set_category", hashes=HASH, category="Movies")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setCategory"
    assert recorder.form["category"] == ["Movies"]


async def test_54_torrents_categories(server, recorder):
    recorder.response = httpx.Response(200, json={"Video": {"name": "Video", "savePath": "/v/"}})
    result = await call(server, "qbittorrent_torrents_categories")
    assert recorder.method == "GET"
    assert recorder.path == "/api/v2/torrents/categories"
    assert result.data["Video"]["savePath"] == "/v/"


async def test_55_torrents_create_category(server, recorder):
    await call(server, "qbittorrent_torrents_create_category", category="NewCat", save_path="/tmp/new")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/createCategory"
    assert recorder.form == {"category": ["NewCat"], "savePath": ["/tmp/new"]}


async def test_56_torrents_edit_category(server, recorder):
    await call(server, "qbittorrent_torrents_edit_category", category="NewCat", save_path="/tmp/edited")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/editCategory"
    assert recorder.form["savePath"] == ["/tmp/edited"]


async def test_57_torrents_remove_categories(server, recorder):
    await call(server, "qbittorrent_torrents_remove_categories", categories="Cat1\nCat2")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/removeCategories"
    assert recorder.form["categories"] == ["Cat1\nCat2"]


async def test_58_torrents_add_tags(server, recorder):
    await call(server, "qbittorrent_torrents_add_tags", hashes=HASH, tags="Tag1,Tag2")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/addTags"
    assert recorder.form["tags"] == ["Tag1,Tag2"]


async def test_59_torrents_remove_tags(server, recorder):
    await call(server, "qbittorrent_torrents_remove_tags", hashes=HASH, tags="Tag1")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/removeTags"
    assert recorder.form["tags"] == ["Tag1"]


async def test_60_torrents_tags(server, recorder):
    recorder.response = httpx.Response(200, json=["Tag 1", "Tag 2"])
    result = await call(server, "qbittorrent_torrents_tags")
    assert recorder.method == "GET"
    assert recorder.path == "/api/v2/torrents/tags"
    assert result.data == ["Tag 1", "Tag 2"]


async def test_61_torrents_create_tags(server, recorder):
    await call(server, "qbittorrent_torrents_create_tags", tags="Tag1,Tag2")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/createTags"
    assert recorder.form["tags"] == ["Tag1,Tag2"]


async def test_62_torrents_delete_tags(server, recorder):
    await call(server, "qbittorrent_torrents_delete_tags", tags="Tag1,Tag2")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/deleteTags"
    assert recorder.form["tags"] == ["Tag1,Tag2"]


async def test_63_torrents_set_auto_management(server, recorder):
    await call(server, "qbittorrent_torrents_set_auto_management", hashes=HASH, enable=True)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setAutoManagement"
    assert recorder.form["enable"] == ["true"]


async def test_64_torrents_toggle_sequential_download(server, recorder):
    await call(server, "qbittorrent_torrents_toggle_sequential_download", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/toggleSequentialDownload"


async def test_65_torrents_toggle_first_last_piece_priority(server, recorder):
    await call(server, "qbittorrent_torrents_toggle_first_last_piece_priority", hashes=HASH)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/toggleFirstLastPiecePrio"


async def test_66_torrents_set_force_start(server, recorder):
    await call(server, "qbittorrent_torrents_set_force_start", hashes=HASH, value=True)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setForceStart"
    assert recorder.form["value"] == ["true"]


async def test_67_torrents_set_super_seeding(server, recorder):
    await call(server, "qbittorrent_torrents_set_super_seeding", hashes=HASH, value=False)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/setSuperSeeding"
    assert recorder.form["value"] == ["false"]


async def test_68_torrents_rename_file(server, recorder):
    await call(server, "qbittorrent_torrents_rename_file", hash=HASH, old_path="a/b.iso", new_path="a/c.iso")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/renameFile"
    assert recorder.form == {"hash": [HASH], "oldPath": ["a/b.iso"], "newPath": ["a/c.iso"]}


async def test_69_torrents_rename_folder(server, recorder):
    await call(server, "qbittorrent_torrents_rename_folder", hash=HASH, old_path="a", new_path="b")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/torrents/renameFolder"
    assert recorder.form == {"hash": [HASH], "oldPath": ["a"], "newPath": ["b"]}


# --- rss ----------------------------------------------------------------------

async def test_70_rss_add_folder(server, recorder):
    await call(server, "qbittorrent_rss_add_folder", path="The Pirate Bay\\Top100")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/addFolder"
    assert recorder.form["path"] == ["The Pirate Bay\\Top100"]


async def test_71_rss_add_feed(server, recorder):
    await call(server, "qbittorrent_rss_add_feed", url="http://feed.example.com/rss")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/addFeed"
    assert recorder.form["url"] == ["http://feed.example.com/rss"]


async def test_72_rss_remove_item(server, recorder):
    await call(server, "qbittorrent_rss_remove_item", path="The Pirate Bay\\Top100")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/removeItem"


async def test_73_rss_move_item(server, recorder):
    await call(server, "qbittorrent_rss_move_item", item_path="The Pirate Bay\\Top100", dest_path="The Pirate Bay")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/moveItem"
    assert recorder.form == {"itemPath": ["The Pirate Bay\\Top100"], "destPath": ["The Pirate Bay"]}


async def test_74_rss_items(server, recorder):
    recorder.response = httpx.Response(200, json={"HD-Torrents.org": "https://hd-torrents.org/rss.php"})
    result = await call(server, "qbittorrent_rss_items")
    assert recorder.path == "/api/v2/rss/items"
    assert result.data["HD-Torrents.org"] == "https://hd-torrents.org/rss.php"


async def test_75_rss_mark_as_read(server, recorder):
    await call(server, "qbittorrent_rss_mark_as_read", item_path="feed")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/markAsRead"
    assert recorder.form["itemPath"] == ["feed"]
    assert "articleId" not in recorder.form


async def test_76_rss_refresh_item(server, recorder):
    await call(server, "qbittorrent_rss_refresh_item", item_path="feed")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/refreshItem"


async def test_77_rss_set_rule(server, recorder):
    rule = {"enabled": True, "mustContain": "Ubuntu", "affectedFeeds": ["http://feed.example.com/rss"]}
    await call(server, "qbittorrent_rss_set_rule", rule_name="Ubuntu", rule_def=rule)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/setRule"
    assert recorder.form["ruleName"] == ["Ubuntu"]
    assert json.loads(recorder.form["ruleDef"][0]) == rule


async def test_78_rss_rename_rule(server, recorder):
    await call(server, "qbittorrent_rss_rename_rule", rule_name="Old", new_rule_name="New")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/renameRule"
    assert recorder.form == {"ruleName": ["Old"], "newRuleName": ["New"]}


async def test_79_rss_remove_rule(server, recorder):
    await call(server, "qbittorrent_rss_remove_rule", rule_name="Old")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/rss/removeRule"


async def test_80_rss_rules(server, recorder):
    recorder.response = httpx.Response(200, json={"The Punisher": {"enabled": False}})
    result = await call(server, "qbittorrent_rss_rules")
    assert recorder.path == "/api/v2/rss/rules"
    assert result.data["The Punisher"]["enabled"] is False


async def test_81_rss_matching_articles(server, recorder):
    recorder.response = httpx.Response(200, json={"DistroWatch": ["sparky.iso.torrent"]})
    result = await call(server, "qbittorrent_rss_matching_articles", rule_name="Linux")
    assert recorder.path == "/api/v2/rss/matchingArticles"
    assert recorder.params["ruleName"] == "Linux"
    assert result.data["DistroWatch"] == ["sparky.iso.torrent"]


# --- search -------------------------------------------------------------------

async def test_82_search_start(server, recorder):
    recorder.response = httpx.Response(200, json={"id": 12345})
    result = await call(server, "qbittorrent_search_start", pattern="Ubuntu 18.04")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/start"
    assert recorder.form["pattern"] == ["Ubuntu 18.04"]
    assert recorder.form["plugins"] == ["enabled"]
    assert recorder.form["category"] == ["all"]
    assert result.data["id"] == 12345


async def test_83_search_stop(server, recorder):
    await call(server, "qbittorrent_search_stop", id=12345)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/stop"
    assert recorder.form["id"] == ["12345"]


async def test_84_search_status(server, recorder):
    recorder.response = httpx.Response(200, json=[{"id": 12345, "status": "Running", "total": 170}])
    result = await call(server, "qbittorrent_search_status")
    assert recorder.path == "/api/v2/search/status"
    assert result.data[0]["status"] == "Running"


async def test_85_search_results(server, recorder):
    recorder.response = httpx.Response(200, json={"results": [{"fileName": "u.iso", "nbSeeders": 0}], "status": "Stopped", "total": 1})
    result = await call(server, "qbittorrent_search_results", id=12345, limit=10, offset=0)
    assert recorder.path == "/api/v2/search/results"
    assert recorder.params["id"] == "12345"
    assert recorder.params["limit"] == "10"
    assert result.data["total"] == 1


async def test_86_search_delete(server, recorder):
    await call(server, "qbittorrent_search_delete", id=12345)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/delete"
    assert recorder.form["id"] == ["12345"]


async def test_87_search_plugins(server, recorder):
    recorder.response = httpx.Response(200, json=[{"enabled": True, "name": "legittorrents", "fullName": "Legit Torrents"}])
    result = await call(server, "qbittorrent_search_plugins")
    assert recorder.path == "/api/v2/search/plugins"
    assert result.data[0]["name"] == "legittorrents"


async def test_88_search_install_plugin(server, recorder):
    await call(server, "qbittorrent_search_install_plugin", sources="https://raw.example.com/plugin.py")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/installPlugin"
    assert recorder.form["sources"] == ["https://raw.example.com/plugin.py"]


async def test_89_search_uninstall_plugin(server, recorder):
    await call(server, "qbittorrent_search_uninstall_plugin", names="legittorrents")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/uninstallPlugin"
    assert recorder.form["names"] == ["legittorrents"]


async def test_90_search_enable_plugin(server, recorder):
    await call(server, "qbittorrent_search_enable_plugin", names="legittorrents", enable=True)
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/enablePlugin"
    assert recorder.form["enable"] == ["true"]


async def test_91_search_update_plugins(server, recorder):
    await call(server, "qbittorrent_search_update_plugins")
    assert recorder.method == "POST"
    assert recorder.path == "/api/v2/search/updatePlugins"


# --- auth header ---------------------------------------------------------------

async def test_api_key_sent_as_bearer_header(server, recorder):
    await call(server, "qbittorrent_app_version")
    assert recorder.headers["authorization"] == "Bearer qbt_test-key-0123456789abcdef0123456789"


async def test_no_api_key_means_no_authorization_header(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = qbittorrent_mcp.build_client("http://qbit.example.com", transport=transport)
    monkeypatch.setattr(qbittorrent_mcp, "_client", client)
    monkeypatch.setattr(qbittorrent_mcp, "_api_key", None)
    monkeypatch.setattr(qbittorrent_mcp, "_username", None)
    monkeypatch.setattr(qbittorrent_mcp, "_logged_in", False)
    await call(qbittorrent_mcp.mcp, "qbittorrent_app_version")
    assert "authorization" not in recorder.headers
    await client.aclose()


# --- cookie login fallback -----------------------------------------------------

def _login_ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        text="Ok.",
        headers={"content-type": "text/plain", "set-cookie": "SID=hBc7TxF76ERhvIw0jQQ4LZ7Z1jQUV0tQ; path=/"},
    )


async def test_cookie_login_happens_lazily_before_first_call(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = qbittorrent_mcp.build_client("http://qbit.example.com", username="admin", password="secret", transport=transport)
    monkeypatch.setattr(qbittorrent_mcp, "_client", client)
    monkeypatch.setattr(qbittorrent_mcp, "_base_url", "http://qbit.example.com")
    monkeypatch.setattr(qbittorrent_mcp, "_api_key", None)
    monkeypatch.setattr(qbittorrent_mcp, "_username", "admin")
    monkeypatch.setattr(qbittorrent_mcp, "_password", "secret")
    monkeypatch.setattr(qbittorrent_mcp, "_logged_in", False)

    recorder.response = _login_ok_response()
    result = await call(qbittorrent_mcp.mcp, "qbittorrent_app_version")
    assert len(recorder.requests) == 2
    assert recorder.requests[0].method == "POST"
    assert recorder.requests[0].url.path == "/api/v2/auth/login"
    assert parse_qs(recorder.requests[0].content.decode())["username"] == ["admin"]
    assert recorder.requests[0].headers["referer"] == "http://qbit.example.com"
    assert recorder.requests[1].url.path == "/api/v2/app/version"
    assert qbittorrent_mcp._logged_in is True
    await client.aclose()


async def test_login_failure_is_surfaced(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = qbittorrent_mcp.build_client("http://qbit.example.com", username="admin", password="wrong", transport=transport)
    monkeypatch.setattr(qbittorrent_mcp, "_client", client)
    monkeypatch.setattr(qbittorrent_mcp, "_base_url", "http://qbit.example.com")
    monkeypatch.setattr(qbittorrent_mcp, "_api_key", None)
    monkeypatch.setattr(qbittorrent_mcp, "_username", "admin")
    monkeypatch.setattr(qbittorrent_mcp, "_password", "wrong")
    monkeypatch.setattr(qbittorrent_mcp, "_logged_in", False)

    # Login succeeds (200) but no SID cookie is set => invalid credentials.
    recorder.response = httpx.Response(200, text="Fails.", headers={"content-type": "text/plain"})
    with pytest.raises(ToolError, match="invalid username or password"):
        await call(qbittorrent_mcp.mcp, "qbittorrent_app_version")
    await client.aclose()


async def test_expired_session_retries_with_relogin(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = qbittorrent_mcp.build_client("http://qbit.example.com", username="admin", password="secret", transport=transport)
    monkeypatch.setattr(qbittorrent_mcp, "_client", client)
    monkeypatch.setattr(qbittorrent_mcp, "_base_url", "http://qbit.example.com")
    monkeypatch.setattr(qbittorrent_mcp, "_api_key", None)
    monkeypatch.setattr(qbittorrent_mcp, "_username", "admin")
    monkeypatch.setattr(qbittorrent_mcp, "_password", "secret")
    monkeypatch.setattr(qbittorrent_mcp, "_logged_in", True)

    recorder.response = httpx.Response(403, text="Forbidden", headers={"content-type": "text/plain"})
    # First app call 403s (expired session) -> re-login -> retried call succeeds.
    def sequence(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/auth/login":
            return _login_ok_response()
        if request.url.path == "/api/v2/app/version" and not sequence.saw_expired:
            sequence.saw_expired = True
            return httpx.Response(403, text="Forbidden", headers={"content-type": "text/plain"})
        return httpx.Response(200, text="v5.0.4", headers={"content-type": "text/plain"})

    sequence.saw_expired = False
    recorder.override = sequence
    result = await call(qbittorrent_mcp.mcp, "qbittorrent_app_version")
    assert [r.url.path for r in recorder.requests] == [
        "/api/v2/app/version",
        "/api/v2/auth/login",
        "/api/v2/app/version",
    ]
    assert result.data == "v5.0.4"
    await client.aclose()


async def test_403_with_api_key_is_not_retried(recorder, monkeypatch):
    transport = httpx.MockTransport(recorder.handler)
    client = qbittorrent_mcp.build_client("http://qbit.example.com", api_key="qbt_x", transport=transport)
    monkeypatch.setattr(qbittorrent_mcp, "_client", client)
    monkeypatch.setattr(qbittorrent_mcp, "_api_key", "qbt_x")
    monkeypatch.setattr(qbittorrent_mcp, "_username", None)
    monkeypatch.setattr(qbittorrent_mcp, "_logged_in", False)

    recorder.response = httpx.Response(403, text="Forbidden", headers={"content-type": "text/plain"})
    with pytest.raises(ToolError, match="403"):
        await call(qbittorrent_mcp.mcp, "qbittorrent_app_version")
    assert len(recorder.requests) == 1
    await client.aclose()


# --- error paths ---------------------------------------------------------------

async def test_404_error_message_reaches_caller(server, recorder):
    recorder.response = httpx.Response(404, text="Not Found", headers={"content-type": "text/plain"})
    with pytest.raises(ToolError, match="404"):
        await call(server, "qbittorrent_torrent_properties", hash="invalid")


async def test_409_error_surfaces_status(server, recorder):
    recorder.response = httpx.Response(409, text="Category name does not exist", headers={"content-type": "text/plain"})
    with pytest.raises(ToolError, match="409"):
        await call(server, "qbittorrent_torrents_set_category", hashes=HASH, category="nope")


async def test_415_error_surfaces_status(server, recorder):
    recorder.response = httpx.Response(415, text="Torrent file is not valid", headers={"content-type": "text/plain"})
    with pytest.raises(ToolError, match="415"):
        await call(server, "qbittorrent_torrents_add", urls="http://invalid.example/torrent.torrent")


# --- main() --------------------------------------------------------------------

def test_main_requires_qbittorrent_url(monkeypatch):
    monkeypatch.delenv("QBITTORRENT_URL", raising=False)
    with pytest.raises(SystemExit):
        qbittorrent_mcp.main()


# --- portmanteau grouping safety net --------------------------------------------

def test_all_operations_grouped():
    """Every entry in _OP_GROUP came from _GROUPS; assert no duplicates and
    that every group name resolves to a real module-level function - this is
    the safety net for the group-tool consolidation."""
    grouped_names = [n for names in qbittorrent_mcp._GROUPS.values() for n in names]
    assert len(grouped_names) == len(set(grouped_names))
    for n in grouped_names:
        assert hasattr(qbittorrent_mcp, n), f"{n} not found in qbittorrent_mcp module"


async def test_group_tools_are_the_only_registered_tools(server):
    async with Client(server) as c:
        tools = await c.list_tools()
    assert {t.name for t in tools} == set(qbittorrent_mcp._GROUPS)


async def test_unknown_operation_rejected_by_schema(server):
    # The Literal[...] enum on `operation` means an invalid value never
    # reaches _register_group's dispatch body - pydantic rejects it first.
    with pytest.raises(ToolError, match="validation error"):
        async with Client(server) as c:
            await c.call_tool("qbittorrent_auth", {"operation": "not_a_real_operation"})
