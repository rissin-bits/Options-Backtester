"""
The API mounts the built frontend at "/". Client-side routes must survive a
direct load / refresh, without the fallback swallowing real 404s.
"""
import pytest
from fastapi.testclient import TestClient

import backend.api as api_module

pytestmark = pytest.mark.skipif(
    not (api_module.frontend_dist.exists() and (api_module.frontend_dist / "index.html").exists()),
    reason="frontend/dist not built",
)


@pytest.fixture
def spa_client():
    return TestClient(api_module.app)


@pytest.mark.parametrize("route", ["/", "/backtest", "/results", "/dashboard", "/code"])
def test_client_routes_serve_the_app(spa_client, route):
    """Regression: StaticFiles 404'd on every route except '/'."""
    res = spa_client.get(route)
    assert res.status_code == 200, route
    assert "<div id=\"root\"" in res.text or "<script" in res.text


def test_missing_asset_still_404s(spa_client):
    """The fallback must not turn a missing bundle into an HTML 200."""
    assert spa_client.get("/assets/definitely-not-here.js").status_code == 404


def test_api_routes_are_not_shadowed_by_the_mount(spa_client):
    res = spa_client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_unknown_api_route_does_not_fall_back_to_html(spa_client):
    res = spa_client.get("/api/no-such-endpoint")
    assert res.status_code == 404
