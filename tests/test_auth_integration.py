import httpx

REGISTRATION = {
    "email": "owner@example.com",
    "password": "correct horse battery staple",
    "full_name": "Example Owner",
    "organization_name": "Example Stays",
}


async def test_register_authenticate_refresh_and_logout(api_client: httpx.AsyncClient) -> None:
    registration = await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    assert registration.status_code == 201
    registration_body = registration.json()
    assert registration_body["token_type"] == "bearer"
    assert registration_body["role"] == "owner"
    assert "refresh_token" not in registration_body
    assert "HttpOnly" in registration.headers["set-cookie"]
    assert "Path=/api/v1/auth" in registration.headers["set-cookie"]

    access_token = registration_body["access_token"]
    profile = await api_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert profile.status_code == 200
    assert profile.json()["user"]["email"] == REGISTRATION["email"]
    assert profile.json()["memberships"][0]["tenant_name"] == "Example Stays"

    old_refresh_token = api_client.cookies.get("stayops_refresh")
    refreshed = await api_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != access_token
    assert api_client.cookies.get("stayops_refresh") != old_refresh_token

    logout = await api_client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"message": "Logged out"}
    assert api_client.cookies.get("stayops_refresh") is None


async def test_login_rejects_invalid_credentials_and_duplicate_registration(
    api_client: httpx.AsyncClient,
) -> None:
    assert (await api_client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 201
    assert (await api_client.post("/api/v1/auth/register", json=REGISTRATION)).status_code == 409

    invalid = await api_client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": "incorrect-password"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Invalid email or password"

    valid = await api_client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": REGISTRATION["password"]},
    )
    assert valid.status_code == 200
    assert valid.json()["role"] == "owner"


async def test_me_requires_access_token(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
