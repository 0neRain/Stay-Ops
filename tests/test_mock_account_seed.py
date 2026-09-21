import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password, verify_password
from app.models.auth import TenantMembership, User
from app.models.enums import MembershipRole
from scripts.seed_mock_knowledge import (
    MOCK_ACCOUNT_EMAIL,
    MOCK_ACCOUNT_PASSWORD,
    get_or_create_mock_account,
    get_or_create_mock_scope,
)


async def test_mock_seed_creates_one_active_demo_account(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        tenant, _ = await get_or_create_mock_scope(
            session,
            tenant_slug="demo-stays",
            property_external_id="demo-casa-aurora",
        )
        previous_user = User(
            email="previous-demo@example.com",
            full_name="Previous Demo User",
            password_hash=hash_password("previous demo password"),
        )
        session.add(previous_user)
        await session.flush()
        previous_membership = TenantMembership(
            tenant_id=tenant.id,
            user_id=previous_user.id,
            role=MembershipRole.OWNER,
        )
        session.add(previous_membership)
        await session.flush()

        user, membership = await get_or_create_mock_account(
            session,
            tenant_id=tenant.id,
        )
        await session.commit()

        assert user.email == MOCK_ACCOUNT_EMAIL
        assert verify_password(MOCK_ACCOUNT_PASSWORD, user.password_hash)
        assert membership.tenant_id == tenant.id
        assert membership.role == MembershipRole.OWNER
        assert membership.is_active is True
        assert previous_membership.is_active is False

        repeated_user, repeated_membership = await get_or_create_mock_account(
            session,
            tenant_id=tenant.id,
        )
        await session.commit()

        account_count = await session.scalar(
            select(func.count(User.id)).where(User.email == MOCK_ACCOUNT_EMAIL)
        )
        active_demo_memberships = await session.scalar(
            select(func.count(TenantMembership.id)).where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.is_active.is_(True),
            )
        )
        assert repeated_user.id == user.id
        assert repeated_membership.id == membership.id
        assert account_count == 1
        assert active_demo_memberships == 1


async def test_mock_login_has_demo_data_while_new_registration_is_empty(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        tenant, _ = await get_or_create_mock_scope(
            session,
            tenant_slug="demo-stays",
            property_external_id="demo-casa-aurora",
        )
        await get_or_create_mock_account(session, tenant_id=tenant.id)
        await session.commit()

    mock_login = await api_client.post(
        "/api/v1/auth/login",
        json={"email": MOCK_ACCOUNT_EMAIL, "password": MOCK_ACCOUNT_PASSWORD},
    )
    assert mock_login.status_code == 200
    mock_properties = await api_client.get(
        "/api/v1/properties",
        headers={"Authorization": f"Bearer {mock_login.json()['access_token']}"},
    )
    assert mock_properties.status_code == 200
    assert len(mock_properties.json()) == 1
    assert mock_properties.json()[0]["name"] == "Casa Aurora"
    assert mock_properties.json()[0]["is_demo"] is True

    registration = await api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "brand-new-owner@example.com",
            "password": "correct horse battery staple",
            "full_name": "Brand New Owner",
            "organization_name": "Empty Stays",
        },
    )
    assert registration.status_code == 201
    new_properties = await api_client.get(
        "/api/v1/properties",
        headers={"Authorization": f"Bearer {registration.json()['access_token']}"},
    )
    assert new_properties.status_code == 200
    assert new_properties.json() == []
