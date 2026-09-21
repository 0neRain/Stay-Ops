import httpx

from app.main import app


async def test_health() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_frontend_routes_serve_the_application() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for route in ("/", "/auth", "/dashboard"):
            response = await client.get(route)
            assert response.status_code == 200
            assert "StayOps" in response.text

        stylesheet = await client.get("/static/styles.css")
        profile_form_script = await client.get("/static/profile-form.js")
        script = await client.get("/static/app.js")

    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert ".ingestion-progress-track" in stylesheet.text
    assert profile_form_script.status_code == 200
    assert "fillHomeProfileForm" in profile_form_script.text
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert 'aria-label="Document ingestion progress"' in script.text
    assert "formatIngestionEta" in script.text
    assert "StayOpsProfileForm.fillHomeProfileForm" in script.text


async def test_auth_routes_are_in_openapi_schema() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        schema = (await client.get("/openapi.json")).json()
    paths = schema["paths"]
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/chat/messages" in paths
    assert "/api/v1/escalations" in paths
    assert "/api/v1/escalations/{escalation_id}/claim" in paths
    assert "/api/v1/escalations/{escalation_id}/resolve" in paths
    assert "/api/v1/knowledge/documents" in paths
    assert "/api/v1/knowledge/documents/{document_id}" in paths
