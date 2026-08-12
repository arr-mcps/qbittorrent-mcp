"""Integration tests against a real qBittorrent WebUI.

Skipped unless QBITTORRENT_URL and one auth path (API key, or username+password)
are set. Run with:
    uv run pytest -m integration

These tests only hit read-only endpoints -- they never add, mutate or delete
torrents, even though the server itself is read+write.
"""

import os

import pytest
from fastmcp import Client

import qbittorrent_mcp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("QBITTORRENT_URL"),
        reason="requires QBITTORRENT_URL",
    ),
]


@pytest.fixture(autouse=True)
def configure_client():
    url = os.environ["QBITTORRENT_URL"]
    qbittorrent_mcp._base_url = url.rstrip("/")
    qbittorrent_mcp._api_key = os.environ.get("QBITTORRENT_API_KEY") or None
    qbittorrent_mcp._username = os.environ.get("QBITTORRENT_USERNAME") or None
    qbittorrent_mcp._password = os.environ.get("QBITTORRENT_PASSWORD") or None
    qbittorrent_mcp._logged_in = False
    qbittorrent_mcp._client = qbittorrent_mcp.build_client(
        url,
        api_key=qbittorrent_mcp._api_key,
        username=qbittorrent_mcp._username,
        password=qbittorrent_mcp._password,
    )
    yield
    if qbittorrent_mcp._client is not None:
        import asyncio

        asyncio.get_event_loop().run_until_complete(qbittorrent_mcp._client.aclose())


async def call(name, **kwargs):
    async with Client(qbittorrent_mcp.mcp) as c:
        return await c.call_tool(name, kwargs)


async def test_app_version_is_semver():
    result = await call("qbittorrent_app_version")
    assert result.data.startswith("v")


async def test_app_build_info():
    result = await call("qbittorrent_app_build_info")
    assert "libtorrent" in result.data
    assert "qt" in result.data


async def test_transfer_info():
    result = await call("qbittorrent_transfer_info")
    assert "dl_info_speed" in result.data
    assert "up_info_speed" in result.data


async def test_torrents_list_is_array():
    result = await call("qbittorrent_torrents_list", limit=5)
    assert isinstance(result.data, list)


async def test_torrent_properties_when_torrents_exist():
    torrents = await call("qbittorrent_torrents_list", limit=1)
    if not torrents.data:
        pytest.skip("no torrents on this instance")
    torrent_hash = torrents.data[0]["hash"]

    props = await call("qbittorrent_torrent_properties", hash=torrent_hash)
    assert props.data["save_path"]
    assert "share_ratio" in props.data
    assert "seeding_time" in props.data

    await call("qbittorrent_torrent_trackers", hash=torrent_hash)
    await call("qbittorrent_torrent_web_seeds", hash=torrent_hash)
    await call("qbittorrent_torrent_contents", hash=torrent_hash)


async def test_categories_and_tags():
    result = await call("qbittorrent_torrents_categories")
    assert isinstance(result.data, dict)
    tags = await call("qbittorrent_torrents_tags")
    assert isinstance(tags.data, list)


async def test_search_plugins():
    result = await call("qbittorrent_search_plugins")
    assert isinstance(result.data, list)
