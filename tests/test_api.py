"""Tests for the REST API endpoints."""

import pytest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import app
from orchestrator.db.models import Run, RunState


@pytest.mark.integration
async def test_healthz():
    """Liveness check always returns ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.integration
async def test_get_workflows():
    """Registered workflows are listed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        names = [w["name"] for w in data]
        assert "research" in names


@pytest.mark.integration
async def test_metrics():
    """Metrics endpoint returns connection count."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_connections" in data
        assert "active_runs" in data
