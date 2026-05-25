from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.privacy, pytest.mark.security, pytest.mark.authz]


def _provision_user(session_factory, external_auth_id: str, email: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
            return user

    return run_async(_run())


def _provision_platform_actor(
    session_factory, external_auth_id: str, email: str, role: PlatformRole
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id, role=role.value
                )
            return user

    return run_async(_run())


def _count_requests(session_factory) -> int:
    async def _run():
        async with session_factory() as session:
            return len(
                (await session.execute(select(DataSubjectRequest))).scalars().all()
            )

    return run_async(_run())


def test_unauthenticated_user_cannot_submit_dsr(
    client_factory, migrated_database_url
) -> None:
    client = client_factory(
        database_url=migrated_database_url, rate_limiting_enabled=True
    )
    response = client.post(
        "/api/v1/privacy/data-subject-requests", json={"request_type": "export"}
    )
    assert response.status_code == 401


def test_user_submit_and_idempotency_behaviour(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _provision_user(
        migrated_session_factory, "kc-dsr-user", "dsr-user@example.com"
    )
    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    r1 = bundle.client.post(
        "/api/v1/privacy/data-subject-requests",
        json={"request_type": "export"},
        headers={"Idempotency-Key": "k-1"},
    )
    r2 = bundle.client.post(
        "/api/v1/privacy/data-subject-requests",
        json={"request_type": "export"},
        headers={"Idempotency-Key": "k-1"},
    )
    r3 = bundle.client.post(
        "/api/v1/privacy/data-subject-requests",
        json={"request_type": "erase"},
        headers={"Idempotency-Key": "k-1"},
    )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 409
    assert r1.json()["id"] == r2.json()["id"]
    assert _count_requests(migrated_session_factory) == 1
    for forbidden in (
        "internal_note",
        "requester_note",
        "idempotency_key_hash",
        "idempotency_fingerprint",
        "idempotency_key_expires_at",
    ):
        assert forbidden not in r1.json()


def test_user_bola_read_and_cancel_protection(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    owner = _provision_user(
        migrated_session_factory, "kc-dsr-owner", "dsr-owner@example.com"
    )
    stranger = _provision_user(
        migrated_session_factory, "kc-dsr-stranger", "dsr-stranger@example.com"
    )
    owner_client = authenticated_client_factory(
        identity=identity_for(owner.external_auth_id, owner.email),
        database_url=migrated_database_url,
    )
    stranger_client = authenticated_client_factory(
        identity=identity_for(stranger.external_auth_id, stranger.email),
        database_url=migrated_database_url,
    )

    created = owner_client.client.post(
        "/api/v1/privacy/data-subject-requests", json={"request_type": "export"}
    )
    request_id = created.json()["id"]

    assert (
        stranger_client.client.get(
            f"/api/v1/privacy/data-subject-requests/{request_id}"
        ).status_code
        == 404
    )
    assert (
        stranger_client.client.post(
            f"/api/v1/privacy/data-subject-requests/{request_id}/cancel"
        ).status_code
        == 404
    )


def test_user_can_cancel_own_submitted_request(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _provision_user(
        migrated_session_factory, "kc-dsr-cancel", "dsr-cancel@example.com"
    )
    client = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )
    created = client.client.post(
        "/api/v1/privacy/data-subject-requests", json={"request_type": "export"}
    )
    request_id = created.json()["id"]

    cancelled = client.client.post(
        f"/api/v1/privacy/data-subject-requests/{request_id}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == DataSubjectRequestStatus.CANCELLED.value


def test_platform_permissions_and_review_lifecycle(
    authenticated_client_factory,
    client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    normal = _provision_user(
        migrated_session_factory, "kc-dsr-normal", "dsr-normal@example.com"
    )
    support = _provision_platform_actor(
        migrated_session_factory,
        "kc-dsr-support",
        "dsr-support@example.com",
        PlatformRole.SUPPORT_AGENT,
    )
    compliance = _provision_platform_actor(
        migrated_session_factory,
        "kc-dsr-compliance",
        "dsr-compliance@example.com",
        PlatformRole.COMPLIANCE_OFFICER,
    )
    submitter = _provision_user(
        migrated_session_factory, "kc-dsr-submitter", "dsr-submitter@example.com"
    )

    unauth = client_factory(database_url=migrated_database_url)
    assert (
        unauth.get("/api/v1/platform/privacy/data-subject-requests").status_code == 401
    )

    normal_client = authenticated_client_factory(
        identity=identity_for(normal.external_auth_id, normal.email),
        database_url=migrated_database_url,
    )
    support_client = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )
    compliance_client = authenticated_client_factory(
        identity=identity_for(
            compliance.external_auth_id, compliance.email, roles=["platform_admin"]
        ),
        database_url=migrated_database_url,
    )
    submitter_client = authenticated_client_factory(
        identity=identity_for(submitter.external_auth_id, submitter.email),
        database_url=migrated_database_url,
    )

    created = submitter_client.client.post(
        "/api/v1/privacy/data-subject-requests", json={"request_type": "export"}
    )
    rid = created.json()["id"]

    assert (
        normal_client.client.get(
            "/api/v1/platform/privacy/data-subject-requests"
        ).status_code
        == 403
    )
    assert (
        support_client.client.get(
            "/api/v1/platform/privacy/data-subject-requests"
        ).status_code
        == 403
    )
    assert (
        support_client.client.post(
            f"/api/v1/platform/privacy/data-subject-requests/{rid}/review", json={}
        ).status_code
        == 403
    )

    lst = compliance_client.client.get(
        "/api/v1/platform/privacy/data-subject-requests",
        params={"status": "submitted", "request_type": "export"},
    )
    assert lst.status_code == 200
    assert set(lst.json().keys()) == {"data", "meta", "links"}

    assert (
        compliance_client.client.post(
            f"/api/v1/platform/privacy/data-subject-requests/{rid}/fulfil", json={}
        ).status_code
        == 409
    )
    assert (
        compliance_client.client.post(
            f"/api/v1/platform/privacy/data-subject-requests/{rid}/review", json={}
        ).status_code
        == 200
    )
    assert (
        compliance_client.client.post(
            f"/api/v1/platform/privacy/data-subject-requests/{rid}/approve",
            json={"reason_code": "compliance_review"},
        ).status_code
        == 200
    )
    assert (
        compliance_client.client.post(
            f"/api/v1/platform/privacy/data-subject-requests/{rid}/fulfil", json={}
        ).status_code
        == 200
    )

    # JWT roles must not elevate without local platform_staff role mapping.
    jwt_only = authenticated_client_factory(
        identity=identity_for(
            "kc-jwt-only", "jwt-only@example.com", roles=["platform_admin"]
        ),
        database_url=migrated_database_url,
    )
    assert (
        jwt_only.client.get(
            "/api/v1/platform/privacy/data-subject-requests"
        ).status_code
        == 403
    )


def test_platform_filters_work(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    compliance = _provision_platform_actor(
        migrated_session_factory,
        "kc-dsr-compliance2",
        "dsr-compliance2@example.com",
        PlatformRole.COMPLIANCE_OFFICER,
    )
    requester = _provision_user(
        migrated_session_factory, "kc-dsr-filter-user", "dsr-filter-user@example.com"
    )
    requester_client = authenticated_client_factory(
        identity=identity_for(requester.external_auth_id, requester.email),
        database_url=migrated_database_url,
    )
    comp_client = authenticated_client_factory(
        identity=identity_for(compliance.external_auth_id, compliance.email),
        database_url=migrated_database_url,
    )

    created = requester_client.client.post(
        "/api/v1/privacy/data-subject-requests", json={"request_type": "export"}
    ).json()
    due_at = datetime.fromisoformat(created["due_at"].replace("Z", "+00:00"))
    response = comp_client.client.get(
        "/api/v1/platform/privacy/data-subject-requests",
        params={
            "status": "submitted",
            "request_type": "export",
            "requester_user_id": str(requester.id),
            "subject_user_id": str(requester.id),
            "due_before": (due_at + timedelta(days=1)).astimezone(UTC).isoformat(),
            "due_after": (due_at - timedelta(days=1)).astimezone(UTC).isoformat(),
        },
    )
    assert response.status_code == 200
    assert any(item["id"] == created["id"] for item in response.json()["data"])
