import asyncio
import json
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import (
    get_acp_gateway_client,
    get_email_service,
    get_gateway_admin_client,
    get_profile_object_store,
    get_skill_storage,
)
from app.clients.acp_gateway import AcpGatewayClient
from app.clients.gateway_admin import GatewayMcpService
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import hash_opaque_token, hash_password, verify_password
from app.db import migrate_database, open_database_connection
from app.main import app, create_app
from app.services.chat_service import _AcpTurnResult
from app.services.email_service import EmailSendError, EmailService
from app.services.profile_repository import ProfileRepository
from app.services.subscription_status import tenant_subscription_management_status


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "experts-backend"}


def test_app_startup_runs_published_expert_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.expert_runtime_reconciliation import (
        ExpertRuntimeReconcileSummary,
    )

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'startup.sqlite3'}",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    calls: list[Settings] = []

    async def reconcile(actual: Settings) -> ExpertRuntimeReconcileSummary:
        calls.append(actual)
        return ExpertRuntimeReconcileSummary(items=())

    monkeypatch.setattr("app.main.reconcile_published_experts", reconcile)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200

    assert calls == [settings]


def test_app_startup_refuses_health_when_fail_closed_did_not_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.expert_runtime_reconciliation import (
        ExpertRuntimeReconcileItem,
        ExpertRuntimeReconcileSummary,
    )

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'unsafe-startup.sqlite3'}",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )

    async def reconcile(_: Settings) -> ExpertRuntimeReconcileSummary:
        return ExpertRuntimeReconcileSummary(
            items=(
                ExpertRuntimeReconcileItem(
                    expert_id="0123456789abcdef",
                    outcome="failed",
                    expert_status="published",
                    error_code="DatabaseError",
                ),
            )
        )

    monkeypatch.setattr("app.main.reconcile_published_experts", reconcile)

    with pytest.raises(
        RuntimeError,
        match="could not fail closed",
    ):
        with TestClient(create_app(settings)):
            pass


def test_app_startup_refuses_health_when_gateway_fail_closed_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.expert_runtime_reconciliation import (
        ExpertRuntimeReconcileItem,
        ExpertRuntimeReconcileSummary,
    )

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'unsafe-gateway-startup.sqlite3'}",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )

    async def reconcile(_: Settings) -> ExpertRuntimeReconcileSummary:
        return ExpertRuntimeReconcileSummary(
            items=(
                ExpertRuntimeReconcileItem(
                    expert_id="0123456789abcdef",
                    outcome="failed",
                    expert_status="unlisted",
                    error_code="EXPERT_RUNTIME_SMOKE_FAILED",
                    fail_closed=False,
                    fail_closed_error_code="EXPERT_RUNTIME_FAIL_CLOSED_FAILED",
                ),
            )
        )

    monkeypatch.setattr("app.main.reconcile_published_experts", reconcile)

    with pytest.raises(RuntimeError, match="could not fail closed"):
        with TestClient(create_app(settings)):
            pass


def test_acp_resumed_turn_uses_persisted_snapshot_as_baseline() -> None:
    result = _AcpTurnResult(previous_usage_snapshot=13_400)

    result.capture_usage(13_460)

    assert result.token_usage_snapshot == 13_460
    assert result.token_used == 60


def test_tenant_subscription_management_status_boundaries() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)

    assert tenant_subscription_management_status("cancelled", None, now=now) == "cancelled"
    assert tenant_subscription_management_status("expired", None, now=now) == "expired"
    assert (
        tenant_subscription_management_status("active", now.isoformat(), now=now) == "expired"
    )
    assert (
        tenant_subscription_management_status(
            "trialing",
            (now - timedelta(microseconds=1)).isoformat(),
            now=now,
        )
        == "expired"
    )
    assert (
        tenant_subscription_management_status(
            "past_due",
            (now + timedelta(days=30)).isoformat(),
            now=now,
        )
        == "past_due"
    )
    assert (
        tenant_subscription_management_status(
            "trialing",
            (now + timedelta(days=30)).isoformat(),
            now=now,
        )
        == "trialing"
    )
    assert (
        tenant_subscription_management_status(
            "active",
            (now + timedelta(days=14)).isoformat(),
            now=now,
        )
        == "expiring_soon"
    )
    assert (
        tenant_subscription_management_status(
            "active",
            (now + timedelta(days=14, microseconds=1)).isoformat(),
            now=now,
        )
        == "active"
    )


def test_openapi_loads() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]
    create_expert_properties = schema["components"]["schemas"]["CreateExpertRequest"][
        "properties"
    ]
    assert schema["components"]["schemas"]["CreateExpertRequest"][
        "additionalProperties"
    ] is False
    assert "expertId" not in create_expert_properties
    assert "expertKey" not in create_expert_properties
    assert "status" not in create_expert_properties
    assert "/api/v1/audit-events" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/password-reset/request" in paths
    assert "/api/v1/auth/password-reset/confirm" in paths
    assert "/api/v1/users/register" in paths
    assert "/api/v1/users" in paths
    assert "/api/v1/users/{user_id}" in paths
    assert "/api/v1/users/{user_id}/status" in paths
    assert "/api/v1/users/{user_id}/tenants" in paths
    assert "/api/v1/users/platform/activate" in paths
    assert "/api/v1/users/platform" in paths
    assert "/api/v1/tenants" in paths
    assert "/api/v1/tenants/{tenant_id}" in paths
    assert "/api/v1/tenants/{tenant_id}/status" in paths
    assert "/api/v1/tenants/{tenant_id}/members" in paths
    assert "/api/v1/tenants/{tenant_id}/members/{user_id}" in paths
    assert "/api/v1/expert-categories" in paths
    assert "/api/v1/expert-categories/{category_id}" in paths
    assert "/api/v1/experts" in paths
    assert "/api/v1/experts/stats/summary" in paths
    assert "/api/v1/experts/{expert_id}" in paths
    assert "/api/v1/experts/{expert_id}/status" in paths
    assert "/api/v1/experts/{expert_id}/runtime-build-input" not in paths
    assert "/api/v1/experts/{expert_id}/runtime-assets" not in paths
    assert "/api/v1/experts/{expert_id}/runtime-bindings" not in paths
    assert "/api/v1/mcp-connectors" in paths
    assert "/api/v1/mcp-servers/catalog" not in paths
    assert "/api/v1/expert-market/categories" in paths
    assert "/api/v1/expert-market/experts" in paths
    assert "/api/v1/expert-market/experts/{expert_id}" in paths
    assert "/api/v1/plans" in paths
    assert "/api/v1/plans/{plan_id}" in paths
    assert "/api/v1/plans/{plan_id}/prices" in paths
    assert "/api/v1/plans/{plan_id}/entitlements" in paths
    assert "/api/v1/plans/{plan_id}/experts" in paths
    assert "/api/v1/plan-market/plans" in paths
    assert "/api/v1/plan-market/current-subscription" in paths
    assert "/api/v1/rbac/tenant/users" in paths
    assert "/api/v1/rbac/tenant/users/{user_id}/roles" in paths
    assert "/api/v1/rbac/tenant/users/{user_id}" in paths
    assert "/api/v1/rbac/platform/users/{user_id}/roles" in paths
    assert "/api/v1/rbac/platform/users/{user_id}/roles/{role}" in paths
    assert "/api/v1/admin/users" not in paths
    assert "/api/v1/knowledge-bases" in paths
    assert "/api/v1/knowledge-bases/{knowledge_base_id}/index-review" in paths
    assert "/api/v1/knowledge-bases/{knowledge_base_id}/index-review/approve" in paths
    assert "/api/v1/knowledge-bases/official" not in paths
    assert "/api/v1/chat/search" in paths
    assert "/api/v1/chat/sessions/{session_id}/turns" in paths
    assert "post" not in paths["/api/v1/library/files"]
    assert "/api/v1/library/files/upload-url" in paths
    assert "/api/v1/library/files/complete-upload" in paths
    assert "/api/v1/skills" in paths


def test_sqlite_migration_uses_infra_sql(tmp_path: Path) -> None:
    database_path = tmp_path / "expert.sqlite3"
    settings = Settings(database_url=f"sqlite:///{database_path}")

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
        chat_turn_columns = {
            row["name"] for row in connection.execute("pragma table_info(chat_turns)").fetchall()
        }
        chat_session_columns = {
            row["name"] for row in connection.execute("pragma table_info(chat_sessions)").fetchall()
        }
        expert_category_columns = {
            row["name"]
            for row in connection.execute("pragma table_info(expert_categories)").fetchall()
        }
        expert_columns = {
            row["name"] for row in connection.execute("pragma table_info(experts)").fetchall()
        }
        plans = connection.execute("select id, code, name, expert_ids from plans").fetchall()
        default_expert = connection.execute(
            "select id, name, status from experts where id = '1825107e997dfde2'"
        ).fetchone()

    assert "tenants" in tables
    assert "password_reset_codes" in tables
    assert "knowledge_bases" in tables
    assert "chat_sessions" in tables
    assert "chat_turns" in tables
    # Old proxy-era tables were removed once the local store became the system of record.
    assert "chat_tasks" not in tables
    assert "chat_task_events" not in tables
    assert "chat_messages" not in tables
    assert "acp_search_session_id" in chat_session_columns
    assert "runtime_build_id" not in chat_session_columns
    assert "runtime_service_id" not in chat_session_columns
    assert "runtime_route_id" not in chat_session_columns
    assert "runtime_route_prefix" not in chat_session_columns
    assert "runtime_search_route_prefix" not in chat_session_columns
    assert "request_text" in chat_turn_columns
    assert "response_text" in chat_turn_columns
    assert "token_usage_scope" in chat_turn_columns
    assert "token_usage_snapshot" in chat_turn_columns
    assert "token_used" in chat_turn_columns
    assert "runtime_build_id" not in chat_turn_columns
    assert "runtime_service_id" not in chat_turn_columns
    assert "expert_categories" in tables
    assert "market_label" not in expert_category_columns
    assert "experts" in tables
    assert "market_labels" in expert_columns
    assert "expert_key" not in expert_columns
    assert "expert_runtime_bindings" not in tables
    assert "expert_skills" in tables
    assert "expert_knowledge_bases" in tables
    assert "plans" in tables
    assert "subscriptions" in tables
    assert "tenant_subscriptions" not in tables
    assert "plan_prices" not in tables
    assert "plan_entitlements" not in tables
    assert "plan_experts" not in tables
    assert "subscription_entitlement_snapshots" not in tables
    assert "tenant_credit_periods" in tables
    assert "credit_ledger" in tables
    assert "credit_usage_records" in tables
    assert [(row["id"], row["code"], row["name"]) for row in plans] == [
        ("plan_free", "free", "Free"),
        ("plan_pro", "pro", "Pro"),
        ("plan_max", "max", "Max"),
        ("plan_business", "business", "Business"),
    ]
    assert [json.loads(row["expert_ids"]) for row in plans[:2]] == [
        ["1825107e997dfde2"],
        ["1825107e997dfde2"],
    ]
    assert default_expert is not None
    assert default_expert["name"] == "默认专家"
    assert default_expert["status"] == "unlisted"

    with open_database_connection(settings) as connection:
        user_columns = [
            row["name"] for row in connection.execute("pragma table_info(users)").fetchall()
        ]
    assert user_columns.count("preferred_locale") == 1
    assert user_columns.count("avatar_object_key") == 1


def test_sqlite_migration_adds_profile_columns_without_losing_existing_users(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-users.sqlite3"
    settings = Settings(database_url=f"sqlite:///{database_path}")

    with open_database_connection(settings) as connection:
        connection.execute(
            """
            create table users (
              id text primary key,
              email text not null unique,
              password_hash text not null,
              name text not null,
              status text not null,
              created_at text not null default CURRENT_TIMESTAMP,
              updated_at text not null default CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values ('user_existing', 'existing@example.com', 'hash', 'Existing User', 'active')
            """
        )
        connection.commit()

    migrate_database(settings)
    migrate_database(settings)

    with open_database_connection(settings) as connection:
        columns = [
            row["name"] for row in connection.execute("pragma table_info(users)").fetchall()
        ]
        row = connection.execute(
            """
            select email, name, preferred_locale, avatar_object_key
            from users
            where id = 'user_existing'
            """
        ).fetchone()

    assert columns.count("preferred_locale") == 1
    assert columns.count("avatar_object_key") == 1
    assert row is not None
    assert row["email"] == "existing@example.com"
    assert row["name"] == "Existing User"
    assert row["preferred_locale"] is None
    assert row["avatar_object_key"] is None


def test_sqlite_migration_backfills_existing_expert_columns_idempotently(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-experts.sqlite3"
    settings = Settings(database_url=f"sqlite:///{database_path}")

    with open_database_connection(settings) as connection:
        connection.execute(
            """
            create table expert_categories (
              id text primary key,
              name text not null unique,
              description text,
              market_label text not null default 'none',
              created_at text not null default CURRENT_TIMESTAMP,
              updated_at text not null default CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            insert into expert_categories (id, name, description)
            values ('expert_cat_existing', 'Existing', 'Existing category')
            """
        )
        connection.execute(
            """
            create table experts (
              id text primary key,
              category_id text not null references expert_categories(id) on delete restrict,
              name text not null,
              ability_intro text not null,
              tags text not null default '[]',
              status text not null default 'draft'
                check (status in ('published', 'draft', 'unlisted')),
              guide_questions text not null default '[]',
              summon_button_text text,
              created_at text not null default CURRENT_TIMESTAMP,
              updated_at text not null default CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            insert into experts (id, category_id, name, ability_intro)
            values (
              'abcdef0123456789', 'expert_cat_existing', 'Existing expert', 'Existing ability'
            )
            """
        )
        connection.commit()

    migrate_database(settings)
    migrate_database(settings)

    with open_database_connection(settings) as connection:
        category_columns = [
            row["name"]
            for row in connection.execute("pragma table_info(expert_categories)").fetchall()
        ]
        columns = [
            row["name"] for row in connection.execute("pragma table_info(experts)").fetchall()
        ]
        row = connection.execute(
            """
            select market_labels
            from experts
            where id = ?
            """,
            ("abcdef0123456789",),
        ).fetchone()

    assert "market_label" not in category_columns
    assert columns.count("market_labels") == 1
    assert row is not None
    assert row["market_labels"] == "[]"


def test_app_startup_migrates_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "startup.sqlite3"
    settings = Settings(database_url=f"sqlite:///{database_path}")
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    with open_database_connection(settings) as connection:
        row = connection.execute(
            "select name from sqlite_master where type = 'table' and name = 'tenants'"
        ).fetchone()
    assert row is not None


def test_auth_register_login_refresh_logout_persists_to_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "auth.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        register_response = client.post(
            "/api/v1/users/register",
            json={"email": "User@Example.com", "password": "secret123", "name": "Test User"},
        )
        assert register_response.status_code == 201
        registered = register_response.json()
        assert registered["accessToken"]
        assert registered["refreshToken"]
        assert registered["user"] == {
            "id": registered["user"]["id"],
            "email": "user@example.com",
            "name": "Test User",
        }

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "secret123"},
        )
        assert login_response.status_code == 200
        logged_in = login_response.json()
        assert logged_in["user"]["email"] == "user@example.com"
        assert logged_in["user"]["name"] == "Test User"

        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {logged_in['accessToken']}"},
        )
        assert me_response.status_code == 200
        assert me_response.json() == {
            **logged_in["user"],
            "preferredLocale": None,
            "avatarUrl": None,
            "avatarUrlExpiresAt": None,
            "updatedAt": me_response.json()["updatedAt"],
        }

        unauthenticated_me = client.get("/api/v1/auth/me")
        assert unauthenticated_me.status_code == 401

        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": registered["refreshToken"]},
        )
        assert refresh_response.status_code == 200
        refreshed = refresh_response.json()
        assert refreshed["refreshToken"] != registered["refreshToken"]
        assert refreshed["user"]["email"] == "user@example.com"

        reused_refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": registered["refreshToken"]},
        )
        assert reused_refresh_response.status_code == 401

        logout_response = client.post(
            "/api/v1/auth/logout",
            json={"refreshToken": refreshed["refreshToken"]},
        )
        assert logout_response.status_code == 204

        logged_out_refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": refreshed["refreshToken"]},
        )
        assert logged_out_refresh_response.status_code == 401

    with open_database_connection(settings) as connection:
        user = connection.execute(
            "select id, email from users where email = 'user@example.com'"
        ).fetchone()
        membership = connection.execute(
            "select tenant_id, role from tenant_members where user_id = ?",
            (user["id"],),
        ).fetchone()
        tenant = connection.execute(
            "select type, owner_user_id from tenants where id = ?",
            (membership["tenant_id"],),
        ).fetchone()

    assert user["email"] == "user@example.com"
    assert membership["role"] == "admin"
    assert tenant["type"] == "personal"
    assert tenant["owner_user_id"] == user["id"]


def _profile_test_context(tmp_path: Path, name: str, **overrides):
    values = {
        "database_url": f"sqlite:///{tmp_path / name}",
        "default_tenant_id": "tenant_default",
        "jwt_secret": "test-secret-with-at-least-32-bytes",
        "avatar_url_ttl_seconds": 600,
    }
    values.update(overrides)
    settings = Settings(**values)
    store = FakeObjectStore()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_profile_object_store] = lambda: store
    return settings, store, test_app


def _register_profile_user(
    client: TestClient,
    *,
    email: str = "profile@example.com",
    name: str = "Profile User",
) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/api/v1/users/register",
        json={"email": email, "password": "secret123", "name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['accessToken']}"}


def _avatar_bytes(image_format: str, *, size: tuple[int, int] = (80, 60)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=(30, 120, 220)).save(output, format=image_format)
    return output.getvalue()


def _current_avatar_key(settings: Settings, user_id: str) -> str | None:
    with open_database_connection(settings) as connection:
        row = connection.execute(
            "select avatar_object_key from users where id = ?",
            (user_id,),
        ).fetchone()
    assert row is not None
    return row["avatar_object_key"]


def test_current_user_profile_read_patch_persistence_and_auth_compatibility(
    tmp_path: Path,
) -> None:
    settings, _, test_app = _profile_test_context(tmp_path, "profile.sqlite3")

    with TestClient(test_app) as client:
        registered, headers = _register_profile_user(client)
        assert set(registered["user"]) == {"id", "email", "name"}

        current = client.get("/api/v1/auth/me", headers=headers)
        assert current.status_code == 200
        assert current.json() == {
            "id": registered["user"]["id"],
            "email": "profile@example.com",
            "name": "Profile User",
            "preferredLocale": None,
            "avatarUrl": None,
            "avatarUrlExpiresAt": None,
            "updatedAt": current.json()["updatedAt"],
        }

        patched = client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"name": "  张三  ", "preferredLocale": "zh-CN"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "张三"
        assert patched.json()["preferredLocale"] == "zh-CN"

        locale_changed = client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"preferredLocale": "en-US"},
        )
        assert locale_changed.status_code == 200
        assert locale_changed.json()["name"] == "张三"
        assert locale_changed.json()["preferredLocale"] == "en-US"

        locale_cleared = client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"preferredLocale": None},
        )
        assert locale_cleared.status_code == 200
        assert locale_cleared.json()["preferredLocale"] is None

        omitted = client.patch("/api/v1/auth/me", headers=headers, json={})
        assert omitted.status_code == 200
        assert omitted.json()["name"] == "张三"
        assert omitted.json()["preferredLocale"] is None

        reread = client.get("/api/v1/auth/me", headers=headers)
        assert reread.status_code == 200
        assert reread.json()["name"] == "张三"
        assert reread.json()["preferredLocale"] is None

        refreshed = client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": registered["refreshToken"]},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["user"] == {
            "id": registered["user"]["id"],
            "email": "profile@example.com",
            "name": "张三",
        }

    with open_database_connection(settings) as connection:
        row = connection.execute(
            "select name, preferred_locale from users where id = ?",
            (registered["user"]["id"],),
        ).fetchone()
    assert row is not None
    assert row["name"] == "张三"
    assert row["preferred_locale"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "bad\nname"},
        {"name": "x" * 81},
        {"preferredLocale": "fr-FR"},
        {"email": "other@example.com"},
        {"status": "disabled"},
        {"roles": ["admin"]},
        {"userId": "user_other"},
    ],
)
def test_current_user_profile_rejects_invalid_or_privileged_fields(
    tmp_path: Path,
    payload: dict,
) -> None:
    _, _, test_app = _profile_test_context(tmp_path, f"invalid-{uuid4().hex}.sqlite3")
    with TestClient(test_app) as client:
        _, headers = _register_profile_user(client)
        response = client.patch("/api/v1/auth/me", headers=headers, json=payload)
    assert response.status_code == 422, response.text


def test_current_user_profile_does_not_change_admin_user_endpoint_permissions(
    tmp_path: Path,
) -> None:
    settings, _, test_app = _profile_test_context(tmp_path, "profile-permissions.sqlite3")
    with TestClient(test_app) as client:
        registered, user_headers = _register_profile_user(client)
        forbidden = client.patch(
            f"/api/v1/users/{registered['user']['id']}",
            headers=user_headers,
            json={"name": "Forbidden Rename"},
        )
        assert forbidden.status_code == 403

        _seed_platform_user(
            settings,
            "profile_admin",
            "profile-admin@example.com",
            "Profile Admin",
            "admin-secret",
            "admin",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "profile-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        allowed = client.patch(
            f"/api/v1/users/{registered['user']['id']}",
            headers=admin_headers,
            json={"name": "Admin Rename"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["name"] == "Admin Rename"


@pytest.mark.parametrize(
    ("image_format", "filename", "content_type"),
    [
        ("JPEG", "avatar.jpg", "image/jpeg"),
        ("PNG", "avatar.png", "image/png"),
        ("WEBP", "avatar.webp", "image/webp"),
    ],
)
def test_current_user_avatar_accepts_and_normalizes_supported_images(
    tmp_path: Path,
    image_format: str,
    filename: str,
    content_type: str,
) -> None:
    settings, store, test_app = _profile_test_context(
        tmp_path,
        f"avatar-{image_format.lower()}.sqlite3",
    )
    with TestClient(test_app) as client:
        registered, headers = _register_profile_user(client)
        response = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": (filename, _avatar_bytes(image_format), content_type)},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["avatarUrl"].startswith("https://minio.test/")
    assert body["avatarUrlExpiresAt"].endswith("Z")
    key = _current_avatar_key(settings, registered["user"]["id"])
    assert key is not None
    assert key.startswith(f"users/{registered['user']['id']}/avatars/")
    assert key.endswith(".webp")
    with Image.open(BytesIO(store.contents[key])) as normalized:
        assert normalized.format == "WEBP"
        assert normalized.size == (60, 60)
        assert normalized.getexif() == {}


def test_current_user_avatar_rejects_type_mismatch_svg_gif_and_corrupt_images(
    tmp_path: Path,
) -> None:
    _, _, test_app = _profile_test_context(tmp_path, "avatar-invalid.sqlite3")
    gif = _avatar_bytes("GIF")
    cases = [
        ("mismatch.png", _avatar_bytes("JPEG"), "image/png", 415, "AVATAR_UNSUPPORTED_TYPE"),
        ("avatar.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", 415, "AVATAR_UNSUPPORTED_TYPE"),
        ("avatar.gif", gif, "image/gif", 415, "AVATAR_UNSUPPORTED_TYPE"),
        ("avatar.png", b"not-an-image", "image/png", 400, "AVATAR_INVALID_IMAGE"),
    ]
    with TestClient(test_app) as client:
        _, headers = _register_profile_user(client)
        for filename, data, content_type, status, code in cases:
            response = client.put(
                "/api/v1/auth/me/avatar",
                headers=headers,
                files={"file": (filename, data, content_type)},
            )
            assert response.status_code == status, response.text
            assert response.json()["code"] == code


def test_current_user_avatar_rejects_byte_and_pixel_limits(tmp_path: Path) -> None:
    _, _, byte_limit_app = _profile_test_context(
        tmp_path,
        "avatar-byte-limit.sqlite3",
        avatar_max_upload_bytes=32,
    )
    with TestClient(byte_limit_app) as client:
        _, headers = _register_profile_user(client)
        too_large = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", b"x" * 33, "image/png")},
        )
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "AVATAR_TOO_LARGE"

    _, _, pixel_limit_app = _profile_test_context(
        tmp_path,
        "avatar-pixel-limit.sqlite3",
        avatar_max_pixels=10_000,
    )
    with TestClient(pixel_limit_app) as client:
        _, headers = _register_profile_user(client)
        too_many_pixels = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", _avatar_bytes("PNG", size=(101, 100)), "image/png")},
        )
    assert too_many_pixels.status_code == 400
    assert too_many_pixels.json()["code"] == "AVATAR_INVALID_IMAGE"


def test_current_user_avatar_replacement_uses_new_key_and_deletes_old_object(
    tmp_path: Path,
) -> None:
    settings, store, test_app = _profile_test_context(tmp_path, "avatar-replace.sqlite3")
    with TestClient(test_app) as client:
        registered, headers = _register_profile_user(client)
        first = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("first.png", _avatar_bytes("PNG"), "image/png")},
        )
        assert first.status_code == 200
        first_key = _current_avatar_key(settings, registered["user"]["id"])
        assert first_key is not None

        second = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("second.jpg", _avatar_bytes("JPEG"), "image/jpeg")},
        )
        assert second.status_code == 200
        second_key = _current_avatar_key(settings, registered["user"]["id"])

    assert second_key is not None
    assert second_key != first_key
    assert first_key in store.removed
    assert first_key not in store.contents
    assert second_key in store.contents


def test_current_user_avatar_database_failure_cleans_up_new_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, store, test_app = _profile_test_context(tmp_path, "avatar-db-failure.sqlite3")

    def fail_update(*_args, **_kwargs) -> bool:
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(ProfileRepository, "update_avatar_object_key", fail_update)
    with TestClient(test_app, raise_server_exceptions=False) as client:
        registered, headers = _register_profile_user(client)
        response = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", _avatar_bytes("PNG"), "image/png")},
        )

    assert response.status_code == 500
    assert store.contents == {}
    assert len(store.removed) == 1
    assert _current_avatar_key(settings, registered["user"]["id"]) is None


def test_current_user_avatar_old_delete_failure_does_not_rollback_replacement(
    tmp_path: Path,
) -> None:
    settings, store, test_app = _profile_test_context(
        tmp_path,
        "avatar-old-delete-failure.sqlite3",
    )
    with TestClient(test_app) as client:
        registered, headers = _register_profile_user(client)
        first = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("first.png", _avatar_bytes("PNG"), "image/png")},
        )
        assert first.status_code == 200
        old_key = _current_avatar_key(settings, registered["user"]["id"])
        assert old_key is not None
        store.fail_remove.add(old_key)

        replaced = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("second.webp", _avatar_bytes("WEBP"), "image/webp")},
        )
        assert replaced.status_code == 200, replaced.text
        new_key = _current_avatar_key(settings, registered["user"]["id"])

    assert new_key is not None
    assert new_key != old_key
    assert old_key in store.contents
    assert new_key in store.contents


def test_current_user_avatar_delete_is_idempotent(tmp_path: Path) -> None:
    settings, store, test_app = _profile_test_context(tmp_path, "avatar-delete.sqlite3")
    with TestClient(test_app) as client:
        registered, headers = _register_profile_user(client)
        uploaded = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", _avatar_bytes("PNG"), "image/png")},
        )
        assert uploaded.status_code == 200
        old_key = _current_avatar_key(settings, registered["user"]["id"])
        assert old_key is not None

        first_delete = client.delete("/api/v1/auth/me/avatar", headers=headers)
        second_delete = client.delete("/api/v1/auth/me/avatar", headers=headers)

    for response in (first_delete, second_delete):
        assert response.status_code == 200
        assert response.json()["avatarUrl"] is None
        assert response.json()["avatarUrlExpiresAt"] is None
    assert _current_avatar_key(settings, registered["user"]["id"]) is None
    assert old_key in store.removed


def test_current_user_profile_endpoints_require_authentication(tmp_path: Path) -> None:
    _, _, test_app = _profile_test_context(tmp_path, "profile-auth-required.sqlite3")
    with TestClient(test_app) as client:
        responses = [
            client.get("/api/v1/auth/me"),
            client.patch("/api/v1/auth/me", json={"name": "No Auth"}),
            client.put(
                "/api/v1/auth/me/avatar",
                files={"file": ("avatar.png", _avatar_bytes("PNG"), "image/png")},
            ),
            client.delete("/api/v1/auth/me/avatar"),
        ]
    assert [response.status_code for response in responses] == [401, 401, 401, 401]


def test_current_user_avatar_maps_object_store_failure_without_leaking_details(
    tmp_path: Path,
) -> None:
    _, store, test_app = _profile_test_context(tmp_path, "avatar-storage-failure.sqlite3")

    def fail_put(*_args, **_kwargs) -> None:
        raise RuntimeError("sensitive-storage-configuration")

    store.put = fail_put  # type: ignore[method-assign]
    with TestClient(test_app) as client:
        _, headers = _register_profile_user(client)
        response = client.put(
            "/api/v1/auth/me/avatar",
            headers=headers,
            files={"file": ("avatar.png", _avatar_bytes("PNG"), "image/png")},
        )

    assert response.status_code == 503
    assert response.json() == {
        "code": "OBJECT_STORE_UNAVAILABLE",
        "message": "Object storage is unavailable",
    }


class FakePasswordResetEmailService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str, str]] = []

    def send_password_reset_code(self, *, recipient: str, code: str, locale: str) -> None:
        self.sent.append((recipient, code, locale))
        if self.fail:
            raise EmailSendError("simulated delivery failure")


def _password_reset_settings(tmp_path: Path, name: str, **overrides) -> Settings:
    values = {
        "database_url": f"sqlite:///{tmp_path / name}",
        "default_tenant_id": "tenant_default",
        "jwt_secret": "test-secret-with-at-least-32-bytes",
    }
    values.update(overrides)
    return Settings(**values)


def _password_reset_app(settings: Settings, email_service: FakePasswordResetEmailService):
    test_app = create_app(settings)
    test_app.dependency_overrides[get_email_service] = lambda: email_service
    return test_app


def _register_password_reset_user(
    client: TestClient,
    *,
    email: str = "reset-user@example.com",
    password: str = "old-password",
    name: str = "Password Reset User",
) -> dict:
    response = client.post(
        "/api/v1/users/register",
        json={"email": email, "password": password, "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _different_six_digit_code(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def test_password_reset_request_is_uniform_cooled_down_and_hashed(tmp_path: Path) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-request.sqlite3")
    email_service = FakePasswordResetEmailService()
    expected = {"message": "如果该邮箱已注册，密码重置验证码将发送到该邮箱"}

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(client, email="Reset-User@Example.com")

        sent = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "  RESET-USER@example.com  ", "locale": "en-US"},
        )
        assert sent.status_code == 202
        assert sent.json() == expected
        assert len(email_service.sent) == 1
        assert email_service.sent[0][0] == "reset-user@example.com"
        assert email_service.sent[0][2] == "en-US"

        missing = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "missing@example.com"},
        )
        assert missing.status_code == 202
        assert missing.json() == expected
        assert len(email_service.sent) == 1

        repeated = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )
        assert repeated.status_code == 202
        assert repeated.json() == expected
        assert len(email_service.sent) == 1

    with open_database_connection(settings) as connection:
        rows = connection.execute(
            "select code_hash from password_reset_codes order by created_at"
        ).fetchall()

    assert len(rows) == 1
    delivered_code = email_service.sent[0][1]
    assert rows[0]["code_hash"] != delivered_code
    assert verify_password(delivered_code, rows[0]["code_hash"])


def test_password_reset_new_code_invalidates_previous_code(tmp_path: Path) -> None:
    settings = _password_reset_settings(
        tmp_path,
        "password-reset-replace.sqlite3",
        password_reset_cooldown_seconds=0,
    )
    email_service = FakePasswordResetEmailService()

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(client)
        first = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )
        second = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )
        assert first.status_code == second.status_code == 202
        assert len(email_service.sent) == 2

    with open_database_connection(settings) as connection:
        rows = connection.execute(
            """
            select used_at
            from password_reset_codes
            order by created_at asc
            """
        ).fetchall()

    assert len(rows) == 2
    assert rows[0]["used_at"] is not None
    assert rows[1]["used_at"] is None


def test_password_reset_wrong_code_counts_attempts_and_locks_after_five(tmp_path: Path) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-attempts.sqlite3")
    email_service = FakePasswordResetEmailService()

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(client)
        assert client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        ).status_code == 202
        correct_code = email_service.sent[0][1]
        wrong_code = _different_six_digit_code(correct_code)

        for _ in range(4):
            response = client.post(
                "/api/v1/auth/password-reset/confirm",
                json={
                    "email": "reset-user@example.com",
                    "code": wrong_code,
                    "newPassword": "new-password",
                },
            )
            assert response.status_code == 400
            assert response.json()["code"] == "AUTH_PASSWORD_RESET_CODE_INVALID"

        with open_database_connection(settings) as connection:
            before_limit = connection.execute(
                "select attempt_count, used_at from password_reset_codes"
            ).fetchone()
        assert before_limit["attempt_count"] == 4
        assert before_limit["used_at"] is None

        fifth = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": wrong_code,
                "newPassword": "new-password",
            },
        )
        assert fifth.status_code == 400

        locked = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": correct_code,
                "newPassword": "new-password",
            },
        )
        assert locked.status_code == 400

    with open_database_connection(settings) as connection:
        at_limit = connection.execute(
            "select attempt_count, used_at from password_reset_codes"
        ).fetchone()
    assert at_limit["attempt_count"] == 5
    assert at_limit["used_at"] is not None


def test_password_reset_expired_code_is_rejected(tmp_path: Path) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-expired.sqlite3")
    email_service = FakePasswordResetEmailService()

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(client)
        client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )
        code = email_service.sent[0][1]
        with open_database_connection(settings) as connection:
            connection.execute(
                "update password_reset_codes set expires_at = ?",
                ("2000-01-01T00:00:00+00:00",),
            )
            connection.commit()

        response = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": code,
                "newPassword": "new-password",
            },
        )
        assert response.status_code == 400
        assert response.json() == {
            "code": "AUTH_PASSWORD_RESET_CODE_INVALID",
            "message": "验证码无效或已过期",
        }


def test_password_reset_smtp_failure_invalidates_code(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-email-failure.sqlite3")
    email_service = FakePasswordResetEmailService(fail=True)
    caplog.set_level("ERROR")

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(client)
        response = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "code": "EMAIL_SEND_FAILED",
        "message": "密码重置邮件发送失败，请稍后重试",
    }
    with open_database_connection(settings) as connection:
        row = connection.execute(
            "select used_at from password_reset_codes"
        ).fetchone()
    assert row["used_at"] is not None
    attempted_code = email_service.sent[0][1]
    assert all(attempted_code not in record.getMessage() for record in caplog.records)
    assert all("reset-user@example.com" not in record.getMessage() for record in caplog.records)


def test_password_reset_success_changes_login_and_revokes_refresh_tokens(tmp_path: Path) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-success.sqlite3")
    email_service = FakePasswordResetEmailService()
    old_password = "old-password"
    new_password = "new-password"

    with TestClient(_password_reset_app(settings, email_service)) as client:
        registered = _register_password_reset_user(client, password=old_password)
        old_refresh_token = registered["refreshToken"]
        client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )
        code = email_service.sent[0][1]

        confirmed = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": code,
                "newPassword": new_password,
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json() == {"message": "密码重置成功，请重新登录"}

        reused = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": code,
                "newPassword": new_password,
            },
        )
        assert reused.status_code == 400

        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": "reset-user@example.com", "password": old_password},
        )
        assert old_login.status_code == 401

        new_login = client.post(
            "/api/v1/auth/login",
            json={"email": "reset-user@example.com", "password": new_password},
        )
        assert new_login.status_code == 200

        old_refresh = client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": old_refresh_token},
        )
        assert old_refresh.status_code == 401
        assert old_refresh.json()["code"] == "AUTH_REFRESH_REVOKED"

    with open_database_connection(settings) as connection:
        refresh = connection.execute(
            "select revoked_at from refresh_tokens where token_hash = ?",
            (hash_opaque_token(old_refresh_token),),
        ).fetchone()
    assert refresh["revoked_at"] is not None


def test_password_reset_disabled_and_pending_users_are_not_eligible(tmp_path: Path) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-status.sqlite3")
    email_service = FakePasswordResetEmailService()

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(
            client,
            email="disabled@example.com",
            name="Disabled User",
        )
        _register_password_reset_user(
            client,
            email="pending@example.com",
            name="Pending User",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                "update users set status = 'disabled' where email = ?",
                ("disabled@example.com",),
            )
            connection.execute(
                "update users set status = 'pending_activation' where email = ?",
                ("pending@example.com",),
            )
            connection.commit()

        for email in ("disabled@example.com", "pending@example.com"):
            requested = client.post(
                "/api/v1/auth/password-reset/request",
                json={"email": email},
            )
            assert requested.status_code == 202
            confirmed = client.post(
                "/api/v1/auth/password-reset/confirm",
                json={
                    "email": email,
                    "code": "000000",
                    "newPassword": "new-password",
                },
            )
            assert confirmed.status_code == 400

    assert email_service.sent == []
    with open_database_connection(settings) as connection:
        statuses = {
            row["email"]: row["status"]
            for row in connection.execute(
                "select email, status from users where email in (?, ?)",
                ("disabled@example.com", "pending@example.com"),
            ).fetchall()
        }
    assert statuses == {
        "disabled@example.com": "disabled",
        "pending@example.com": "pending_activation",
    }


def test_password_reset_confirm_is_single_consumer_under_concurrency(tmp_path: Path) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-concurrent.sqlite3")
    email_service = FakePasswordResetEmailService()

    with TestClient(_password_reset_app(settings, email_service)) as client:
        _register_password_reset_user(client)
        client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com"},
        )
        code = email_service.sent[0][1]

        def confirm_once():
            return client.post(
                "/api/v1/auth/password-reset/confirm",
                json={
                    "email": "reset-user@example.com",
                    "code": code,
                    "newPassword": "concurrent-password",
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: confirm_once(), range(2)))

        assert sorted(response.status_code for response in responses) == [200, 400]
        assert client.post(
            "/api/v1/auth/login",
            json={
                "email": "reset-user@example.com",
                "password": "concurrent-password",
            },
        ).status_code == 200


def test_password_reset_request_validation_rejects_bad_code_and_short_password(
    tmp_path: Path,
) -> None:
    settings = _password_reset_settings(tmp_path, "password-reset-validation.sqlite3")
    email_service = FakePasswordResetEmailService()

    with TestClient(_password_reset_app(settings, email_service)) as client:
        bad_code = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": "ABC123",
                "newPassword": "new-password",
            },
        )
        short_password = client.post(
            "/api/v1/auth/password-reset/confirm",
            json={
                "email": "reset-user@example.com",
                "code": "123456",
                "newPassword": "1234567",
            },
        )
        unsupported_locale = client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "reset-user@example.com", "locale": "fr-FR"},
        )

    assert bad_code.status_code == 422
    assert short_password.status_code == 422
    assert unsupported_locale.status_code == 422


@pytest.mark.parametrize(
    ("locale", "subject", "body_marker"),
    [
        ("zh-CN", "WinWise 密码重置验证码", "你正在重置 WinWise 登录密码"),
        ("en-US", "WinWise Password Reset Code", "You are resetting your WinWise"),
    ],
)
def test_email_service_uses_smtp_ssl_with_plain_and_html_parts(
    monkeypatch,
    locale: str,
    subject: str,
    body_marker: str,
) -> None:
    calls: dict[str, object] = {}

    class StubSmtpSsl:
        def __init__(self, **kwargs) -> None:
            calls["connect"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            calls["login"] = (username, password)

        def send_message(self, message, *, from_addr: str, to_addrs: list[str]) -> None:
            calls["message"] = message
            calls["envelope"] = (from_addr, to_addrs)

    monkeypatch.setattr("app.services.email_service.smtplib.SMTP_SSL", StubSmtpSsl)
    username = uuid4().hex
    password = uuid4().hex
    code = f"{secrets.randbelow(1_000_000):06d}"
    settings = Settings(
        smtp_server="smtp.example.invalid",
        smtp_port=465,
        smtp_username=username,
        smtp_password=password,
        smtp_from_address="no-reply@example.invalid",
        smtp_from_name="WinWise",
        smtp_use_ssl=True,
        smtp_timeout_seconds=7.5,
    )

    EmailService(settings).send_password_reset_code(
        recipient="recipient@example.invalid",
        code=code,
        locale=locale,
    )

    assert calls["login"] == (username, password)
    assert calls["connect"]["host"] == "smtp.example.invalid"
    assert calls["connect"]["port"] == 465
    assert calls["connect"]["timeout"] == 7.5
    message = calls["message"]
    assert message["Subject"] == subject
    plain_body = message.get_body(preferencelist=("plain",)).get_content()
    html_body = message.get_body(preferencelist=("html",)).get_content()
    assert code in plain_body
    assert code in html_body
    assert body_marker in plain_body
    assert body_marker in html_body


def test_platform_user_activation_updates_password_and_allows_login(tmp_path: Path) -> None:
    database_path = tmp_path / "activation.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    activation_token = "activation-token"

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into users (id, email, password_hash, name, status)
                values (?, ?, ?, ?, 'active')
                """,
                (
                    "admin_user",
                    "admin@example.com",
                    hash_password("placeholder"),
                    "Admin",
                ),
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values (?, ?, ?, ?)
                """,
                ("admin_member", "tenant_default", "admin_user", "admin"),
            )
            connection.execute(
                """
                insert into platform_activation_tokens
                  (id, user_id, token_hash, expires_at)
                values (?, ?, ?, ?)
                """,
                (
                    "activation_1",
                    "admin_user",
                    hash_opaque_token(activation_token),
                    "2999-01-01T00:00:00+00:00",
                ),
            )
            connection.commit()

        activation_response = client.post(
            "/api/v1/users/platform/activate",
            json={
                "token": activation_token,
                "newPassword": "new-secret",
                "name": "Platform User",
            },
        )
        assert activation_response.status_code == 200
        assert activation_response.json() == {
            "message": "Platform user activated",
            "userId": "admin_user",
            "email": "admin@example.com",
        }

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "new-secret"},
        )
        assert login_response.status_code == 200

    with open_database_connection(settings) as connection:
        token = connection.execute(
            "select used_at from platform_activation_tokens where id = 'activation_1'"
        ).fetchone()
        user = connection.execute("select name from users where id = 'admin_user'").fetchone()

    assert token["used_at"] is not None
    assert user["name"] == "Platform User"


def test_rbac_admin_lists_users_and_grants_roles(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "admin_user",
            "admin@example.com",
            "Admin User",
            "admin-secret",
            "admin",
        )
        _seed_tenant_user(
            settings,
            "target_user",
            "target@example.com",
            "Target User",
            "target-secret",
            "member",
        )

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-secret"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["accessToken"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-tenant-id": "tenant_default",
        }

        list_response = client.get("/api/v1/rbac/tenant/users", headers=headers)
        assert list_response.status_code == 200
        items = {item["id"]: item for item in list_response.json()["items"]}
        assert items["admin_user"]["tenantRoles"] == ["admin"]
        assert "tenant:user_manage" in items["admin_user"]["tenantPermissions"]
        assert "system:ops" not in items["admin_user"]["platformPermissions"]
        assert items["target_user"]["tenantRoles"] == ["member"]
        # Tenant roles only consume (chat); capability authoring is platform-side.
        assert "chat:ask" in items["target_user"]["tenantPermissions"]
        assert "kb:delete" not in items["target_user"]["tenantPermissions"]
        assert "tenant:user_manage" not in items["target_user"]["tenantPermissions"]

        grant_response = client.post(
            "/api/v1/rbac/tenant/users/target_user/roles",
            headers=headers,
            json={"role": "admin"},
        )
        assert grant_response.status_code == 204

        updated_response = client.get("/api/v1/rbac/tenant/users", headers=headers)
        assert updated_response.status_code == 200
        updated_items = {item["id"]: item for item in updated_response.json()["items"]}
        assert updated_items["target_user"]["tenantRoles"] == ["admin"]
        assert "tenant:user_manage" in updated_items["target_user"]["tenantPermissions"]

    with open_database_connection(settings) as connection:
        roles = [
            row["role"]
            for row in connection.execute(
                """
                select role from tenant_members
                where tenant_id = ? and user_id = ?
                order by created_at asc
                """,
                ("tenant_default", "target_user"),
            ).fetchall()
        ]

    assert roles == ["admin"]


def test_rbac_revoke_tenant_member_and_last_admin_guard(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_revoke.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings, "admin_user", "admin@example.com", "Admin User", "admin-secret", "admin"
        )
        _seed_tenant_user(
            settings, "target_user", "target@example.com", "Target User", "target-secret", "member"
        )

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-secret"},
        )
        access_token = login_response.json()["accessToken"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-tenant-id": "tenant_default",
        }

        # The sole admin cannot demote themselves to member.
        self_demote = client.post(
            "/api/v1/rbac/tenant/users/admin_user/roles",
            headers=headers,
            json={"role": "member"},
        )
        assert self_demote.status_code == 409

        # The sole admin cannot remove their own membership.
        self_remove = client.delete("/api/v1/rbac/tenant/users/admin_user", headers=headers)
        assert self_remove.status_code == 409

        # A regular member can be removed.
        remove_member = client.delete("/api/v1/rbac/tenant/users/target_user", headers=headers)
        assert remove_member.status_code == 204

        # Removing a non-member returns 404.
        remove_again = client.delete("/api/v1/rbac/tenant/users/target_user", headers=headers)
        assert remove_again.status_code == 404

    with open_database_connection(settings) as connection:
        members = connection.execute(
            "select user_id from tenant_members where tenant_id = 'tenant_default'"
        ).fetchall()

    assert [row["user_id"] for row in members] == ["admin_user"]


def test_rbac_tenant_role_changes_invalidate_existing_access_token(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_stale_tenant_token.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings, "admin_user", "admin@example.com", "Admin User", "admin-secret", "admin"
        )
        _seed_tenant_user(
            settings, "second_admin", "second@example.com", "Second Admin", "second-secret", "admin"
        )

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-secret"},
        )
        stale_headers = {
            "Authorization": f"Bearer {admin_login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        second_login = client.post(
            "/api/v1/auth/login",
            json={"email": "second@example.com", "password": "second-secret"},
        )
        second_headers = {
            "Authorization": f"Bearer {second_login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        remove_admin = client.delete(
            "/api/v1/rbac/tenant/users/admin_user", headers=second_headers
        )
        assert remove_admin.status_code == 204

        stale_request = client.get("/api/v1/rbac/tenant/users", headers=stale_headers)
        assert stale_request.status_code == 403


def test_rbac_platform_admin_grants_and_revokes_platform_role(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_platform_revoke.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings, "platform_admin", "padmin@example.com", "Platform Admin", "admin-secret", "admin"
        )
        _seed_user(settings, "target_user", "target@example.com", "Target User", "target-secret")

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "padmin@example.com", "password": "admin-secret"},
        )
        access_token = login_response.json()["accessToken"]
        headers = {"Authorization": f"Bearer {access_token}"}

        grant = client.post(
            "/api/v1/rbac/platform/users/target_user/roles",
            headers=headers,
            json={"role": "expert"},
        )
        assert grant.status_code == 204

        revoke = client.delete(
            "/api/v1/rbac/platform/users/target_user/roles/expert", headers=headers
        )
        assert revoke.status_code == 204

        # Revoking an already-absent role is idempotent.
        revoke_again = client.delete(
            "/api/v1/rbac/platform/users/target_user/roles/expert", headers=headers
        )
        assert revoke_again.status_code == 204

        missing_user = client.delete(
            "/api/v1/rbac/platform/users/missing_user/roles/expert", headers=headers
        )
        assert missing_user.status_code == 404

    with open_database_connection(settings) as connection:
        roles = connection.execute(
            "select role from platform_user_roles where user_id = 'target_user'"
        ).fetchall()

    assert roles == []


def test_rbac_platform_roles_list_requires_platform_role_grant(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_platform_roles.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings, "platform_admin", "padmin@example.com", "Platform Admin", "admin-secret", "admin"
        )

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "padmin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        response = client.get("/api/v1/rbac/platform/roles", headers=admin_headers)
        assert response.status_code == 200
        by_role = {item["role"]: item for item in response.json()["items"]}
        assert set(by_role) == {"admin", "expert", "operator"}
        assert by_role["admin"]["name"] == "admin"
        assert "platform:role_grant" in by_role["admin"]["permissions"]
        assert "kb:create" in by_role["expert"]["permissions"]
        assert "kb:read" in by_role["operator"]["permissions"]

        tenant_register = client.post(
            "/api/v1/users/register",
            json={"email": "tenant@example.com", "password": "secret123", "name": "Tenant User"},
        )
        assert tenant_register.status_code == 201
        tenant_headers = {"Authorization": f"Bearer {tenant_register.json()['accessToken']}"}
        forbidden = client.get("/api/v1/rbac/platform/roles", headers=tenant_headers)
        assert forbidden.status_code == 403


def test_rbac_platform_last_admin_guard(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_platform_last_admin.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings, "platform_admin", "padmin@example.com", "Platform Admin", "admin-secret", "admin"
        )

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "padmin@example.com", "password": "admin-secret"},
        )
        headers = {"Authorization": f"Bearer {login_response.json()['accessToken']}"}

        revoke_last_admin = client.delete(
            "/api/v1/rbac/platform/users/platform_admin/roles/admin", headers=headers
        )
        assert revoke_last_admin.status_code == 409


def test_rbac_platform_role_changes_invalidate_existing_access_token(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_stale_platform_token.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings, "platform_admin", "padmin@example.com", "Platform Admin", "admin-secret", "admin"
        )
        _seed_platform_user(
            settings, "expert_user", "expert@example.com", "Expert User", "expert-secret", "expert"
        )

        expert_login = client.post(
            "/api/v1/auth/login",
            json={"email": "expert@example.com", "password": "expert-secret"},
        )
        stale_headers = {"Authorization": f"Bearer {expert_login.json()['accessToken']}"}

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "padmin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        revoke_expert = client.delete(
            "/api/v1/rbac/platform/users/expert_user/roles/expert", headers=admin_headers
        )
        assert revoke_expert.status_code == 204

        stale_request = client.post(
            "/api/v1/knowledge-bases",
            headers=stale_headers,
            json={"name": "KB", "description": "test"},
        )
        assert stale_request.status_code == 403


def test_losing_tenant_membership_keeps_platform_access(tmp_path: Path) -> None:
    database_path = tmp_path / "stale_tenant_platform.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        # A user who is both a platform admin and a member of a team tenant.
        _seed_platform_user(
            settings, "dual_user", "dual@example.com", "Dual User", "dual-secret", "admin"
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenants (id, type, name, slug, status)
                values ('team_x', 'team', 'Team X', 'team-x', 'active')
                """
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('member_x', 'team_x', 'dual_user', 'member')
                """
            )
            connection.commit()

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "dual@example.com", "password": "dual-secret"},
        )
        # Token now carries activeTenantId=team_x.
        token = login.json()["accessToken"]
        platform_headers = {"Authorization": f"Bearer {token}"}

        # Simulate the user being removed from the team tenant.
        with open_database_connection(settings) as connection:
            connection.execute("delete from tenant_members where user_id = 'dual_user'")
            connection.commit()

        # Platform access must survive the loss of the tenant membership.
        platform_call = client.post(
            "/api/v1/users/platform",
            headers=platform_headers,
            json={"email": "invitee@example.com", "name": "Invitee", "roles": ["expert"]},
        )
        assert platform_call.status_code == 201

        with open_database_connection(settings) as connection:
            membership = connection.execute(
                """
                select role from tenant_members
                where tenant_id = 'tenant_default' and user_id = 'dual_user'
                """
            ).fetchone()
        assert membership is not None
        assert membership["role"] == "member"

        # The still-valid old token resolves to the fallback tenant without a re-login.
        default_call = client.get(
            "/api/v1/chat/sessions",
            headers={**platform_headers, "x-tenant-id": "tenant_default"},
        )
        assert default_call.status_code == 200

        # Tenant-scoped access for the now-stale tenant is still rejected.
        tenant_call = client.get(
            "/api/v1/rbac/tenant/users",
            headers={**platform_headers, "x-tenant-id": "team_x"},
        )
        assert tenant_call.status_code == 403


def test_tenantless_platform_user_is_attached_to_default_tenant(tmp_path: Path) -> None:
    database_path = tmp_path / "tenantless_platform_user.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_only",
            "platform-only@example.com",
            "Platform Only",
            "platform-secret",
            "expert",
        )

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-only@example.com", "password": "platform-secret"},
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }
        sessions = client.get("/api/v1/chat/sessions", headers=headers)
        assert sessions.status_code == 200
        assert sessions.json() == {"items": []}

        # Repeated login keeps one idempotent membership. Subscription creation stays
        # lazy until a plan or credit operation actually needs it.
        repeated = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-only@example.com", "password": "platform-secret"},
        )
        assert repeated.status_code == 200
        with open_database_connection(settings) as connection:
            membership = connection.execute(
                """
                select role, count(*) as membership_count
                from tenant_members
                where tenant_id = 'tenant_default' and user_id = 'platform_only'
                group by role
                """
            ).fetchone()
        assert membership is not None
        assert membership["role"] == "member"
        assert membership["membership_count"] == 1


def test_existing_active_tenant_is_preferred_over_default_tenant(tmp_path: Path) -> None:
    database_path = tmp_path / "existing_active_tenant.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "team_member",
            "team-member@example.com",
            "Team Member",
            "team-secret",
            "expert",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenants (id, type, name, slug, status)
                values ('team_existing', 'team', 'Existing Team', 'existing-team', 'active')
                """
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('member_existing', 'team_existing', 'team_member', 'member')
                """
            )
            connection.commit()

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "team-member@example.com", "password": "team-secret"},
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "team_existing",
        }
        assert client.get("/api/v1/chat/sessions", headers=headers).status_code == 200

        with open_database_connection(settings) as connection:
            default_membership = connection.execute(
                """
                select 1 from tenant_members
                where tenant_id = 'tenant_default' and user_id = 'team_member'
                """
            ).fetchone()
        assert default_membership is None

def test_rbac_ops_cannot_grant_admin(tmp_path: Path) -> None:
    database_path = tmp_path / "rbac_ops.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "ops_user",
            "ops@example.com",
            "Ops User",
            "ops-secret",
            "operator",
        )
        _seed_user(settings, "target_user", "target@example.com", "Target User", "target-secret")

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "ops@example.com", "password": "ops-secret"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["accessToken"]

        grant_response = client.post(
            "/api/v1/rbac/platform/users/target_user/roles",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            json={"role": "admin"},
        )
        assert grant_response.status_code == 403

        create_admin_response = client.post(
            "/api/v1/users/platform",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            json={
                "email": "new-admin@example.com",
                "name": "New Admin",
                "roles": ["admin"],
            },
        )
        assert create_admin_response.status_code == 403


def test_platform_admin_creates_platform_user_invitation_and_user_activates(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "platform_invite.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )

        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert login_response.status_code == 200
        access_token = login_response.json()["accessToken"]

        create_response = client.post(
            "/api/v1/users/platform",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "email": "Invited-Expert@Example.com",
                "name": "Invited Expert",
                "roles": ["expert"],
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["email"] == "invited-expert@example.com"
        assert created["status"] == "pending_activation"
        assert created["platformRoles"] == ["expert"]
        assert created["activationToken"]
        assert created["activationExpiresAt"]

        pending_login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "invited-expert@example.com", "password": "new-secret"},
        )
        assert pending_login_response.status_code == 401

        activation_response = client.post(
            "/api/v1/users/platform/activate",
            json={
                "token": created["activationToken"],
                "newPassword": "new-secret",
            },
        )
        assert activation_response.status_code == 200
        assert activation_response.json()["userId"] == created["id"]

        invited_login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "invited-expert@example.com", "password": "new-secret"},
        )
        assert invited_login_response.status_code == 200

    with open_database_connection(settings) as connection:
        user = connection.execute(
            "select id, status from users where email = 'invited-expert@example.com'"
        ).fetchone()
        roles = [
            row["role"]
            for row in connection.execute(
                "select role from platform_user_roles where user_id = ?",
                (user["id"],),
            ).fetchall()
        ]
        token = connection.execute(
            "select used_at from platform_activation_tokens where user_id = ?",
            (user["id"],),
        ).fetchone()

    assert user["status"] == "active"
    assert roles == ["expert"]
    assert token["used_at"] is not None


def test_platform_user_list_requires_platform_user_manage(tmp_path: Path) -> None:
    database_path = tmp_path / "platform_user_list.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        create_response = client.post(
            "/api/v1/users/platform",
            headers=admin_headers,
            json={
                "email": "invited-expert@example.com",
                "name": "Invited Expert",
                "roles": ["expert"],
            },
        )
        assert create_response.status_code == 201

        list_response = client.get("/api/v1/users/platform", headers=admin_headers)
        assert list_response.status_code == 200
        by_email = {item["email"]: item for item in list_response.json()["items"]}
        assert by_email["platform-admin@example.com"]["platformRoles"] == ["admin"]
        assert by_email["invited-expert@example.com"]["name"] == "Invited Expert"
        assert by_email["invited-expert@example.com"]["status"] == "pending_activation"
        assert by_email["invited-expert@example.com"]["platformRoles"] == ["expert"]
        assert "kb:create" in by_email["invited-expert@example.com"]["platformPermissions"]
        assert by_email["invited-expert@example.com"]["tenantRoles"] == []

        tenant_register = client.post(
            "/api/v1/users/register",
            json={"email": "tenant@example.com", "password": "secret123", "name": "Tenant User"},
        )
        assert tenant_register.status_code == 201
        tenant_headers = {"Authorization": f"Bearer {tenant_register.json()['accessToken']}"}
        forbidden = client.get("/api/v1/users/platform", headers=tenant_headers)
        assert forbidden.status_code == 403


def test_managed_users_crud_and_tenants_require_platform_user_manage(tmp_path: Path) -> None:
    database_path = tmp_path / "managed_users.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenants (id, type, name, slug, owner_user_id, status)
                values ('team_extra', 'team', 'Extra Team', 'extra-team', 'tenant_user', 'active')
                """
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('tenant_user_extra_member', 'team_extra', 'tenant_user', 'admin')
                """
            )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        list_response = client.get("/api/v1/users", headers=admin_headers)
        assert list_response.status_code == 200
        list_body = list_response.json()
        assert list_body["total"] == 1
        assert list_body["page"] == 1
        assert list_body["pageSize"] == 50
        listed_by_email = {item["email"]: item for item in list_body["items"]}
        assert "tenant@example.com" in listed_by_email
        assert "platform-admin@example.com" not in listed_by_email
        assert listed_by_email["tenant@example.com"]["tenantCount"] == 2
        assert listed_by_email["tenant@example.com"]["platformRoles"] == []

        detail = client.get("/api/v1/users/tenant_user", headers=admin_headers)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["email"] == "tenant@example.com"
        assert {tenant["id"] for tenant in detail_body["tenants"]} == {
            "tenant_default",
            "team_extra",
        }

        tenants = client.get("/api/v1/users/tenant_user/tenants", headers=admin_headers)
        assert tenants.status_code == 200
        assert len(tenants.json()["items"]) == 2

        patched = client.patch(
            "/api/v1/users/tenant_user",
            headers=admin_headers,
            json={"name": "Renamed Tenant User"},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed Tenant User"

        disabled = client.patch(
            "/api/v1/users/tenant_user/status",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"

        disabled_login = client.post(
            "/api/v1/auth/login",
            json={"email": "tenant@example.com", "password": "tenant-secret"},
        )
        assert disabled_login.status_code == 401

        missing = client.get("/api/v1/users/missing_user", headers=admin_headers)
        assert missing.status_code == 404

        tenant_register = client.post(
            "/api/v1/users/register",
            json={"email": "plain@example.com", "password": "secret123", "name": "Plain User"},
        )
        assert tenant_register.status_code == 201
        tenant_headers = {"Authorization": f"Bearer {tenant_register.json()['accessToken']}"}
        forbidden = client.get("/api/v1/users", headers=tenant_headers)
        assert forbidden.status_code == 403


def test_managed_users_include_subscription_usage_filters_and_detail(tmp_path: Path) -> None:
    database_path = tmp_path / "managed_users_subscription.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into subscriptions (
                  id,
                  tenant_id,
                  plan_id,
                  status,
                  billing_period,
                  current_period_start,
                  current_period_end,
                  cancel_at_period_end
                )
                values (
                  'sub_tenant_user_free',
                  'tenant_default',
                  'plan_free',
                  'active',
                  'free',
                  CURRENT_TIMESTAMP,
                  datetime('now', '+9 days'),
                  false
                )
                """
            )
            connection.execute(
                """
                insert into chat_sessions (
                  id,
                  tenant_id,
                  user_id,
                  title,
                  agent_options,
                  status
                )
                values (
                  'session_tenant_user',
                  'tenant_default',
                  'tenant_user',
                  'Usage Session',
                  '{}',
                  'active'
                )
                """
            )
            connection.execute(
                """
                insert into chat_turns (
                  id,
                  session_id,
                  tenant_id,
                  user_id,
                  request_text,
                  response_text,
                  status,
                  is_internal
                )
                values
                  (
                    'turn_tenant_user_1',
                    'session_tenant_user',
                    'tenant_default',
                    'tenant_user',
                    'Question 1',
                    'Answer 1',
                    'completed',
                    false
                  ),
                  (
                    'turn_tenant_user_2',
                    'session_tenant_user',
                    'tenant_default',
                    'tenant_user',
                    'Question 2',
                    'Answer 2',
                    'completed',
                    false
                  )
                """
            )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        response = client.get(
            "/api/v1/users",
            headers=admin_headers,
            params={
                "search": "Free",
                "subscriptionStatus": "expiring_soon",
                "subscriptionType": "Free · 免费",
                "sort": "subscriptionStart",
                "page": 1,
                "pageSize": 10,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["pageSize"] == 10
        item = body["items"][0]
        assert item["id"] == "tenant_user"
        assert item["currentSubscription"]["subscriptionId"] == "sub_tenant_user_free"
        assert item["currentSubscription"]["planName"] == "Free"
        assert item["currentSubscription"]["billingPeriod"] == "free"
        assert item["currentSubscription"]["status"] == "expiring_soon"
        assert "statusLabel" not in item["currentSubscription"]
        assert item["currentSubscription"]["priceLabel"] == "免费"
        assert "monthlyUsage" not in item
        assert item["orderSummary"] == {
            "totalAmountCents": 0,
            "orderCount": 0,
            "recentOrders": [],
        }
        assert item["usageLifetime"]["usageDays"] >= 1

        detail = client.get("/api/v1/users/tenant_user", headers=admin_headers)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["currentSubscription"]["tenantId"] == "tenant_default"
        assert "monthlyUsage" not in detail_body
        assert detail_body["tenants"][0]["id"] == "tenant_default"


def test_platform_tenant_management_crud_members_and_guards(tmp_path: Path) -> None:
    database_path = tmp_path / "tenant_management.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_user(settings, "owner_user", "owner@example.com", "Owner User", "owner-secret")
        _seed_user(settings, "member_user", "member@example.com", "Member User", "member-secret")

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        created = client.post(
            "/api/v1/tenants",
            headers=admin_headers,
            json={"name": "Acme Team", "slug": "acme-team", "ownerUserId": "owner_user"},
        )
        assert created.status_code == 201, created.text
        tenant = created.json()
        tenant_id = tenant["id"]
        assert tenant["type"] == "team"
        assert tenant["slug"] == "acme-team"
        assert tenant["ownerUserName"] == "Owner User"
        assert tenant["ownerUserEmail"] == "owner@example.com"
        assert tenant["memberCount"] == 1
        assert tenant["currentSubscription"]["planCode"] == "free"
        assert tenant["currentPlan"]["code"] == "free"
        assert tenant["monthlyCredits"] == {
            "monthlyCreditLimit": 2000,
            "estimatedUsedCredits": 0,
            "deductedCredits": 0,
            "remainingCredits": 2000,
            "enforcementEnabled": True,
        }

        listed = client.get("/api/v1/tenants", headers=admin_headers)
        assert listed.status_code == 200
        listed_body = listed.json()
        assert listed_body["total"] >= 1
        assert any(item["id"] == tenant_id for item in listed_body["items"])

        got = client.get(f"/api/v1/tenants/{tenant_id}", headers=admin_headers)
        assert got.status_code == 200
        got_body = got.json()
        assert got_body["memberCount"] == 1
        assert got_body["members"][0]["userId"] == "owner_user"

        members = client.get(f"/api/v1/tenants/{tenant_id}/members", headers=admin_headers)
        assert members.status_code == 200
        assert members.json()["items"] == [
            {
                "userId": "owner_user",
                "email": "owner@example.com",
                "name": "Owner User",
                "status": "active",
                "role": "admin",
                "joinedAt": members.json()["items"][0]["joinedAt"],
            }
        ]

        business = client.patch(
            f"/api/v1/tenants/{tenant_id}/subscription",
            headers=admin_headers,
            json={"planId": "plan_business", "billingPeriod": "yearly"},
        )
        assert business.status_code == 200, business.text

        added = client.post(
            f"/api/v1/tenants/{tenant_id}/members",
            headers=admin_headers,
            json={"userId": "member_user", "role": "member"},
        )
        assert added.status_code == 201
        assert added.json()["role"] == "member"

        promoted = client.patch(
            f"/api/v1/tenants/{tenant_id}/members/member_user",
            headers=admin_headers,
            json={"role": "admin"},
        )
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "admin"

        patched = client.patch(
            f"/api/v1/tenants/{tenant_id}",
            headers=admin_headers,
            json={"name": "Acme Renamed", "slug": "acme-renamed", "ownerUserId": "member_user"},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Acme Renamed"
        assert patched.json()["ownerUserName"] == "Member User"

        demoted_owner = client.patch(
            f"/api/v1/tenants/{tenant_id}/members/owner_user",
            headers=admin_headers,
            json={"role": "member"},
        )
        assert demoted_owner.status_code == 200
        assert demoted_owner.json()["role"] == "member"

        remove_last_admin = client.delete(
            f"/api/v1/tenants/{tenant_id}/members/member_user",
            headers=admin_headers,
        )
        assert remove_last_admin.status_code == 409

        disabled = client.patch(
            f"/api/v1/tenants/{tenant_id}/status",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"

        subscription = client.patch(
            f"/api/v1/tenants/{tenant_id}/subscription",
            headers=admin_headers,
            json={"planId": "plan_free", "billingPeriod": "free"},
        )
        assert subscription.status_code == 200, subscription.text
        assert subscription.json()["currentSubscription"]["planCode"] == "free"
        assert subscription.json()["currentSubscription"]["billingPeriod"] == "free"
        assert subscription.json()["currentPlan"]["id"] == "plan_free"

        duplicate = client.post(
            "/api/v1/tenants",
            headers=admin_headers,
            json={"name": "Duplicate", "slug": "acme-renamed", "ownerUserId": "owner_user"},
        )
        assert duplicate.status_code == 409

        missing_owner = client.post(
            "/api/v1/tenants",
            headers=admin_headers,
            json={"name": "Missing Owner", "slug": "missing-owner", "ownerUserId": "missing"},
        )
        assert missing_owner.status_code == 404


def test_tenant_management_subscription_usage_filters_and_personal_guards(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "tenant_management_subscription.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                update tenants
                set type = 'personal',
                    owner_user_id = 'tenant_user'
                where id = 'tenant_default'
                """
            )
            connection.execute(
                """
                insert into subscriptions (
                  id,
                  tenant_id,
                  plan_id,
                  status,
                  billing_period,
                  current_period_start,
                  current_period_end,
                  cancel_at_period_end
                )
                values (
                  'sub_tenant_default_free',
                  'tenant_default',
                  'plan_free',
                  'active',
                  'free',
                  CURRENT_TIMESTAMP,
                  datetime('now', '+9 days'),
                  false
                )
                """
            )
            connection.execute(
                """
                insert into chat_sessions (
                  id,
                  tenant_id,
                  user_id,
                  title,
                  agent_options,
                  status
                )
                values (
                  'session_tenant_default',
                  'tenant_default',
                  'tenant_user',
                  'Usage Session',
                  '{}',
                  'active'
                )
                """
            )
            connection.execute(
                """
                insert into chat_turns (
                  id,
                  session_id,
                  tenant_id,
                  user_id,
                  request_text,
                  response_text,
                  status,
                  is_internal
                )
                values
                  (
                    'turn_tenant_default_1',
                    'session_tenant_default',
                    'tenant_default',
                    'tenant_user',
                    'Question 1',
                    'Answer 1',
                    'completed',
                    false
                  ),
                  (
                    'turn_tenant_default_2',
                    'session_tenant_default',
                    'tenant_default',
                    'tenant_user',
                    'Question 2',
                    'Answer 2',
                    'completed',
                    false
                  )
                """
            )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        listed = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={
                "search": "Free",
                "type": "personal",
                "subscriptionType": "free",
                "subscriptionStatus": "expiring_soon",
                "sort": "monthlyCredits",
                "page": 1,
                "pageSize": 10,
            },
        )
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["id"] == "tenant_default"
        assert item["type"] == "personal"
        assert item["ownerUserEmail"] == "tenant@example.com"
        assert item["currentSubscription"]["subscriptionId"] == "sub_tenant_default_free"
        assert item["currentSubscription"]["status"] == "expiring_soon"
        # The backend exposes only the stable value; localized text is the frontend's job.
        assert "statusLabel" not in item["currentSubscription"]
        assert item["currentPlan"]["code"] == "free"
        assert item["monthlyCredits"] == {
            "monthlyCreditLimit": 4000,
            "estimatedUsedCredits": 0,
            "deductedCredits": 0,
            "remainingCredits": 4000,
            "enforcementEnabled": True,
        }
        assert item["orderSummary"] == {
            "totalAmountCents": 0,
            "orderCount": 0,
            "recentOrders": [],
        }

        # filter-options serves stable values accepted directly by the tenant-list endpoint. It
        # must resolve ahead of the /{tenant_id} route rather than being swallowed as a tenant id.
        options = client.get("/api/v1/tenants/filter-options", headers=admin_headers)
        assert options.status_code == 200, options.text
        options_body = options.json()
        assert options_body["tenantTypes"] == ["personal", "team"]
        assert options_body["subscriptionStatuses"] == [
            "active",
            "expiring_soon",
            "expired",
            "trialing",
            "past_due",
            "cancelled",
        ]
        assert options_body["subscriptionTypes"] == [
            {"value": "free", "label": "Free"},
            {"value": "monthly", "label": "Monthly"},
            {"value": "yearly", "label": "Yearly"},
            {"value": "sales", "label": "Sales"},
        ]

        detail = client.get("/api/v1/tenants/tenant_default", headers=admin_headers)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["members"] == []

        blocked = client.post(
            "/api/v1/tenants/tenant_default/members",
            headers=admin_headers,
            json={"userId": "platform_admin", "role": "member"},
        )
        assert blocked.status_code == 409

        tenant_register = client.post(
            "/api/v1/users/register",
            json={"email": "plain@example.com", "password": "secret123", "name": "Plain User"},
        )
        assert tenant_register.status_code == 201
        tenant_headers = {"Authorization": f"Bearer {tenant_register.json()['accessToken']}"}
        forbidden = client.get("/api/v1/tenants", headers=tenant_headers)
        assert forbidden.status_code == 403


def test_tenant_management_filters_latest_history_pagination_and_read_only(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "tenant_management_filters.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)
    now = datetime.now(timezone.utc)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_user(
            settings,
            "trialing_user",
            "trialing@example.com",
            "Trialing User",
            "trialing-secret",
        )
        _seed_user(
            settings,
            "legacy_user",
            "legacy@example.com",
            "Legacy User",
            "legacy-secret",
        )

        with open_database_connection(settings) as connection:
            connection.execute(
                """
                update plans
                set name = 'Business Plan',
                    description = 'Business plan for tenant-filter tests',
                    prices = '[{"id":"business-monthly","planId":"plan_business","billingPeriod":"monthly","currency":"CNY","amountCents":9900,"isEnabled":true},{"id":"business-yearly","planId":"plan_business","billingPeriod":"yearly","currency":"CNY","amountCents":99000,"isEnabled":true},{"id":"business-sales","planId":"plan_business","billingPeriod":"sales","currency":"CNY","amountCents":0,"isEnabled":true}]',
                    entitlements = '{"id":"business-entitlements","planId":"plan_business","monthlyCreditLimit":130000,"allExperts":true,"seatLimit":5,"singleTurnTokenLimit":null,"modelTiers":["core"],"features":{"teamManagement":true}}'
                where id = 'plan_business'
                """
            )
            connection.execute(
                """
                insert into tenants (id, type, name, slug, status)
                values
                  ('tenant_active', 'team', 'Active Tenant', 'active-tenant', 'active'),
                  ('tenant_expiring', 'personal', 'Expiring Tenant', 'expiring-tenant', 'active'),
                  ('tenant_expired', 'team', 'Expired Tenant', 'expired-tenant', 'active'),
                  ('tenant_trialing', 'personal', 'Trialing Tenant', 'trialing-tenant', 'active'),
                  ('tenant_past_due', 'team', 'Past Due Tenant', 'past-due-tenant', 'active'),
                  ('tenant_cancelled', 'personal', 'Cancelled Tenant', 'cancelled-tenant', 'active'),
                  ('tenant_cancel_at_end', 'team', 'Cancel At End Tenant', 'cancel-at-end', 'active'),
                  ('tenant_history', 'team', 'History Tenant', 'history-tenant', 'active'),
                  ('tenant_yearly', 'personal', 'Yearly Tenant', 'yearly-tenant', 'active'),
                  ('tenant_sales', 'personal', 'Sales Tenant', 'sales-tenant', 'active'),
                  ('tenant_without_subscription', 'personal', 'No Subscription', 'no-subscription', 'active')
                """
            )
            subscriptions = [
                (
                    "sub_active",
                    "tenant_active",
                    "plan_business",
                    "active",
                    "monthly",
                    now - timedelta(days=5),
                    now + timedelta(days=30),
                    False,
                ),
                (
                    "sub_expiring",
                    "tenant_expiring",
                    "plan_free",
                    "active",
                    "free",
                    now - timedelta(days=5),
                    now + timedelta(days=7),
                    False,
                ),
                (
                    "sub_expired_period",
                    "tenant_expired",
                    "plan_free",
                    "active",
                    "free",
                    now - timedelta(days=30),
                    now - timedelta(seconds=1),
                    False,
                ),
                (
                    "sub_trialing",
                    "tenant_trialing",
                    "plan_business",
                    "trialing",
                    "monthly",
                    now - timedelta(days=2),
                    now + timedelta(days=30),
                    False,
                ),
                (
                    "sub_past_due",
                    "tenant_past_due",
                    "plan_business",
                    "past_due",
                    "monthly",
                    now - timedelta(days=10),
                    now + timedelta(days=20),
                    False,
                ),
                (
                    "sub_cancelled",
                    "tenant_cancelled",
                    "plan_free",
                    "cancelled",
                    "free",
                    now - timedelta(days=20),
                    now + timedelta(days=10),
                    False,
                ),
                (
                    "sub_cancel_at_end",
                    "tenant_cancel_at_end",
                    "plan_business",
                    "active",
                    "monthly",
                    now - timedelta(days=1),
                    now + timedelta(days=30),
                    True,
                ),
                (
                    "sub_history_old",
                    "tenant_history",
                    "plan_free",
                    "cancelled",
                    "free",
                    now - timedelta(days=60),
                    now - timedelta(days=30),
                    False,
                ),
                (
                    "sub_history_new",
                    "tenant_history",
                    "plan_business",
                    "trialing",
                    "monthly",
                    now - timedelta(days=3),
                    now + timedelta(days=20),
                    False,
                ),
                (
                    "sub_yearly",
                    "tenant_yearly",
                    "plan_business",
                    "active",
                    "yearly",
                    now - timedelta(days=4),
                    now + timedelta(days=30),
                    False,
                ),
                (
                    "sub_sales",
                    "tenant_sales",
                    "plan_business",
                    "active",
                    "sales",
                    now - timedelta(days=4),
                    now + timedelta(days=30),
                    False,
                ),
            ]
            connection.executemany(
                """
                insert into subscriptions (
                  id, tenant_id, plan_id, status, billing_period,
                  current_period_start, current_period_end, cancel_at_period_end
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        subscription_id,
                        tenant_id,
                        plan_id,
                        status,
                        billing_period,
                        period_start.isoformat(),
                        period_end.isoformat(),
                        cancel_at_period_end,
                    )
                    for (
                        subscription_id,
                        tenant_id,
                        plan_id,
                        status,
                        billing_period,
                        period_start,
                        period_end,
                        cancel_at_period_end,
                    ) in subscriptions
                ],
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values
                  ('trialing_user_member', 'tenant_trialing', 'trialing_user', 'member'),
                  ('legacy_user_member', 'tenant_without_subscription', 'legacy_user', 'admin')
                """
            )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        assert admin_login.status_code == 200
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        with open_database_connection(settings) as connection:
            subscriptions_before = connection.execute(
                "select count(*) from subscriptions"
            ).fetchone()[0]

        options = client.get("/api/v1/tenants/filter-options", headers=admin_headers)
        assert options.status_code == 200, options.text
        options_body = options.json()
        assert options_body["tenantTypes"] == ["personal", "team"]
        assert options_body["subscriptionStatuses"] == [
            "active",
            "expiring_soon",
            "expired",
            "trialing",
            "past_due",
            "cancelled",
        ]
        assert options_body["subscriptionTypes"] == [
            {"value": "free", "label": "Free"},
            {"value": "monthly", "label": "Monthly"},
            {"value": "yearly", "label": "Yearly"},
            {"value": "sales", "label": "Sales"},
        ]

        for option in options_body["subscriptionTypes"]:
            by_subscription_type = client.get(
                "/api/v1/tenants",
                headers=admin_headers,
                params={"subscriptionType": option["value"], "pageSize": 100},
            )
            assert by_subscription_type.status_code == 200, by_subscription_type.text
            assert by_subscription_type.json()["total"] > 0
            assert {
                item["currentSubscription"]["billingPeriod"]
                for item in by_subscription_type.json()["items"]
            } == {option["value"]}

        expected_status_ids = {
            "active": {
                "tenant_active",
                "tenant_cancel_at_end",
                "tenant_yearly",
                "tenant_sales",
            },
            "expiring_soon": {"tenant_expiring"},
            "expired": {"tenant_expired"},
            "trialing": {"tenant_trialing", "tenant_history"},
            "past_due": {"tenant_past_due"},
            "cancelled": {"tenant_cancelled"},
        }
        for status, expected_ids in expected_status_ids.items():
            by_status = client.get(
                "/api/v1/tenants",
                headers=admin_headers,
                params={"subscriptionStatus": status, "pageSize": 100},
            )
            assert by_status.status_code == 200, by_status.text
            assert {item["id"] for item in by_status.json()["items"]} == expected_ids
            assert by_status.json()["total"] == len(expected_ids)

        personal = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"type": "personal", "pageSize": 100},
        )
        team = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"type": "team", "pageSize": 100},
        )
        assert personal.status_code == 200
        assert team.status_code == 200
        assert {item["type"] for item in personal.json()["items"]} == {"personal"}
        assert {item["type"] for item in team.json()["items"]} == {"team"}

        combined = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={
                "type": "personal",
                "subscriptionType": "monthly",
                "subscriptionStatus": "trialing",
            },
        )
        assert combined.status_code == 200, combined.text
        assert combined.json()["total"] == 1
        assert [item["id"] for item in combined.json()["items"]] == ["tenant_trialing"]

        team_page_1 = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"type": "team", "page": 1, "pageSize": 2},
        )
        team_page_2 = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"type": "team", "page": 2, "pageSize": 2},
        )
        team_page_3 = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"type": "team", "page": 3, "pageSize": 2},
        )
        assert team_page_1.status_code == 200
        assert team_page_2.status_code == 200
        assert team_page_3.status_code == 200
        assert team_page_1.json()["total"] == 6
        assert team_page_2.json()["total"] == 6
        assert team_page_3.json()["total"] == 6
        page_1_ids = {item["id"] for item in team_page_1.json()["items"]}
        page_2_ids = {item["id"] for item in team_page_2.json()["items"]}
        page_3_ids = {item["id"] for item in team_page_3.json()["items"]}
        assert len(page_1_ids) == 2
        assert len(page_2_ids) == 2
        assert len(page_3_ids) == 2
        assert page_1_ids.isdisjoint(page_2_ids)
        assert page_1_ids.isdisjoint(page_3_ids)
        assert page_2_ids.isdisjoint(page_3_ids)
        assert page_1_ids | page_2_ids | page_3_ids == {
            "tenant_active",
            "tenant_expired",
            "tenant_past_due",
            "tenant_cancel_at_end",
            "tenant_history",
            "tenant_default",
        }

        history = client.get("/api/v1/tenants/tenant_history", headers=admin_headers)
        assert history.status_code == 200
        assert history.json()["currentSubscription"]["subscriptionId"] == "sub_history_new"
        assert history.json()["currentSubscription"]["status"] == "trialing"

        cancel_at_end = client.get(
            "/api/v1/tenants/tenant_cancel_at_end",
            headers=admin_headers,
        )
        assert cancel_at_end.status_code == 200
        assert cancel_at_end.json()["currentSubscription"]["status"] == "active"
        assert cancel_at_end.json()["currentSubscription"]["cancelAtPeriodEnd"] is True
        assert cancel_at_end.json()["currentSubscription"]["autoRenew"] is False

        no_subscription = client.get(
            "/api/v1/tenants/tenant_without_subscription",
            headers=admin_headers,
        )
        assert no_subscription.status_code == 200
        assert no_subscription.json()["currentSubscription"] is None
        assert no_subscription.json()["currentPlan"] is None
        assert no_subscription.json()["monthlyCredits"]["remainingCredits"] == 0

        invalid_type = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"type": "enterprise"},
        )
        invalid_status = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"subscriptionStatus": "unknown"},
        )
        invalid_subscription_type = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"subscriptionType": "weekly"},
        )
        assert invalid_type.status_code == 422
        assert invalid_status.status_code == 422
        assert invalid_subscription_type.status_code == 422

        with open_database_connection(settings) as connection:
            subscriptions_after_management_reads = connection.execute(
                "select count(*) from subscriptions"
            ).fetchone()[0]
            cancelled_rows = connection.execute(
                """
                select id, status
                from subscriptions
                where tenant_id = 'tenant_cancelled'
                order by current_period_start desc
                """
            ).fetchall()
        assert subscriptions_after_management_reads == subscriptions_before
        assert [(row["id"], row["status"]) for row in cancelled_rows] == [
            ("sub_cancelled", "cancelled")
        ]

        managed_user = client.get("/api/v1/users/trialing_user", headers=admin_headers)
        assert managed_user.status_code == 200
        assert managed_user.json()["currentSubscription"]["status"] == "active"

        legacy_login = client.post(
            "/api/v1/auth/login",
            json={"email": "legacy@example.com", "password": "legacy-secret"},
        )
        assert legacy_login.status_code == 200
        legacy_headers = {"Authorization": f"Bearer {legacy_login.json()['accessToken']}"}
        market_current = client.get(
            "/api/v1/plan-market/current-subscription",
            headers=legacy_headers,
        )
        assert market_current.status_code == 200, market_current.text
        assert market_current.json()["subscription"]["planId"] == "plan_free"
        assert market_current.json()["subscription"]["status"] == "active"

        with open_database_connection(settings) as connection:
            subscriptions_after_market_read = connection.execute(
                "select count(*) from subscriptions"
            ).fetchone()[0]
        assert subscriptions_after_market_read == subscriptions_before + 1


def test_expert_category_crud_permissions_and_delete_guard(tmp_path: Path) -> None:
    database_path = tmp_path / "expert_categories.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_platform_user(
            settings,
            "operator_user",
            "operator@example.com",
            "Operator User",
            "operator-secret",
            "operator",
        )

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        created = client.post(
            "/api/v1/expert-categories",
            headers=admin_headers,
            json={"name": "Amazon Operations", "description": "Marketplace experts"},
        )
        assert created.status_code == 201, created.text
        category = created.json()
        assert category["name"] == "Amazon Operations"
        assert category["description"] == "Marketplace experts"

        listed = client.get("/api/v1/expert-categories", headers=admin_headers)
        assert listed.status_code == 200
        assert any(item["id"] == category["id"] for item in listed.json()["items"])

        got = client.get(f"/api/v1/expert-categories/{category['id']}", headers=admin_headers)
        assert got.status_code == 200
        assert got.json()["id"] == category["id"]

        patched = client.patch(
            f"/api/v1/expert-categories/{category['id']}",
            headers=admin_headers,
            json={"name": "Amazon Growth", "description": None},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Amazon Growth"
        assert patched.json()["description"] == "Marketplace experts"

        duplicate = client.post(
            "/api/v1/expert-categories",
            headers=admin_headers,
            json={"name": "Amazon Growth"},
        )
        assert duplicate.status_code == 409

        operator_login = client.post(
            "/api/v1/auth/login",
            json={"email": "operator@example.com", "password": "operator-secret"},
        )
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['accessToken']}"}
        operator_list = client.get("/api/v1/expert-categories", headers=operator_headers)
        assert operator_list.status_code == 200
        operator_create = client.post(
            "/api/v1/expert-categories",
            headers=operator_headers,
            json={"name": "Operator Category"},
        )
        assert operator_create.status_code == 403

        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into experts (id, category_id, name, ability_intro, status)
                values ('expert_in_use', ?, 'In Use', 'Used by delete guard.', 'draft')
                """,
                (category["id"],),
            )
            connection.commit()

        in_use_delete = client.delete(
            f"/api/v1/expert-categories/{category['id']}", headers=admin_headers
        )
        assert in_use_delete.status_code == 409

        with open_database_connection(settings) as connection:
            connection.execute("delete from experts where id = 'expert_in_use'")
            connection.commit()

        deleted = client.delete(
            f"/api/v1/expert-categories/{category['id']}", headers=admin_headers
        )
        assert deleted.status_code == 204
        missing = client.get(f"/api/v1/expert-categories/{category['id']}", headers=admin_headers)
        assert missing.status_code == 404


def test_expert_crud_relations_status_and_permissions(tmp_path: Path) -> None:
    database_path = tmp_path / "experts.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    class FakeConnectorGateway:
        def __init__(self) -> None:
            self.list_calls = 0

        async def list_mcp_services(self) -> list[GatewayMcpService]:
            self.list_calls += 1
            return [
                GatewayMcpService(
                    id="z-disabled",
                    name="Disabled Connector",
                    description="Must not be listed",
                    transport="stdio",
                    disabled=True,
                ),
                GatewayMcpService(
                    id="local_test",
                    name="Local MCP test",
                    description="System acceptance Connector",
                    transport="streamable_http",
                ),
                GatewayMcpService(
                    id="alpha",
                    name="Alpha Connector",
                    description="Sorted before local_test",
                    transport="stdio",
                ),
            ]

    connector_gateway = FakeConnectorGateway()
    test_app.dependency_overrides[get_gateway_admin_client] = lambda: connector_gateway

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_platform_user(
            settings,
            "operator_user",
            "operator@example.com",
            "Operator User",
            "operator-secret",
            "operator",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_ops', 'Operations', 'Operations experts')
                """
            )
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_growth', 'Growth', 'Growth experts')
                """
            )
            connection.execute(
                """
                insert into skills (
                  id, slug, name, description, allowed_tools, file_paths, tags, storage_uri
                )
                values (
                  'skill_ops', 'ops-skill', 'Ops Skill', 'Ops helper', '[]', '[]', '[]',
                  'local://ops-skill'
                )
                """
            )
            connection.execute(
                """
                insert into skills (
                  id, slug, name, description, allowed_tools, file_paths, tags, storage_uri
                )
                values (
                  'skill_growth', 'growth-skill', 'Growth Skill', 'Growth helper', '[]',
                  '[]', '[]', 'local://growth-skill'
                )
                """
            )
            connection.execute(
                """
                insert into knowledge_bases (id, owner_user_id, name, status, metadata)
                values ('kb_ops', 'platform_admin', 'Ops KB', 'active', '{}')
                """
            )
            connection.execute(
                """
                insert into knowledge_bases (id, owner_user_id, name, status, metadata)
                values ('kb_growth', 'platform_admin', 'Growth KB', 'active', '{}')
                """
            )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        connectors = client.get("/api/v1/mcp-connectors", headers=admin_headers)
        assert connectors.status_code == 200
        assert connectors.json()["items"] == [
            {
                "id": "alpha",
                "name": "Alpha Connector",
                "description": "Sorted before local_test",
                "transport": "stdio",
            },
            {
                "id": "local_test",
                "name": "Local MCP test",
                "description": "System acceptance Connector",
                "transport": "streamable_http",
            },
        ]
        assert connector_gateway.list_calls == 1

        created = client.post(
            "/api/v1/experts",
            headers=admin_headers,
            json={
                "name": "Listing Expert",
                "categoryId": "expert_cat_ops",
                "abilityIntro": "Helps optimize listings.",
                "localizedContent": {
                    "zh": {"name": "Listing Expert", "abilityIntro": "帮助优化商品详情。", "categoryName": "运营"},
                    "en": {"name": "Listing Expert", "abilityIntro": "Helps optimize listings.", "categoryName": "Operations"},
                },
                "tags": ["listing", "ops", "listing"],
                "skillIds": ["skill_ops"],
                "knowledgeBaseIds": ["kb_ops"],
                "guideQuestions": ["How to improve listing?", "Why did traffic drop?"],
                "summonButtonText": "Ask expert",
                "mcpConnectorIds": ["local_test"],
            },
        )
        assert created.status_code == 201, created.text
        expert = created.json()
        expert_id = expert["id"]
        assert re.fullmatch(r"[0-9a-f]{16}", expert_id)
        assert expert["status"] == "draft"
        assert "expertKey" not in expert
        assert expert["categoryName"] == "Operations"
        assert expert["localizedContent"]["zh"]["categoryName"] == "运营"
        assert expert["localizedContent"]["en"]["abilityIntro"] == "Helps optimize listings."
        assert expert["tags"] == ["listing", "ops"]
        assert expert["marketLabels"] == []
        assert expert["skillIds"] == ["skill_ops"]
        assert expert["knowledgeBaseIds"] == ["kb_ops"]
        assert expert["mcpConnectorIds"] == ["local_test"]
        assert "mcpServers" not in expert
        assert expert["runtimeConfig"]["codex"]["model"] == "gpt-5.5"
        assert connector_gateway.list_calls == 1

        hot_created = client.post(
            "/api/v1/experts",
            headers=admin_headers,
            json={
                "name": "Hot Expert",
                "categoryId": "expert_cat_ops",
                "abilityIntro": "Featured expert.",
                "marketLabels": ["hot", "hot"],
            },
        )
        assert hot_created.status_code == 201, hot_created.text
        assert hot_created.json()["marketLabels"] == ["hot"]

        listed = client.get("/api/v1/experts", headers=admin_headers)
        assert listed.status_code == 200
        listed_expert = next(item for item in listed.json()["items"] if item["id"] == expert_id)
        assert listed_expert["marketLabels"] == []

        got = client.get(f"/api/v1/experts/{expert_id}", headers=admin_headers)
        assert got.status_code == 200
        assert got.json()["marketLabels"] == []
        assert got.json()["guideQuestions"] == [
            "How to improve listing?",
            "Why did traffic drop?",
        ]

        mcp_patched = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"mcpConnectorIds": ["policy"]},
        )
        assert mcp_patched.status_code == 200
        assert mcp_patched.json()["mcpConnectorIds"] == ["policy"]
        assert connector_gateway.list_calls == 1

        duplicate_connectors = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"mcpConnectorIds": ["policy", "policy"]},
        )
        assert duplicate_connectors.status_code == 400
        assert duplicate_connectors.json()["code"] == "EXPERT_MCP_CONNECTOR_DUPLICATE"

        empty_connector = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"mcpConnectorIds": [" "]},
        )
        assert empty_connector.status_code == 400
        assert empty_connector.json()["code"] == "EXPERT_MCP_CONNECTOR_ID_INVALID"

        legacy_mcp_servers = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"mcpServers": []},
        )
        assert legacy_mcp_servers.status_code == 422

        with open_database_connection(settings) as connection:
            row = connection.execute(
                "select mcp_connector_ids from experts where id = ?",
                (expert_id,),
            ).fetchone()
            columns = {
                str(item["name"])
                for item in connection.execute("pragma table_info(experts)").fetchall()
            }
        assert row is not None
        assert json.loads(row["mcp_connector_ids"]) == ["policy"]
        assert "mcp_servers" not in columns

        set_hot = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"marketLabels": ["hot"]},
        )
        assert set_hot.status_code == 200
        assert set_hot.json()["marketLabels"] == ["hot"]

        invalid_label = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"marketLabels": ["unknown"]},
        )
        assert invalid_label.status_code == 422

        patched = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={
                "name": "Growth Expert",
                "categoryId": "expert_cat_growth",
                "abilityIntro": "Helps grow conversion.",
                "localizedContent": {
                    "zh": {"name": "增长专家", "abilityIntro": "帮助提升转化。", "categoryName": "增长"},
                    "en": {"name": "Growth Expert", "abilityIntro": "Helps grow conversion.", "categoryName": "Growth"},
                },
                "tags": ["growth"],
                "skillIds": ["skill_growth"],
                "knowledgeBaseIds": ["kb_growth"],
                "guideQuestions": [],
                "summonButtonText": "Start",
            },
        )
        assert patched.status_code == 200
        patched_body = patched.json()
        assert patched_body["name"] == "Growth Expert"
        assert patched_body["categoryName"] == "Growth"
        assert patched_body["localizedContent"]["zh"]["name"] == "增长专家"
        assert patched_body["marketLabels"] == ["hot"]
        assert patched_body["skillIds"] == ["skill_growth"]
        assert patched_body["knowledgeBaseIds"] == ["kb_growth"]
        assert patched_body["guideQuestions"] == []

        cleared_labels = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"marketLabels": []},
        )
        assert cleared_labels.status_code == 200
        assert cleared_labels.json()["marketLabels"] == []

        restored_hot = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"marketLabels": ["hot"]},
        )
        assert restored_hot.status_code == 200
        assert restored_hot.json()["marketLabels"] == ["hot"]

        # A soft-deleted knowledge base must drop out of the expert's knowledgeBaseIds
        # (the join-table ON DELETE CASCADE only fires at GC purge time).
        with open_database_connection(settings) as connection:
            connection.execute(
                "update knowledge_bases set deleted_at = '2026-06-09T00:00:00+00:00'"
                " where id = ?",
                ("kb_growth",),
            )
            connection.commit()
        after_soft_delete = client.get(f"/api/v1/experts/{expert_id}", headers=admin_headers)
        assert after_soft_delete.status_code == 200
        assert after_soft_delete.json()["knowledgeBaseIds"] == []

        missing_skill = client.post(
            "/api/v1/experts",
            headers=admin_headers,
            json={
                "name": "Broken Expert",
                "categoryId": "expert_cat_ops",
                "abilityIntro": "Broken.",
                "skillIds": ["missing_skill"],
            },
        )
        assert missing_skill.status_code == 404

        too_many_kbs = client.post(
            "/api/v1/experts",
            headers=admin_headers,
            json={
                "name": "Multi KB Expert",
                "categoryId": "expert_cat_ops",
                "abilityIntro": "Broken.",
                "knowledgeBaseIds": ["kb_ops", "kb_growth"],
            },
        )
        assert too_many_kbs.status_code == 422

        too_many_kbs_patch = client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=admin_headers,
            json={"knowledgeBaseIds": ["kb_ops", "kb_growth"]},
        )
        assert too_many_kbs_patch.status_code == 422

        too_many_questions = client.post(
            "/api/v1/experts",
            headers=admin_headers,
            json={
                "name": "Too Many Questions",
                "categoryId": "expert_cat_ops",
                "abilityIntro": "Too many.",
                "guideQuestions": ["q1", "q2", "q3", "q4"],
            },
        )
        assert too_many_questions.status_code == 422

        operator_login = client.post(
            "/api/v1/auth/login",
            json={"email": "operator@example.com", "password": "operator-secret"},
        )
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['accessToken']}"}
        operator_list = client.get("/api/v1/experts", headers=operator_headers)
        assert operator_list.status_code == 200
        operator_create = client.post(
            "/api/v1/experts",
            headers=operator_headers,
            json={
                "name": "Operator Expert",
                "categoryId": "expert_cat_ops",
                "abilityIntro": "Not allowed.",
            },
        )
        assert operator_create.status_code == 403

        deleted = client.delete(f"/api/v1/experts/{expert_id}", headers=admin_headers)
        assert deleted.status_code == 204
        missing = client.get(f"/api/v1/experts/{expert_id}", headers=admin_headers)
        assert missing.status_code == 404
        with open_database_connection(settings) as connection:
            links = connection.execute(
                "select id from expert_skills where expert_id = ?", (expert_id,)
            ).fetchall()
        assert links == []


def test_expert_delete_detaches_soft_deleted_chat_history(tmp_path: Path) -> None:
    database_path = tmp_path / "expert_delete_history.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        created = client.post(
            "/api/v1/experts",
            headers=headers,
            json={
                "name": "Expert with deleted history",
                "categoryId": "expert_category_default",
                "abilityIntro": "Deletion regression.",
            },
        )
        assert created.status_code == 201, created.text
        expert_id = created.json()["id"]

        with open_database_connection(settings) as connection:
            user_id = connection.execute(
                "select id from users where email = ?",
                ("platform-admin@example.com",),
            ).fetchone()[0]
            connection.execute(
                """
                insert into tenants (id, slug, name, status)
                values ('tenant_delete_history', 'tenant-delete-history',
                        'Delete History', 'active')
                """
            )
            connection.execute(
                """
                insert into chat_sessions
                  (id, user_id, tenant_id, title, status, deleted_at, expert_id,
                   runtime_type)
                values
                  ('session_deleted_history', ?, 'tenant_delete_history', 'Deleted',
                   'active', CURRENT_TIMESTAMP, ?, 'codex')
                """,
                (user_id, expert_id),
            )
            connection.execute(
                """
                insert into chat_turns
                  (id, session_id, tenant_id, user_id, request_text, status,
                   expert_id, runtime_type)
                values
                  ('turn_deleted_history', 'session_deleted_history',
                   'tenant_delete_history', ?, 'deleted history', 'completed', ?, 'codex')
                """,
                (user_id, expert_id),
            )
            connection.commit()

        deleted = client.delete(f"/api/v1/experts/{expert_id}", headers=headers)
        assert deleted.status_code == 204
        with open_database_connection(settings) as connection:
            session = connection.execute(
                "select expert_id from chat_sessions where id = 'session_deleted_history'"
            ).fetchone()
            turn = connection.execute(
                "select expert_id from chat_turns where id = 'turn_deleted_history'"
            ).fetchone()
        assert session["expert_id"] is None
        assert turn["expert_id"] is None


def test_mcp_connector_directory_returns_sanitized_503(tmp_path: Path) -> None:
    database_path = tmp_path / "mcp_connectors_unavailable.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    class UnavailableGateway:
        async def list_mcp_services(self) -> list[GatewayMcpService]:
            raise ApiError(
                502,
                "GATEWAY_ADMIN_ERROR",
                "upstream http://127.0.0.1:8765 contains private details",
                {"auth": "must-not-leak"},
            )

    test_app.dependency_overrides[get_gateway_admin_client] = lambda: UnavailableGateway()
    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        response = client.get("/api/v1/mcp-connectors", headers=headers)
        assert response.status_code == 503
        assert response.json() == {
            "code": "MCP_CONNECTORS_UNAVAILABLE",
            "message": "MCP Connector directory is unavailable",
        }
        assert "127.0.0.1" not in response.text
        assert "must-not-leak" not in response.text


def test_expert_stats_summary_counts_statuses(tmp_path: Path) -> None:
    database_path = tmp_path / "expert_stats.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_stats', 'Stats', 'Stats experts')
                """
            )
            for expert_id, status in [
                ("expert_published_1", "published"),
                ("expert_published_2", "published"),
                ("expert_draft", "draft"),
                ("expert_unlisted", "unlisted"),
            ]:
                connection.execute(
                    """
                    insert into experts (id, category_id, name, ability_intro, status)
                    values (?, 'expert_cat_stats', ?, 'Stats helper.', ?)
                    """,
                    (expert_id, expert_id, status),
                )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        response = client.get("/api/v1/experts/stats/summary", headers=admin_headers)
        assert response.status_code == 200
        assert response.json() == {
            "total": 5,
            "published": 2,
            "draft": 1,
            "unlisted": 2,
        }


def test_expert_search_by_name_category_and_status(tmp_path: Path) -> None:
    database_path = tmp_path / "expert_search.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_ops', 'Operations', null)
                """
            )
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_ads', 'Advertising', null)
                """
            )
            for expert_id, category_id, name, status in [
                ("expert_listing", "expert_cat_ops", "Listing Expert", "published"),
                ("expert_store", "expert_cat_ops", "Store Operations Expert", "draft"),
                ("expert_ads", "expert_cat_ads", "Advertising Expert", "unlisted"),
            ]:
                connection.execute(
                    """
                    insert into experts (id, category_id, name, ability_intro, status)
                    values (?, ?, ?, 'Search helper.', ?)
                    """,
                    (expert_id, category_id, name, status),
                )
            connection.commit()

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}

        by_name = client.get(
            "/api/v1/experts",
            headers=admin_headers,
            params={"name": "listing"},
        )
        assert by_name.status_code == 200
        assert [item["id"] for item in by_name.json()["items"]] == ["expert_listing"]

        by_category = client.get(
            "/api/v1/experts",
            headers=admin_headers,
            params={"categoryId": "expert_cat_ops"},
        )
        assert by_category.status_code == 200
        assert {item["id"] for item in by_category.json()["items"]} == {
            "expert_listing",
            "expert_store",
        }

        by_status = client.get(
            "/api/v1/experts",
            headers=admin_headers,
            params={"status": "unlisted"},
        )
        assert by_status.status_code == 200
        assert {item["id"] for item in by_status.json()["items"]} == {
            "1825107e997dfde2",
            "expert_ads",
        }

        # Filters compose on the single list endpoint.
        combined = client.get(
            "/api/v1/experts",
            headers=admin_headers,
            params={"categoryId": "expert_cat_ops", "status": "published"},
        )
        assert combined.status_code == 200
        assert [item["id"] for item in combined.json()["items"]] == ["expert_listing"]


def test_plan_phase1_admin_market_and_current_subscription(tmp_path: Path) -> None:
    database_path = tmp_path / "plans.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        _seed_platform_user(
            settings,
            "operator_user",
            "operator@example.com",
            "Operator User",
            "operator-secret",
            "operator",
        )

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}
        operator_login = client.post(
            "/api/v1/auth/login",
            json={"email": "operator@example.com", "password": "operator-secret"},
        )
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['accessToken']}"}

        seeded = client.get("/api/v1/plans", headers=admin_headers)
        assert seeded.status_code == 200, seeded.text
        seeded_codes = [item["code"] for item in seeded.json()["items"]]
        assert seeded_codes == ["free", "pro", "max", "business"]
        by_seed_code = {item["code"]: item for item in seeded.json()["items"]}
        free_plan = by_seed_code["free"]
        assert free_plan["id"] == "plan_free"
        assert free_plan["name"] == "Free"
        assert free_plan["entitlements"]["monthlyCreditLimit"] == 2000
        assert free_plan["entitlements"]["allExperts"] is False
        assert free_plan["expertIds"] == ["1825107e997dfde2"]
        assert by_seed_code["pro"]["entitlements"]["monthlyCreditLimit"] == 20000
        assert by_seed_code["pro"]["expertIds"] == ["1825107e997dfde2"]
        assert by_seed_code["max"]["entitlements"]["allExperts"] is True
        assert by_seed_code["business"]["entitlements"]["seatLimit"] == 5

        operator_create = client.post(
            "/api/v1/plans",
            headers=operator_headers,
            json={
                "code": "operator-plan",
                "name": "Operator Plan",
                "level": 99,
                "description": "Forbidden",
            },
        )
        assert operator_create.status_code == 403

        missing_type = client.post(
            "/api/v1/plans",
            headers=admin_headers,
            json={
                "name": "Missing Type",
                "level": 6,
                "description": "Missing type label",
            },
        )
        assert missing_type.status_code == 400
        assert missing_type.json()["code"] == "PLAN_TYPE_LABEL_REQUIRED"

        unsupported_type = client.post(
            "/api/v1/plans",
            headers=admin_headers,
            json={
                "name": "Unsupported Type",
                "typeLabel": "未知类型",
                "level": 7,
                "description": "Unsupported type label",
            },
        )
        assert unsupported_type.status_code == 400
        assert unsupported_type.json()["code"] == "PLAN_TYPE_LABEL_UNSUPPORTED"

        invalid_level = client.post(
            "/api/v1/plans",
            headers=admin_headers,
            json={
                "name": "Invalid Level",
                "typeLabel": "个人付费",
                "level": 100,
                "description": "Out of range",
            },
        )
        assert invalid_level.status_code == 422

        invalid_sort = client.post(
            "/api/v1/plans",
            headers=admin_headers,
            json={
                "name": "Invalid Sort",
                "typeLabel": "个人付费",
                "level": 8,
                "description": "Out of range",
                "sortOrder": 10000,
            },
        )
        assert invalid_sort.status_code == 422

        created = client.post(
            "/api/v1/plans",
            headers=admin_headers,
            json={
                "code": "team-custom",
                "name": "Team",
                "level": 5,
                "description": "Team plan",
                "typeLabel": "团队",
                "subtitle": "团队协作",
                "badgeLabel": "团队版",
                "highlightItems": ["多人协作", "组织管理"],
                "upgradeRules": {
                    "fromPlanIds": ["plan_free"],
                    "toPlanIds": [],
                    "rules": ["联系销售"],
                    "selfServiceEnabled": False,
                },
                "isRecommended": True,
                "sortOrder": 50,
            },
        )
        assert created.status_code == 201, created.text
        plan = created.json()
        assert plan["code"] == "team-custom"
        assert plan["typeLabel"] == "团队"
        assert plan["subtitle"] == "团队协作"
        assert plan["badgeLabel"] == "团队版"
        assert plan["highlightItems"] == ["多人协作", "组织管理"]
        assert plan["upgradeRules"]["rules"] == ["联系销售"]
        assert plan["isRecommended"] is True

        changed_type = client.patch(
            f"/api/v1/plans/{plan['id']}",
            headers=admin_headers,
            json={"typeLabel": "企业定制"},
        )
        assert changed_type.status_code == 200, changed_type.text
        plan = changed_type.json()
        assert plan["code"] == "enterprise"
        assert plan["typeLabel"] == "企业定制"

        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenants (id, type, name, slug, status)
                values
                  ('plan_sub_tenant_1', 'personal', 'Plan Sub Tenant 1', 'plan-sub-tenant-1', 'active'),
                  ('plan_sub_tenant_2', 'personal', 'Plan Sub Tenant 2', 'plan-sub-tenant-2', 'active'),
                  ('plan_sub_tenant_cancelled', 'personal', 'Plan Sub Cancelled', 'plan-sub-cancelled', 'active')
                """
            )
            connection.execute(
                """
                insert into subscriptions (
                  id,
                  tenant_id,
                  plan_id,
                  status,
                  billing_period,
                  current_period_start,
                  current_period_end,
                  cancel_at_period_end
                )
                values
                  (
                    'plan_sub_active_1',
                    'plan_sub_tenant_1',
                    'plan_free',
                    'active',
                    'free',
                    CURRENT_TIMESTAMP,
                    datetime('now', '+30 days'),
                    false
                  ),
                  (
                    'plan_sub_trialing_2',
                    'plan_sub_tenant_2',
                    'plan_free',
                    'trialing',
                    'free',
                    CURRENT_TIMESTAMP,
                    datetime('now', '+14 days'),
                    false
                  ),
                  (
                    'plan_sub_cancelled_ignored',
                    'plan_sub_tenant_cancelled',
                    'plan_free',
                    'cancelled',
                    'free',
                    CURRENT_TIMESTAMP,
                    datetime('now', '+30 days'),
                    false
                  )
                """
            )
            connection.commit()

        after_recommend = client.get("/api/v1/plans", headers=admin_headers)
        by_code = {item["code"]: item for item in after_recommend.json()["items"]}
        assert by_code["free"]["isRecommended"] is False
        assert by_code["free"]["subscriptionCount"] == 2
        assert by_code["enterprise"]["isRecommended"] is True

        free_detail = client.get("/api/v1/plans/plan_free", headers=admin_headers)
        assert free_detail.status_code == 200
        assert free_detail.json()["subscriptionCount"] == 2

        priced = client.put(
            f"/api/v1/plans/{plan['id']}/prices",
            headers=admin_headers,
            json={
                "items": [
                    {
                        "billingPeriod": "monthly",
                        "currency": "CNY",
                        "amountCents": 49900,
                        "isEnabled": True,
                    }
                ]
            },
        )
        assert priced.status_code == 200, priced.text
        assert priced.json()["prices"][0]["amountCents"] == 49900

        entitled = client.put(
            f"/api/v1/plans/{plan['id']}/entitlements",
            headers=admin_headers,
            json={
                "monthlyCreditLimit": 2000,
                "allExperts": True,
                "seatLimit": 3,
                "singleTurnTokenLimit": None,
                "modelTiers": ["core", "enhanced"],
                "features": {"teamManagement": True},
            },
        )
        assert entitled.status_code == 200, entitled.text
        assert entitled.json()["entitlements"]["seatLimit"] == 3

        hidden = client.patch(
            f"/api/v1/plans/{plan['id']}",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert hidden.status_code == 200
        market = client.get("/api/v1/plan-market/plans", headers=operator_headers)
        assert market.status_code == 200
        assert plan["code"] not in [item["code"] for item in market.json()["items"]]

        tenant_register = client.post(
            "/api/v1/users/register",
            json={"email": "tenant@example.com", "password": "secret123", "name": "Tenant User"},
        )
        assert tenant_register.status_code == 201
        tenant_headers = {"Authorization": f"Bearer {tenant_register.json()['accessToken']}"}

        with open_database_connection(settings) as connection:
            registered_subscription = connection.execute(
                """
                select s.plan_id, s.status, s.billing_period
                from users u
                inner join tenant_members tm on tm.user_id = u.id
                inner join subscriptions s on s.tenant_id = tm.tenant_id
                where u.email = 'tenant@example.com'
                order by s.created_at desc
                limit 1
                """
            ).fetchone()
        assert registered_subscription is not None
        assert (
            registered_subscription["plan_id"],
            registered_subscription["status"],
            registered_subscription["billing_period"],
        ) == ("plan_free", "active", "free")

        current = client.get("/api/v1/plan-market/current-subscription", headers=tenant_headers)
        assert current.status_code == 200, current.text
        body = current.json()
        assert body["subscription"]["planId"] == free_plan["id"]
        assert body["plan"]["code"] == "free"
        assert body["plan"]["name"] == "Free"
        assert body["plan"]["entitlements"]["monthlyCreditLimit"] == 2000
        assert body["plan"]["expertIds"] == ["1825107e997dfde2"]

        client.put(
            f"/api/v1/plans/{free_plan['id']}/entitlements",
            headers=admin_headers,
            json={
                "monthlyCreditLimit": 999,
                "allExperts": False,
                "seatLimit": 1,
                "singleTurnTokenLimit": None,
                "modelTiers": ["core"],
                "features": {},
            },
        )
        changed_current = client.get(
            "/api/v1/plan-market/current-subscription", headers=tenant_headers
        )
        assert changed_current.status_code == 200
        assert changed_current.json()["plan"]["entitlements"]["monthlyCreditLimit"] == 999

        delete_free = client.delete(f"/api/v1/plans/{free_plan['id']}", headers=admin_headers)
        assert delete_free.status_code == 409


def test_plan_market_self_service_upgrade_updates_monthly_credits_once(tmp_path: Path) -> None:
    database_path = tmp_path / "plan-market-upgrade.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        registered = client.post(
            "/api/v1/users/register",
            json={
                "email": "subscriber@example.com",
                "password": "subscriber-secret",
                "name": "Subscriber",
            },
        )
        assert registered.status_code == 201, registered.text
        authorization = {"Authorization": f"Bearer {registered.json()['accessToken']}"}
        with open_database_connection(settings) as connection:
            tenant_id = str(
                connection.execute(
                    "select tenant_id from tenant_members where user_id = ?",
                    (registered.json()["user"]["id"],),
                ).fetchone()["tenant_id"]
            )
        headers = {**authorization, "x-tenant-id": tenant_id}

        missing_tenant = client.patch(
            "/api/v1/plan-market/current-subscription",
            headers=authorization,
            json={"planId": "plan_pro"},
        )
        assert (missing_tenant.status_code, missing_tenant.json()["code"]) == (
            401,
            "AUTH_UNAUTHORIZED",
        )
        mismatched_tenant = client.patch(
            "/api/v1/plan-market/current-subscription",
            headers={**authorization, "x-tenant-id": "another-tenant"},
            json={"planId": "plan_pro"},
        )
        assert (mismatched_tenant.status_code, mismatched_tenant.json()["code"]) == (
            403,
            "AUTH_FORBIDDEN",
        )

        upgraded = client.patch(
            "/api/v1/plan-market/current-subscription",
            headers=headers,
            json={"planId": "plan_pro"},
        )
        assert upgraded.status_code == 200, upgraded.text
        assert upgraded.json()["plan"]["code"] == "pro"
        assert upgraded.json()["subscription"]["billingPeriod"] == "monthly"

        credits = client.get("/api/v1/credits/current", headers=headers)
        assert credits.status_code == 200, credits.text
        assert credits.json()["monthlyCreditLimit"] == 20_000
        assert credits.json()["grantedCredits"] == 20_000
        subscription_id = upgraded.json()["subscription"]["id"]

        repeated = client.patch(
            "/api/v1/plan-market/current-subscription",
            headers=headers,
            json={"planId": "plan_pro"},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["subscription"]["id"] == subscription_id

        downgrade = client.patch(
            "/api/v1/plan-market/current-subscription",
            headers=headers,
            json={"planId": "plan_free"},
        )
        assert (downgrade.status_code, downgrade.json()["code"]) == (
            409,
            "PLAN_NOT_UPGRADE",
        )

        with open_database_connection(settings) as connection:
            active_subscriptions = connection.execute(
                "select count(*) as count from subscriptions "
                "where tenant_id = ? and status = 'active'",
                (tenant_id,),
            ).fetchone()["count"]
            subscription_audits = connection.execute(
                "select count(*) as count from audit_events "
                "where tenant_id = ? and action = 'tenant.subscription_change'",
                (tenant_id,),
            ).fetchone()["count"]
        assert active_subscriptions == 1
        assert subscription_audits == 1


def test_expert_market_requires_sign_in_and_only_lists_published_experts(tmp_path: Path) -> None:
    database_path = tmp_path / "expert_market.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_platform_user(
            settings, "market_user", "market@example.com", "Market User", "market-secret", "operator"
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('market_user_member', 'tenant_default', 'market_user', 'member')
                """
            )
            connection.execute(
                """
                insert into subscriptions (
                  id, tenant_id, plan_id, status, billing_period,
                  current_period_start, current_period_end, cancel_at_period_end
                )
                values (
                  'sub_market_free', 'tenant_default', 'plan_free', 'active', 'free',
                  CURRENT_TIMESTAMP, null, false
                )
                """
            )
            connection.commit()

        # Anonymous callers are rejected -- the marketplace is sign-in gated, not public.
        assert client.get("/api/v1/expert-market/categories").status_code == 401
        assert client.get("/api/v1/expert-market/experts").status_code == 401
        assert client.get("/api/v1/expert-market/experts/expert_listing").status_code == 401

        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "market@example.com",
                "password": "market-secret",
                "tenantId": "tenant_default",
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_ops', 'Operations', 'Operations experts')
                """
            )
            connection.execute(
                """
                insert into expert_categories (id, name, description)
                values ('expert_cat_ads', 'Advertising', 'Advertising experts')
                """
            )
            for expert_id, category_id, name, status, labels, created_at in [
                (
                    "expert_listing",
                    "expert_cat_ops",
                    "Listing Expert",
                    "published",
                    '["hot"]',
                    "2026-06-01T00:00:00+00:00",
                ),
                (
                    "expert_newer",
                    "expert_cat_ops",
                    "Newer Expert",
                    "published",
                    "[]",
                    "2026-06-02T00:00:00+00:00",
                ),
                (
                    "expert_store",
                    "expert_cat_ops",
                    "Store Expert",
                    "draft",
                    '["hot"]',
                    "2026-06-03T00:00:00+00:00",
                ),
                (
                    "expert_ads",
                    "expert_cat_ads",
                    "Ads Expert",
                    "unlisted",
                    '["hot"]',
                    "2026-06-04T00:00:00+00:00",
                ),
            ]:
                connection.execute(
                    """
                    insert into experts (
                      id, category_id, name, ability_intro, tags, market_labels, status,
                      guide_questions, summon_button_text, created_at
                    )
                    values (?, ?, ?, 'Public helper.', '["tag"]', ?, ?, '["q1"]', 'Ask', ?)
                    """,
                    (expert_id, category_id, name, labels, status, created_at),
                )
            # The system default is a Runtime defaults template, never a selectable market Expert.
            connection.execute(
                "update experts set status = 'published' where id = ?",
                ("1825107e997dfde2",),
            )
            connection.commit()

        categories = client.get("/api/v1/expert-market/categories", headers=headers)
        assert categories.status_code == 200
        assert categories.json()["items"] == [
            {
                "id": "expert_cat_ops",
                "name": "Operations",
                "description": "Operations experts",
            }
        ]

        experts = client.get("/api/v1/expert-market/experts", headers=headers)
        assert experts.status_code == 200
        market_items = experts.json()["items"]
        assert {item["id"] for item in market_items} == {
            "expert_listing",
            "expert_newer",
        }
        assert next(item for item in market_items if item["id"] == "expert_listing")[
            "marketLabels"
        ] == ["hot"]
        assert {item["id"]: item["isAccessible"] for item in market_items} == {
            "expert_listing": False,
            "expert_newer": False,
        }
        assert next(item for item in market_items if item["id"] == "expert_newer")[
            "marketLabels"
        ] == []
        assert [
            item["id"]
            for item in market_items
            if item["id"] in {"expert_listing", "expert_newer"}
        ] == ["expert_newer", "expert_listing"]

        by_category = client.get(
            "/api/v1/expert-market/experts",
            params={"categoryId": "expert_cat_ads"},
            headers=headers,
        )
        assert by_category.status_code == 200
        assert by_category.json()["items"] == []

        detail = client.get("/api/v1/expert-market/experts/expert_listing", headers=headers)
        assert detail.status_code == 200
        assert detail.json() == {
            "id": "expert_listing",
            "name": "Listing Expert",
            "categoryId": "expert_cat_ops",
            "categoryName": "Operations",
            "abilityIntro": "Public helper.",
            "tags": ["tag"],
            "marketLabels": ["hot"],
            "guideQuestions": ["q1"],
            "summonButtonText": "Ask",
            "isAccessible": False,
        }

        hidden = client.get("/api/v1/expert-market/experts/expert_store", headers=headers)
        assert hidden.status_code == 404
        system_default = client.get(
            "/api/v1/expert-market/experts/1825107e997dfde2",
            headers=headers,
        )
        assert system_default.status_code == 404
        default_session = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"expertId": "1825107e997dfde2"},
        )
        assert default_session.status_code == 409
        assert default_session.json()["code"] == "EXPERT_NOT_SELECTABLE"


def test_skills_upload_list_get_file_update_and_delete(tmp_path: Path) -> None:
    database_path = tmp_path / "skills.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
    )
    test_app = create_app(settings)

    with TestClient(test_app) as client:
        _seed_platform_user(
            settings,
            "expert_user",
            "expert@example.com",
            "Expert User",
            "expert-secret",
            "expert",
        )
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "expert@example.com", "password": "expert-secret"},
        )
        assert login_response.status_code == 200
        headers = {
            "Authorization": f"Bearer {login_response.json()['accessToken']}",
        }

        upload_response = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        assert upload_response.status_code == 201
        uploaded = upload_response.json()
        assert uploaded["slug"] == "amazon-review-analyzer"
        assert uploaded["allowedTools"] == ["Bash(python scripts/analyze_reviews.py:*)"]
        assert uploaded["filePaths"] == ["SKILL.md", "scripts/analyze_reviews.py"]
        assert uploaded["tags"] == ["amazon", "reviews"]

        list_response = client.get("/api/v1/skills?tags=amazon&search=review", headers=headers)
        assert list_response.status_code == 200
        list_body = list_response.json()
        assert [item["slug"] for item in list_body["items"]] == ["amazon-review-analyzer"]
        assert list_body["total"] == 1
        assert list_body["hasMore"] is False

        file_response = client.get(
            "/api/v1/skills/amazon-review-analyzer/file?path=SKILL.md",
            headers=headers,
        )
        assert file_response.status_code == 200
        assert "Analyze Amazon review trends" in file_response.text

        update_response = client.put(
            "/api/v1/skills/amazon-review-analyzer",
            headers=headers,
            json={"description": "Updated description", "tags": ["amazon", "feedback"]},
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["description"] == "Updated description"
        assert updated["tags"] == ["amazon", "feedback"]

        delete_response = client.delete(
            "/api/v1/skills/amazon-review-analyzer?delete_files=true",
            headers=headers,
        )
        assert delete_response.status_code == 204

        missing_response = client.get("/api/v1/skills/amazon-review-analyzer", headers=headers)
        assert missing_response.status_code == 404
        assert not (tmp_path / "objects" / "skills" / "amazon-review-analyzer").exists()


def _skill_test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'skills.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
    )


def _login_skill_expert(client: TestClient, settings: Settings) -> dict[str, str]:
    _seed_platform_user(
        settings, "expert_user", "expert@example.com", "Expert User", "expert-secret", "expert"
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "expert@example.com", "password": "expert-secret"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def _skill_md_zip(skill_md: str, *, root: str = "pkg") -> BytesIO:
    content = BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr(f"{root}/SKILL.md", skill_md)
    content.seek(0)
    return content


def _binary_skill_zip() -> BytesIO:
    content = BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr(
            "pkg/SKILL.md",
            "---\nname: binary-skill\ndescription: Contains a binary asset.\n---\n",
        )
        archive.writestr("pkg/assets/blob.bin", b"\xff\xfe\x00")
    content.seek(0)
    return content


def test_skills_duplicate_slug_conflict(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        first = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        assert second.status_code == 409
        assert second.json()["code"] == "SKILL_EXISTS"


def test_skills_upload_slug_accepts_multipart_form_field(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        response = client.post(
            "/api/v1/skills",
            headers=headers,
            data={"slug": "custom-skill"},
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        assert response.status_code == 201
        assert response.json()["slug"] == "custom-skill"


def test_skills_upload_storage_failure_rolls_back_metadata(tmp_path: Path) -> None:
    class FailingSkillStorage:
        deleted = False

        def uri_for(self, slug: str) -> str:
            return f"/skills/{slug}"

        def put_files(self, slug: str, files: dict[str, bytes]) -> str:
            raise RuntimeError("storage unavailable")

        def get_file(self, slug: str, path: str) -> bytes:
            raise AssertionError("not used")

        def delete_skill(self, slug: str) -> None:
            self.deleted = True

    settings = _skill_test_settings(tmp_path)
    storage = FailingSkillStorage()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_skill_storage] = lambda: storage
    with TestClient(test_app, raise_server_exceptions=False) as client:
        headers = _login_skill_expert(client, settings)
        response = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        assert response.status_code == 500

    with open_database_connection(settings) as connection:
        row = connection.execute(
            "select count(*) as count from skills where slug = ?",
            ("amazon-review-analyzer",),
        ).fetchone()
    assert row["count"] == 0
    assert storage.deleted is True


def test_skills_list_pagination(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        for slug in ("skill-a", "skill-b"):
            response = client.post(
                "/api/v1/skills",
                headers=headers,
                data={"slug": slug},
                files={"file": ("skill.zip", _skill_zip(), "application/zip")},
            )
            assert response.status_code == 201

        page = client.get("/api/v1/skills?limit=1", headers=headers).json()
        assert page["total"] == 2
        assert len(page["items"]) == 1
        assert page["hasMore"] is True

        last = client.get("/api/v1/skills?limit=1&offset=1", headers=headers).json()
        assert last["total"] == 2
        assert last["hasMore"] is False


def test_skills_file_content_type_by_extension(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )
        response = client.get(
            "/api/v1/skills/amazon-review-analyzer/file?path=scripts/analyze_reviews.py",
            headers=headers,
        )
        assert response.status_code == 200
        content_type = response.headers["content-type"]
        assert "markdown" not in content_type


def test_skills_file_returns_binary_content(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        upload = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _binary_skill_zip(), "application/zip")},
        )
        assert upload.status_code == 201

        response = client.get(
            "/api/v1/skills/binary-skill/file?path=assets/blob.bin",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.content == b"\xff\xfe\x00"


def test_skills_zip_too_many_files(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr(
                "pkg/SKILL.md",
                "---\nname: big-skill\ndescription: Too many files.\n---\n",
            )
            for index in range(501):
                archive.writestr(f"pkg/file_{index}.txt", "x")
        buffer.seek(0)
        response = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", buffer, "application/zip")},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "SKILL_ZIP_TOO_MANY_FILES"


def test_skills_frontmatter_unclosed_block(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        skill_md = "---\nname: broken\ndescription: No closing fence.\n# body without close\n"
        response = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_md_zip(skill_md), "application/zip")},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "SKILL_INVALID_FRONTMATTER"


def test_skills_frontmatter_inline_lists_and_dashes(tmp_path: Path) -> None:
    settings = _skill_test_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = _login_skill_expert(client, settings)
        skill_md = (
            "---\n"
            "name: dash-skill\n"
            "description: Values with dashes and inline lists.\n"
            "tags: [alpha-one, beta]\n"
            "allowed-tools:\n"
            "  - Bash(some-tool --flag)\n"
            "---\n# Dash Skill\n"
        )
        response = client.post(
            "/api/v1/skills",
            headers=headers,
            files={"file": ("skill.zip", _skill_md_zip(skill_md), "application/zip")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["tags"] == ["alpha-one", "beta"]
        assert body["allowedTools"] == ["Bash(some-tool --flag)"]


def _chat_search_test_context(tmp_path: Path, database_name: str) -> tuple[Settings, FastAPI]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / database_name}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    return settings, create_app(settings)


def _login_chat_search_user(client: TestClient, settings: Settings) -> dict[str, str]:
    _seed_tenant(settings)
    _seed_tenant_user(
        settings,
        "search_user",
        "search-user@example.com",
        "Search User",
        "search-secret",
        "member",
    )
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "search-user@example.com",
            "password": "search-secret",
            "tenantId": "tenant_default",
        },
    )
    assert login.status_code == 200, login.text
    return {
        "Authorization": f"Bearer {login.json()['accessToken']}",
        "x-tenant-id": "tenant_default",
    }


def _seed_chat_search_records(
    settings: Settings,
    sessions: list[tuple],
    turns: list[tuple],
) -> None:
    with open_database_connection(settings) as connection:
        connection.executemany(
            """
            insert into chat_sessions (
              id, tenant_id, user_id, title, status, created_at, updated_at, deleted_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sessions,
        )
        connection.executemany(
            """
            insert into chat_turns (
              id, session_id, tenant_id, user_id, request_text, response_text,
              reasoning_text, error_message, status, is_internal, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
            """,
            turns,
        )
        connection.commit()


def test_chat_search_scopes_filters_isolation_and_match_selection(tmp_path: Path) -> None:
    settings, test_app = _chat_search_test_context(tmp_path, "chat_search.sqlite3")

    with TestClient(test_app) as client:
        headers = _login_chat_search_user(client, settings)
        _seed_tenant_user(
            settings,
            "other_default_user",
            "other-default-search@example.com",
            "Other Default Search User",
            "other-secret",
            "member",
        )
        _seed_user(
            settings,
            "other_tenant_user",
            "other-tenant-search@example.com",
            "Other Tenant Search User",
            "other-secret",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenants (id, type, name, slug, status)
                values ('tenant_other', 'team', 'Other Tenant', 'other-search', 'active')
                """
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('other_search_member', 'tenant_other', 'other_tenant_user', 'member')
                """
            )
            connection.commit()

        sessions = [
            (
                "session_first_after",
                "tenant_default",
                "search_user",
                "Second question",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-10T00:00:00+00:00",
                None,
            ),
            (
                "session_question",
                "tenant_default",
                "search_user",
                "Question match",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-09T00:00:00+00:00",
                None,
            ),
            (
                "session_answer",
                "tenant_default",
                "search_user",
                None,
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-08T00:00:00+00:00",
                None,
            ),
            (
                "session_title_only",
                "tenant_default",
                "search_user",
                "COMMON_SCOPE title only",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-07T00:00:00+00:00",
                None,
            ),
            (
                "session_archived",
                "tenant_default",
                "search_user",
                "Archived",
                "archived",
                "2026-01-01T00:00:00+00:00",
                "2026-01-06T00:00:00+00:00",
                None,
            ),
            (
                "session_deleted",
                "tenant_default",
                "search_user",
                "Deleted",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-05T00:00:00+00:00",
                "2026-01-05T01:00:00+00:00",
            ),
            (
                "session_internal",
                "tenant_default",
                "search_user",
                "Internal",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-04T00:00:00+00:00",
                None,
            ),
            (
                "session_metadata",
                "tenant_default",
                "search_user",
                "Metadata",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-03T00:00:00+00:00",
                None,
            ),
            (
                "session_other_user",
                "tenant_default",
                "other_default_user",
                "Other user",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
                None,
            ),
            (
                "session_other_tenant",
                "tenant_other",
                "other_tenant_user",
                "Other tenant",
                "active",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                None,
            ),
            (
                "session_latest",
                "tenant_default",
                "search_user",
                "Latest match",
                "active",
                "2026-02-01T00:00:00+00:00",
                "2026-02-02T00:00:00+00:00",
                None,
            ),
            (
                "session_priority",
                "tenant_default",
                "search_user",
                "Question priority",
                "active",
                "2026-02-01T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
                None,
            ),
        ]
        turns = [
            (
                "turn_first",
                "session_first_after",
                "tenant_default",
                "search_user",
                "第一条普通问题",
                "普通回答",
                None,
                None,
                False,
                "2026-01-01T00:00:00+00:00",
            ),
            (
                "turn_second",
                "session_first_after",
                "tenant_default",
                "search_user",
                "第二条问题包含针叶关键字",
                "第二条回答",
                None,
                None,
                False,
                "2026-01-02T00:00:00+00:00",
            ),
            (
                "turn_question",
                "session_question",
                "tenant_default",
                "search_user",
                "A common_scope marker in the question",
                "No marker here",
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_answer",
                "session_answer",
                "tenant_default",
                "search_user",
                "Ask for a result",
                "The assistant returns COMMON_SCOPE in uppercase",
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_title_only",
                "session_title_only",
                "tenant_default",
                "search_user",
                "No searchable marker",
                "Still no searchable marker",
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_archived",
                "session_archived",
                "tenant_default",
                "search_user",
                "common_scope archived",
                None,
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_deleted",
                "session_deleted",
                "tenant_default",
                "search_user",
                "common_scope deleted",
                None,
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_internal",
                "session_internal",
                "tenant_default",
                "search_user",
                "common_scope internal",
                "common_scope internal answer",
                None,
                None,
                True,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_metadata",
                "session_metadata",
                "tenant_default",
                "search_user",
                "Ordinary request",
                None,
                "common_scope reasoning only",
                "common_scope error only",
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_other_user",
                "session_other_user",
                "tenant_default",
                "other_default_user",
                "common_scope other user",
                None,
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_other_tenant",
                "session_other_tenant",
                "tenant_other",
                "other_tenant_user",
                "common_scope other tenant",
                None,
                None,
                None,
                False,
                "2026-01-03T00:00:00+00:00",
            ),
            (
                "turn_latest_old",
                "session_latest",
                "tenant_default",
                "search_user",
                "latest-choice-marker in an older question",
                None,
                None,
                None,
                False,
                "2026-02-01T00:00:00+00:00",
            ),
            (
                "turn_latest_new",
                "session_latest",
                "tenant_default",
                "search_user",
                "New question without it",
                "latest-choice-marker in the newer answer",
                None,
                None,
                False,
                "2026-02-02T00:00:00+00:00",
            ),
            (
                "turn_priority",
                "session_priority",
                "tenant_default",
                "search_user",
                "same-turn-choice in question",
                "same-turn-choice in answer",
                None,
                None,
                False,
                "2026-02-01T00:00:00+00:00",
            ),
        ]
        _seed_chat_search_records(settings, sessions, turns)

        all_scope = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "common_scope"},
        )
        assert all_scope.status_code == 200, all_scope.text
        assert all_scope.json() == {
            "items": [
                {
                    "sessionId": "session_question",
                    "title": "Question match",
                    "matchedTurnId": "turn_question",
                    "matchedType": "question",
                    "snippet": "A common_scope marker in the question",
                },
                {
                    "sessionId": "session_answer",
                    "title": None,
                    "matchedTurnId": "turn_answer",
                    "matchedType": "answer",
                    "snippet": "The assistant returns COMMON_SCOPE in uppercase",
                },
                {
                    "sessionId": "session_title_only",
                    "title": "COMMON_SCOPE title only",
                    "matchedTurnId": "turn_title_only",
                    "matchedType": "title",
                    "snippet": "COMMON_SCOPE title only",
                },
            ],
            "total": 3,
            "limit": 20,
            "offset": 0,
        }

        question_scope = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "common_scope", "scope": "question"},
        ).json()
        assert [item["sessionId"] for item in question_scope["items"]] == [
            "session_question"
        ]

        answer_scope = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "common_scope", "scope": "answer"},
        ).json()
        assert [item["sessionId"] for item in answer_scope["items"]] == ["session_answer"]

        second_question = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "针叶"},
        ).json()
        assert second_question["total"] == 1
        assert second_question["items"][0]["matchedTurnId"] == "turn_second"

        latest = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "latest-choice-marker"},
        ).json()
        assert latest["total"] == 1
        assert latest["items"][0]["matchedTurnId"] == "turn_latest_new"
        assert latest["items"][0]["matchedType"] == "answer"

        priority = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "same-turn-choice"},
        ).json()
        assert priority["total"] == 1
        assert priority["items"][0]["matchedTurnId"] == "turn_priority"
        assert priority["items"][0]["matchedType"] == "question"


@pytest.mark.parametrize("keyword", ["%token", "_token", "\\token"])
def test_chat_search_treats_like_special_characters_as_text(
    tmp_path: Path,
    keyword: str,
) -> None:
    settings, test_app = _chat_search_test_context(
        tmp_path,
        f"chat_search_special_{ord(keyword[0])}.sqlite3",
    )
    with TestClient(test_app) as client:
        headers = _login_chat_search_user(client, settings)
        _seed_chat_search_records(
            settings,
            [
                (
                    "session_special",
                    "tenant_default",
                    "search_user",
                    "Special text",
                    "active",
                    "2026-03-01T00:00:00+00:00",
                    "2026-03-02T00:00:00+00:00",
                    None,
                ),
                (
                    "session_decoy",
                    "tenant_default",
                    "search_user",
                    "Decoy",
                    "active",
                    "2026-03-01T00:00:00+00:00",
                    "2026-03-01T00:00:00+00:00",
                    None,
                ),
            ],
            [
                (
                    "turn_special",
                    "session_special",
                    "tenant_default",
                    "search_user",
                    "Literal %token and _token and \\token are present",
                    None,
                    None,
                    None,
                    False,
                    "2026-03-02T00:00:00+00:00",
                ),
                (
                    "turn_decoy",
                    "session_decoy",
                    "tenant_default",
                    "search_user",
                    "Literal xtoken and token without those symbols",
                    None,
                    None,
                    None,
                    False,
                    "2026-03-01T00:00:00+00:00",
                ),
            ],
        )

        response = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": keyword},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1
        assert [item["sessionId"] for item in response.json()["items"]] == [
            "session_special"
        ]

        empty = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "not-present"},
        )
        assert empty.json() == {
            "items": [],
            "total": 0,
            "limit": 20,
            "offset": 0,
        }


def test_chat_search_pagination_is_stable_and_snippet_is_bounded(tmp_path: Path) -> None:
    settings, test_app = _chat_search_test_context(tmp_path, "chat_search_page.sqlite3")
    with TestClient(test_app) as client:
        headers = _login_chat_search_user(client, settings)
        session_ids = ["session_a", "session_b", "session_2", "session_3"]
        updated_at = {
            "session_a": "2026-04-01T00:00:00+00:00",
            "session_b": "2026-04-01T00:00:00+00:00",
            "session_2": "2026-04-02T00:00:00+00:00",
            "session_3": "2026-04-03T00:00:00+00:00",
        }
        sessions = [
            (
                session_id,
                "tenant_default",
                "search_user",
                session_id,
                "active",
                "2026-04-01T00:00:00+00:00",
                updated_at[session_id],
                None,
            )
            for session_id in session_ids
        ]
        turns = [
            (
                f"turn_{session_id}",
                session_id,
                "tenant_default",
                "search_user",
                (
                    "x" * 300 + "Page-Key" + "y" * 300
                    if session_id == "session_3"
                    else f"{session_id} contains page-key"
                ),
                None,
                None,
                None,
                False,
                updated_at[session_id],
            )
            for session_id in session_ids
        ]
        _seed_chat_search_records(settings, sessions, turns)

        first_page = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "  page-key  ", "limit": 2, "offset": 0},
        )
        assert first_page.status_code == 200, first_page.text
        first_body = first_page.json()
        assert first_body["total"] == 4
        assert first_body["limit"] == 2
        assert first_body["offset"] == 0
        assert [item["sessionId"] for item in first_body["items"]] == [
            "session_3",
            "session_2",
        ]
        snippet = first_body["items"][0]["snippet"]
        assert "Page-Key" in snippet
        assert len(snippet) <= 160
        assert snippet.startswith("…")
        assert snippet.endswith("…")

        second_page = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "page-key", "limit": 2, "offset": 2},
        ).json()
        assert second_page["total"] == 4
        assert [item["sessionId"] for item in second_page["items"]] == [
            "session_b",
            "session_a",
        ]

        past_end = client.get(
            "/api/v1/chat/search",
            headers=headers,
            params={"keyword": "page-key", "limit": 2, "offset": 99},
        ).json()
        assert past_end == {"items": [], "total": 4, "limit": 2, "offset": 99}


def test_chat_search_parameter_validation_uses_documented_error_shapes(tmp_path: Path) -> None:
    settings, test_app = _chat_search_test_context(tmp_path, "chat_search_validation.sqlite3")
    with TestClient(test_app) as client:
        headers = _login_chat_search_user(client, settings)

        missing = client.get("/api/v1/chat/search", headers=headers)
        assert missing.status_code == 422
        assert "detail" in missing.json()

        for keyword in ("   ", "x" * 201):
            invalid_keyword = client.get(
                "/api/v1/chat/search",
                headers=headers,
                params={"keyword": keyword},
            )
            assert invalid_keyword.status_code == 400
            assert invalid_keyword.json() == {
                "code": "CHAT_SEARCH_KEYWORD_INVALID",
                "message": "keyword must contain 1 to 200 characters after trimming",
            }

        invalid_parameters = [
            {"keyword": "valid", "scope": "invalid"},
            {"keyword": "valid", "limit": 0},
            {"keyword": "valid", "limit": 101},
            {"keyword": "valid", "offset": -1},
        ]
        for params in invalid_parameters:
            response = client.get("/api/v1/chat/search", headers=headers, params=params)
            assert response.status_code == 422
            assert "detail" in response.json()


def test_chat_acp_backend_creates_locally_and_translates_turn(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        created = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"title": "ACP Test"},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        # The ACP backend mints the thread id locally; no upstream create call is made.
        assert session_id.startswith("thread_")

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )
        assert turn.status_code == 200
        # ACP session/delta/done events are translated to the public public contract.
        assert "event: turn_started" in turn.text
        assert "event: message_delta" in turn.text
        assert "event: turn_completed" in turn.text
        assert "event: session" not in turn.text

        first_call = fake_acp.turn_calls[0]
        assert first_call["thread_id"] == session_id
        assert first_call["session_id"] is None  # first turn has no id to resume
        assert first_call["cwd"] == fake_acp.prepare_user_cwd(
            "tenant_default", "tenant_user"
        )
        assert first_call["input"].startswith("hello\n\n[Internal personal Library authorization]")
        assert first_call.get("config_overrides") is None
        assert first_call.get("search_mode") == "off"
        assert first_call.get("route_prefix") == fake_acp.route_prefix

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        assert messages.json()["items"][0]["responseText"] == "ok"

        # A follow-up turn echoes back the agent-assigned ACP session id to resume the instance.
        client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "again"},
        )
        assert fake_acp.turn_calls[1]["session_id"] == "acp_sess_1"


def test_chat_acp_usage_is_persisted_and_aggregated_for_tenant(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_usage.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpUsageGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform-admin@example.com",
            "Platform Admin",
            "admin-secret",
            "admin",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into subscriptions (
                  id, tenant_id, plan_id, status, billing_period,
                  current_period_start, current_period_end, cancel_at_period_end
                )
                values (
                  'sub_tenant_default_usage',
                  'tenant_default',
                  'plan_free',
                  'active',
                  'free',
                  CURRENT_TIMESTAMP,
                  null,
                  false
                )
                """
            )
            connection.commit()
        tenant_login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        tenant_headers = {
            "Authorization": f"Bearer {tenant_login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }
        session_id = client.post(
            "/api/v1/chat/sessions",
            headers=tenant_headers,
            json={"title": "Usage Test"},
        ).json()["id"]

        first = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=tenant_headers,
            json={"question": "first"},
        )
        second = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=tenant_headers,
            json={"question": "second"},
        )
        third = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=tenant_headers,
            json={"question": "third after runtime reload"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 200

        with open_database_connection(settings) as connection:
            rows = connection.execute(
                """
                select token_usage_scope, token_usage_session_id,
                       token_usage_previous_snapshot, token_usage_snapshot, token_used
                from chat_turns
                order by created_at asc
                """
            ).fetchall()
        # usage.used is an absolute context snapshot. The second turn receives the pooled
        # instance's 120-token replay before its live 175 value. The third simulates a reloaded
        # instance and emits only its live 200 value. Both paths must persist only new growth.
        assert [row["token_usage_scope"] for row in rows] == ["no_search"] * 3
        assert [row["token_usage_session_id"] for row in rows] == ["acp_sess_usage"] * 3
        assert [row["token_usage_previous_snapshot"] for row in rows] == [0, 120, 175]
        assert [row["token_usage_snapshot"] for row in rows] == [120, 175, 200]
        assert [row["token_used"] for row in rows] == [120, 55, 25]
        with open_database_connection(settings) as connection:
            usage_records = connection.execute(
                """
                select calculator_version, usage_source, previous_usage_size, current_usage_size,
                       cached_tokens, uncached_tokens, cached_input_weight_scaled,
                       calculation_scale, effective_tokens_scaled, calculated_credits
                from credit_usage_records
                where user_id = 'tenant_user'
                order by created_at asc
                """
            ).fetchall()
        assert [row["calculator_version"] for row in usage_records] == [
            "estimated-cache-v2"
        ] * 3
        assert [row["usage_source"] for row in usage_records] == [
            "acp_context_snapshot_split"
        ] * 3
        assert [row["previous_usage_size"] for row in usage_records] == [0, 120, 175]
        assert [row["current_usage_size"] for row in usage_records] == [120, 175, 200]
        assert [row["cached_tokens"] for row in usage_records] == [0, 120, 175]
        assert [row["uncached_tokens"] for row in usage_records] == [120, 55, 25]
        assert [row["cached_input_weight_scaled"] for row in usage_records] == [1_000] * 3
        assert [row["calculation_scale"] for row in usage_records] == [10_000] * 3
        assert [row["effective_tokens_scaled"] for row in usage_records] == [
            1_200_000,
            670_000,
            425_000,
        ]
        assert [row["calculated_credits"] for row in usage_records] == [1, 1, 1]

        # A turn in another tenant must not leak into this tenant's aggregate. A turn by another
        # user in this tenant must count for the tenant but not for this user's own usage.
        _seed_user(
            settings,
            "other_tenant_user",
            "other-tenant@example.com",
            "Other Tenant User",
            "other-tenant-secret",
        )
        _seed_user(
            settings,
            "other_default_user",
            "other-default@example.com",
            "Other Default User",
            "other-default-secret",
        )
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                insert into tenants (id, type, name, slug, status)
                values ('tenant_other', 'team', 'Other Tenant', 'other', 'active')
                """
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('tenant_other_member', 'tenant_other', 'other_tenant_user', 'member')
                """
            )
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values ('tenant_default_other_member', 'tenant_default', 'other_default_user', 'member')
                """
            )
            connection.execute(
                """
                insert into chat_sessions (id, tenant_id, user_id, title)
                values (
                    'session_other_tenant', 'tenant_other', 'other_tenant_user', 'Other tenant'
                )
                """
            )
            connection.execute(
                """
                insert into chat_sessions (id, tenant_id, user_id, title)
                values (
                    'session_other_default_user', 'tenant_default', 'other_default_user',
                    'Other default user'
                )
                """
            )
            connection.execute(
                """
                insert into chat_turns (
                    id, session_id, tenant_id, user_id, request_text, status,
                    token_usage_scope, token_usage_snapshot, token_used
                )
                values (
                    'turn_other_tenant', 'session_other_tenant', 'tenant_other',
                    'other_tenant_user', 'do not include', 'completed', 'no_search', 9999, 9999
                )
                """
            )
            connection.execute(
                """
                insert into chat_turns (
                    id, session_id, tenant_id, user_id, request_text, status,
                    token_usage_scope, token_usage_snapshot, token_used
                )
                values (
                    'turn_other_default_user', 'session_other_default_user', 'tenant_default',
                    'other_default_user', 'tenant-only usage', 'completed', 'no_search', 8888, 8888
                )
                """
            )
            connection.commit()

        other_login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "other-tenant@example.com",
                "password": "other-tenant-secret",
                "tenantId": "tenant_other",
            },
        )
        assert other_login.status_code == 200
        other_headers = {
            "Authorization": f"Bearer {other_login.json()['accessToken']}",
            "x-tenant-id": "tenant_other",
        }
        assert client.get(
            f"/api/v1/chat/sessions/{session_id}", headers=other_headers
        ).status_code == 404
        assert client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=other_headers,
            json={"question": "cross-tenant access"},
        ).status_code == 404
        assert client.get(
            "/api/v1/chat/sessions/session_other_tenant", headers=tenant_headers
        ).status_code == 404

        admin_login = client.post(
            "/api/v1/auth/login",
            json={"email": "platform-admin@example.com", "password": "admin-secret"},
        )
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['accessToken']}"}
        tenants = client.get(
            "/api/v1/tenants",
            headers=admin_headers,
            params={"page": 1, "pageSize": 20},
        )
        assert tenants.status_code == 200
        tenant = next(item for item in tenants.json()["items"] if item["id"] == "tenant_default")
        assert tenant["monthlyCredits"] == {
            "monthlyCreditLimit": 6000,
            "estimatedUsedCredits": 3,
            "deductedCredits": 3,
            "remainingCredits": 5997,
            "enforcementEnabled": True,
        }

        users = client.get("/api/v1/users", headers=admin_headers)
        assert users.status_code == 200
        tenant_user = next(
            item for item in users.json()["items"] if item["email"] == "tenant@example.com"
        )
        assert "monthlyUsage" not in tenant_user


def test_chat_acp_usage_keeps_search_and_default_sessions_independent(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_scoped_usage.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpScopedUsageGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)
        session_id = client.post(
            "/api/v1/chat/sessions", headers=headers, json={"title": "Scoped Usage"}
        ).json()["id"]

        for enabled in (True, False, True, False):
            turn = client.post(
                f"/api/v1/chat/sessions/{session_id}/turns",
                headers=headers,
                json={"question": "count independently", "webSearchEnabled": enabled},
            )
            assert turn.status_code == 200

        with open_database_connection(settings) as connection:
            rows = connection.execute(
                """
                select token_usage_scope, token_usage_session_id,
                       token_usage_previous_snapshot, token_usage_snapshot, token_used
                from chat_turns
                order by created_at asc
                """
            ).fetchall()

        assert [row["token_usage_scope"] for row in rows] == [
            "search",
            "no_search",
            "search",
            "no_search",
        ]
        assert [row["token_usage_snapshot"] for row in rows] == [100, 200, 130, 260]
        assert [row["token_usage_previous_snapshot"] for row in rows] == [0, 0, 100, 200]
        assert [row["token_usage_session_id"] for row in rows] == [
            "acp_sess_1",
            "acp_sess_2",
            "acp_sess_1",
            "acp_sess_2",
        ]
        assert [row["token_used"] for row in rows] == [100, 200, 30, 60]


def test_chat_acp_turn_forwards_web_search_mode(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_web_search.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_backend="acp",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        session_id = client.post(
            "/api/v1/chat/sessions", headers=headers, json={"title": "Search Test"}
        ).json()["id"]

        enabled = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello", "webSearchEnabled": True},
        )
        disabled = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "again", "webSearchEnabled": False},
        )

        assert enabled.status_code == 200
        assert disabled.status_code == 200
        assert fake_acp.turn_calls[0]["search_mode"] == "auto"
        assert fake_acp.turn_calls[0]["route_prefix"] == fake_acp.search_route_prefix
        assert fake_acp.turn_calls[0]["session_id"] is None
        assert fake_acp.turn_calls[0]["input"].startswith("hello\n\n[Internal personal Library authorization]")
        assert fake_acp.turn_calls[1]["search_mode"] == "off"
        assert fake_acp.turn_calls[1]["route_prefix"] == fake_acp.route_prefix
        assert fake_acp.turn_calls[1]["session_id"] is None
        assert fake_acp.turn_calls[1]["input"].startswith("again\n\n[Internal personal Library authorization]")

        resumed_search = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "search again", "webSearchEnabled": True},
        )

        assert resumed_search.status_code == 200
        assert fake_acp.turn_calls[2]["search_mode"] == "auto"
        assert fake_acp.turn_calls[2]["route_prefix"] == fake_acp.search_route_prefix
        assert fake_acp.turn_calls[2]["session_id"] == "acp_sess_1"


def test_chat_acp_empty_stream_fails_turn(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_empty_stream.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_backend="acp",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpEmptyStreamGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )

        assert turn.status_code == 200
        assert "event: turn_started" in turn.text
        assert "event: error" in turn.text
        assert "interrupted before completion" in turn.text

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        item = messages.json()["items"][0]
        assert item["status"] == "failed"
        assert item["responseText"] == ""
        assert "interrupted before completion" in item["errorMessage"]


def test_chat_acp_client_error_is_streamed_and_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_client_error.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_backend="acp",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = FakeAcpErrorGatewayClient

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )

        assert turn.status_code == 200
        assert "event: turn_started" in turn.text
        assert "event: error" in turn.text
        assert "reached max_instances 2" not in turn.text
        assert "The requested operation could not be completed" in turn.text

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        item = messages.json()["items"][0]
        assert item["status"] == "failed"
        assert "reached max_instances 2" not in item["errorMessage"]


def test_chat_acp_unexpected_error_is_streamed_and_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_unexpected_error.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_backend="acp",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = FakeAcpUnexpectedErrorGatewayClient

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )

        assert turn.status_code == 200
        assert "event: turn_started" in turn.text
        assert "event: error" in turn.text
        assert "CHAT_TURN_FAILED" in turn.text
        assert "event: turn_completed" not in turn.text

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        item = messages.json()["items"][0]
        assert item["status"] == "failed"
        assert item["responseText"] == ""
        assert item["errorMessage"] == "Chat turn failed unexpectedly. Please retry."


def test_chat_acp_backend_translates_reasoning_and_tool_call(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_reasoning.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpReasoningGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        session_id = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"title": "ACP Reasoning"},
        ).json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )

        assert turn.status_code == 200
        assert "event: reasoning_delta" in turn.text
        assert "thinking" not in turn.text
        assert "expert_knowledge/search_expert_knowledge" not in turn.text
        assert turn.text.index("event: reasoning_delta") < turn.text.index("event: message_delta")

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        item = messages.json()["items"][0]
        assert "thinking" not in item["reasoningText"]
        assert "expert_knowledge/search_expert_knowledge" not in item["reasoningText"]
        assert '"query": "hello"' not in item["reasoningText"]
        assert "turnId" not in item["reasoningText"]
        assert item["reasoningText"] == "Processing your request.\n"
        assert item["responseText"] == "final answer"


def test_default_chat_transcript_excludes_internal_capabilities(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_transcript.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings, "tenant_user", "tenant@example.com", "Tenant User", "tenant-secret", "member"
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "tenant@example.com", "password": "tenant-secret", "tenantId": "tenant_default"},
        )
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        session_id = client.post(
            "/api/v1/chat/sessions", headers=headers, json={"title": "Replay"}
        ).json()["id"]

        # Before any turn there is no ACP session, so replay falls back to the local record.
        empty = client.get(f"/api/v1/chat/sessions/{session_id}/transcript", headers=headers)
        assert empty.status_code == 200
        assert empty.json() == {"sessionId": session_id, "messages": [], "source": "local"}

        # Run a turn so the agent-assigned session id is captured and persisted.
        client.post(
            f"/api/v1/chat/sessions/{session_id}/turns", headers=headers, json={"question": "hello"}
        )

        transcript = client.get(f"/api/v1/chat/sessions/{session_id}/transcript", headers=headers)
        assert transcript.status_code == 200
        body = transcript.json()
        assert body["source"] == "local"
        assert body["sessionId"] == session_id
        assert body["messages"][0] == {"role": "user", "text": "hello"}
        assert fake_acp.transcript_calls == []
        assert "turnCapability" in fake_acp.turn_calls[-1]["input"]
        assert "lturn_" not in json.dumps(body)



def _login_tenant_member(client: TestClient, settings: Settings) -> dict[str, str]:
    _seed_tenant(settings)
    _seed_tenant_user(
        settings,
        "tenant_user",
        "tenant@example.com",
        "Tenant User",
        "tenant-secret",
        "member",
    )
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "tenant@example.com",
            "password": "tenant-secret",
            "tenantId": "tenant_default",
        },
    )
    assert login.status_code == 200
    return {
        "Authorization": f"Bearer {login.json()['accessToken']}",
        "x-tenant-id": "tenant_default",
    }


def test_chat_acp_auto_title_via_session_info_event(tmp_path: Path) -> None:
    # The live `session_info` SSE path, for agents like opencode that DO emit session_info_update.
    # The session list returns no title for this fake, so the title can only come from the stream event.
    database_path = tmp_path / "chat_acp_title.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpTitleGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)

        # Create with a preset title: the agent's nested session_info title must not clobber it.
        preset = client.post(
            "/api/v1/chat/sessions", headers=headers, json={"title": "Preset"}
        )
        assert preset.status_code == 201
        preset_id = preset.json()["id"]
        turn_preset = client.post(
            f"/api/v1/chat/sessions/{preset_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )
        assert "event: session_title_updated" not in turn_preset.text
        assert (
            client.get(f"/api/v1/chat/sessions/{preset_id}", headers=headers).json()["title"]
            == "Preset"
        )

        # Create without a title: the nested ACP session_info title fills it and emits a frame.
        created = client.post("/api/v1/chat/sessions", headers=headers, json={})
        session_id = created.json()["id"]
        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )
        assert "event: session_title_updated" in turn.text
        assert "Auto 2" in turn.text  # second stream_turn call on this fake
        assert (
            client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()["title"]
            == "Auto 2"
        )


def test_chat_acp_auto_title_from_route_session_list(tmp_path: Path) -> None:
    # The codex-acp path: the gateway emits no session_info, so the title is reconciled from the
    # route-scoped session list after the turn, keyed by the bound acp_session_id.
    database_path = tmp_path / "chat_acp_title_list.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpTitleListGatewayClient()  # streams session/delta/done, title via session/list
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)

        # Empty title: reconciled from session/list after the turn binds the acp_session_id.
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns", headers=headers, json={"question": "hi"}
        )
        assert "event: session_title_updated" in turn.text
        assert "Codex Title" in turn.text
        assert (
            client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()["title"]
            == "Codex Title"
        )
        assert fake_acp.list_calls  # the route session list was consulted
        # Lookup is keyed by the agent session id + tenant cwd, not the local thread id.
        assert fake_acp.list_calls[-1]["cwd"] == fake_acp.prepare_user_cwd(
            "tenant_default", "tenant_user"
        )

        # Preset title: reconciliation is short-circuited -- no session list lookup, no clobber.
        calls_before = len(fake_acp.list_calls)
        preset_id = client.post(
            "/api/v1/chat/sessions", headers=headers, json={"title": "Preset"}
        ).json()["id"]
        preset_turn = client.post(
            f"/api/v1/chat/sessions/{preset_id}/turns", headers=headers, json={"question": "hi"}
        )
        assert "event: session_title_updated" not in preset_turn.text
        assert (
            client.get(f"/api/v1/chat/sessions/{preset_id}", headers=headers).json()["title"]
            == "Preset"
        )
        assert len(fake_acp.list_calls) == calls_before  # skipped while the title is non-empty


def test_chat_sessions_can_be_listed_by_archive_status(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_archive.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        created = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"title": "Archive Test"},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        assert created.json()["status"] == "active"

        archived = client.patch(
            f"/api/v1/chat/sessions/{session_id}/archive",
            headers=headers,
            json={"archived": True},
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"

        active_list = client.get("/api/v1/chat/sessions", headers=headers)
        assert active_list.status_code == 200
        assert active_list.json()["items"] == []

        archived_list = client.get(
            "/api/v1/chat/sessions",
            headers=headers,
            params={"status": "archived"},
        )
        assert archived_list.status_code == 200
        assert [item["id"] for item in archived_list.json()["items"]] == [session_id]

        restored = client.patch(
            f"/api/v1/chat/sessions/{session_id}/archive",
            headers=headers,
            json={"archived": False},
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "active"

        active_list = client.get("/api/v1/chat/sessions", headers=headers)
        assert active_list.status_code == 200
        assert [item["id"] for item in active_list.json()["items"]] == [session_id]


def test_chat_session_delete_is_soft_delete(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_soft_delete.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        assert login.status_code == 200
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }

        created = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"title": "Soft Delete Test"},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )
        assert turn.status_code == 200

        deleted = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json() == {"id": session_id, "status": "deleted"}

        listed = client.get("/api/v1/chat/sessions", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"] == []
        assert client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).status_code == 404
        assert (
            client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers).status_code
            == 404
        )

    with open_database_connection(settings) as connection:
        session = connection.execute(
            "select deleted_at from chat_sessions where id = ?",
            (session_id,),
        ).fetchone()
        turns = connection.execute(
            "select count(*) as count from chat_turns where session_id = ?",
            (session_id,),
        ).fetchone()

    assert session is not None
    assert session["deleted_at"] is not None
    assert turns["count"] == 1


def test_chat_acp_backend_does_not_silently_reset_stale_resume_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "chat_acp_stale_session.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpStaleUsageGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        _seed_tenant(settings)
        _seed_tenant_user(
            settings,
            "tenant_user",
            "tenant@example.com",
            "Tenant User",
            "tenant-secret",
            "member",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "tenant@example.com",
                "password": "tenant-secret",
                "tenantId": "tenant_default",
            },
        )
        headers = {
            "Authorization": f"Bearer {login.json()['accessToken']}",
            "x-tenant-id": "tenant_default",
        }
        created = client.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={"title": "ACP stale session"},
        )
        session_id = created.json()["id"]
        first_turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )
        assert first_turn.status_code == 200

        fake_acp.fail_next_resume = True
        resumed_turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "after restart"},
        )

        assert resumed_turn.status_code == 200
        assert "network error" not in resumed_turn.text
        assert "ACP_SESSION_RESUME_FAILED" in resumed_turn.text
        assert '"contextReset": false' in resumed_turn.text
        assert "event: message_delta" not in resumed_turn.text
        assert "event: turn_completed" not in resumed_turn.text
        assert fake_acp.turn_calls[1]["session_id"] == "acp_sess_1"
        assert len(fake_acp.turn_calls) == 2

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        items = messages.json()["items"]
        assert items[-1]["status"] == "failed"
        assert items[-1]["responseText"] == ""
        assert "could not be resumed" in items[-1]["errorMessage"]

        with open_database_connection(settings) as connection:
            usage_rows = connection.execute(
                """
                select token_usage_snapshot, token_used
                from chat_turns
                order by created_at asc
                """
            ).fetchall()

        # The saved ACP id remains bound and no empty replacement session is created.
        assert [row["token_usage_snapshot"] for row in usage_rows] == [120, 0]
        assert [row["token_used"] for row in usage_rows] == [120, 0]


def test_chat_acp_backend_retries_transient_first_turn_before_output(tmp_path: Path) -> None:
    database_path = tmp_path / "chat_acp_first_turn_retry.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_backend="acp",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpTransientFirstTurnGatewayClient()
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )

        assert turn.status_code == 200
        assert "idle timeout" not in turn.text
        assert "event: message_delta" in turn.text
        assert "event: turn_completed" in turn.text
        assert len(fake_acp.turn_calls) == 2
        assert fake_acp.turn_calls[0]["session_id"] is None
        assert fake_acp.turn_calls[1]["session_id"] is None
        assert fake_acp.turn_calls[1]["fresh_session"] is True

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        item = messages.json()["items"][0]
        assert item["status"] == "completed"
        assert item["responseText"] == "ok"
        assert item["errorMessage"] is None


@pytest.mark.parametrize(
    ("retry_error", "expected_code", "expected_message"),
    [
        (
            ApiError(503, "ACP_UNAVAILABLE", "retry capacity unavailable"),
            "ACP_UNAVAILABLE",
            "The requested operation could not be completed. Please try again.",
        ),
        (
            RuntimeError("unexpected retry failure"),
            "CHAT_TURN_FAILED",
            "Chat turn failed unexpectedly. Please retry.",
        ),
    ],
    ids=["api-error", "unexpected-error"],
)
def test_chat_acp_failed_fresh_retry_is_streamed_and_persisted(
    tmp_path: Path,
    retry_error: Exception,
    expected_code: str,
    expected_message: str,
) -> None:
    database_path = tmp_path / "chat_acp_failed_fresh_retry.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_backend="acp",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
    )
    fake_acp = FakeAcpFailedRetryGatewayClient(retry_error)
    test_app = create_app(settings)
    test_app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp

    with TestClient(test_app) as client:
        headers = _login_tenant_member(client, settings)
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "hello"},
        )

        assert turn.status_code == 200
        assert turn.text.count("event: error") == 1
        assert expected_code in turn.text
        assert expected_message in turn.text
        assert "event: turn_completed" not in turn.text
        assert len(fake_acp.turn_calls) == 2
        assert fake_acp.turn_calls[1]["fresh_session"] is True

        messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
        assert messages.status_code == 200
        item = messages.json()["items"][0]
        assert item["status"] == "failed"
        assert item["responseText"] == ""
        assert item["errorMessage"] == expected_message


def test_acp_gateway_keeps_default_and_tenant_workspaces_distinct(tmp_path: Path) -> None:
    default = tmp_path / "legacy-workspace"
    base = tmp_path / "tenant-workspaces"
    base.mkdir()
    client = AcpGatewayClient(
        Settings(acp_default_cwd=str(default), acp_cwd_base=str(base))
    )

    assert client.prepare_default_cwd() == str(default)
    assert client.prepare_tenant_cwd("tenant_default") == str(base / "tenant_default")
    assert default.is_dir()
    assert (base / "tenant_default").is_dir()


def test_acp_gateway_prepare_tenant_cwd_creates_per_tenant_dir(tmp_path: Path) -> None:
    # The agent chdirs into cwd, so the per-tenant subdir under an absolute base must be created
    # (regression: an absolute cwd_base used to return early without mkdir, breaking codex chdir).
    base = tmp_path / "acp-roots"
    base.mkdir()
    client = AcpGatewayClient(Settings(acp_default_cwd="/unused", acp_cwd_base=str(base)))

    cwd = client.prepare_tenant_cwd("tenant_default")

    assert cwd == str(base / "tenant_default")
    assert (base / "tenant_default").is_dir()
    for name in (".git", ".agents", ".codex"):
        target = base / "tenant_default" / name
        assert target.is_dir()
        assert list(target.iterdir()) == []
    assert client.prepare_tenant_cwd("tenant_default") == cwd


def test_acp_gateway_prepare_user_cwd_creates_isolated_workspace(tmp_path: Path) -> None:
    base = tmp_path / "acp-roots"
    client = AcpGatewayClient(Settings(acp_default_cwd="/unused", acp_cwd_base=str(base)))

    cwd = client.prepare_user_cwd("tenant_default", "user_default")

    expected = base / "tenant_default" / "users" / "user_default"
    assert cwd == str(expected)
    assert expected.is_dir()
    for name in (".git", ".agents", ".codex"):
        target = expected / name
        assert target.is_dir()
        assert list(target.iterdir()) == []
    assert client.prepare_user_cwd("tenant_default", "user_default") == cwd


@pytest.mark.parametrize("user_id", ["", ".", "..", "../escape", "/absolute", "a/b", r"a\b"])
def test_acp_gateway_rejects_unsafe_user_workspace_segments(
    tmp_path: Path, user_id: str
) -> None:
    base = tmp_path / "tenant-workspaces"
    client = AcpGatewayClient(Settings(acp_cwd_base=str(base)))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_user_cwd("tenant_default", user_id)

    assert exc_info.value.code == "ACP_TENANT_CWD_INVALID"
    assert not (tmp_path / "escape").exists()


def test_acp_gateway_rejects_tenant_sandbox_mount_symlink(tmp_path: Path) -> None:
    base = tmp_path / "tenant-workspaces"
    tenant = base / "tenant_default"
    outside = tmp_path / "outside"
    tenant.mkdir(parents=True)
    outside.mkdir()
    (tenant / ".git").symlink_to(outside, target_is_directory=True)
    client = AcpGatewayClient(Settings(acp_default_cwd="/unused", acp_cwd_base=str(base)))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_tenant_cwd("tenant_default")

    assert exc_info.value.code == "ACP_TENANT_CWD_INVALID"
    assert list(outside.iterdir()) == []


def test_acp_gateway_creates_backend_managed_tenant_root(tmp_path: Path) -> None:
    base = tmp_path / "tenant-workspaces"
    client = AcpGatewayClient(Settings(acp_cwd_base=str(base)))

    cwd = client.prepare_tenant_cwd("tenant_default")

    assert cwd == str(base / "tenant_default")
    assert base.is_dir()
    for name in (".git", ".agents", ".codex"):
        assert (base / "tenant_default" / name).is_dir()


@pytest.mark.parametrize("tenant_id", ["", ".", "..", "../escape", "/absolute", "a/b", r"a\b"])
def test_acp_gateway_rejects_unsafe_tenant_workspace_segments(
    tmp_path: Path, tenant_id: str
) -> None:
    base = tmp_path / "tenant-workspaces"
    client = AcpGatewayClient(Settings(acp_cwd_base=str(base)))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_tenant_cwd(tenant_id)

    assert exc_info.value.code == "ACP_TENANT_CWD_INVALID"
    assert not (tmp_path / "escape").exists()


def test_acp_gateway_rejects_tenant_workspace_symlink_escape(tmp_path: Path) -> None:
    base = tmp_path / "tenant-workspaces"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    (base / "tenant_link").symlink_to(outside, target_is_directory=True)
    client = AcpGatewayClient(Settings(acp_cwd_base=str(base)))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_tenant_cwd("tenant_link")

    assert exc_info.value.code == "ACP_TENANT_CWD_INVALID"


def test_acp_gateway_reports_tenant_workspace_creation_failure(tmp_path: Path) -> None:
    base = tmp_path / "not-a-directory"
    base.write_text("occupied", encoding="utf-8")
    client = AcpGatewayClient(Settings(acp_cwd_base=str(base)))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_tenant_cwd("tenant_default")

    assert exc_info.value.code == "ACP_CWD_PREPARE_FAILED"


def test_acp_gateway_requires_tenant_workspace_root() -> None:
    client = AcpGatewayClient(Settings(acp_cwd_base=None))

    with pytest.raises(ApiError) as exc_info:
        client.prepare_tenant_cwd("tenant_default")

    assert exc_info.value.code == "ACP_TENANT_CWD_UNCONFIGURED"


def test_acp_stream_turn_builds_turn_request_payload() -> None:
    client = AcpGatewayClient(
        Settings(
            acp_gateway_base_url="http://gateway.test",
            acp_route_prefix="/acp",
            acp_default_model="claude-opus",
        )
    )
    captured: dict = {}

    def fake_stream(method, path, *, tenant_id=None, **kwargs):
        captured.update(method=method, path=path, tenant_id=tenant_id, json=kwargs.get("json"))

        async def empty():
            return
            yield  # pragma: no cover - marks this an async generator

        return empty()

    client.stream = fake_stream  # type: ignore[assignment]

    async def drive() -> None:
        agen = client.stream_turn(
            thread_id="thread_1",
            input="hello",
            tenant_id="tenant_default",
            session_id="",  # falsy -> omitted, lets the agent assign one on the first turn
            config_overrides={"thought_level": "medium"},
            search_mode="auto",
            route_prefix="/acp-search",
        )
        async for _ in agen:
            pass

    asyncio.run(drive())

    assert captured["method"] == "POST"
    assert captured["path"] == "/acp-search/turn"
    assert captured["tenant_id"] == "tenant_default"
    # The deployed ACP route accepts acpruntime.TurnRequest directly;
    # search mode is selected by the route, not the payload.
    assert captured["json"] == {
        "thread_id": "thread_1",
        "input": "hello",
        "model": "claude-opus",
        "config_overrides": {"thought_level": "medium"},
    }


def test_acp_stream_turn_builds_payload_with_optional_runtime_fields() -> None:
    client = AcpGatewayClient(
        Settings(
            acp_gateway_base_url="http://gateway.test",
            acp_route_prefix="/acp-llm",
            acp_default_model="gpt-default",
        )
    )
    captured: dict = {}

    def fake_stream(method, path, *, tenant_id=None, **kwargs):
        captured.update(method=method, path=path, tenant_id=tenant_id, json=kwargs.get("json"))

        async def empty():
            return
            yield  # pragma: no cover - marks this an async generator

        return empty()

    client.stream = fake_stream  # type: ignore[assignment]

    async def drive() -> None:
        async for _ in client.stream_turn(
            thread_id="thread_default",
            input="hello",
            tenant_id="tenant_default",
            session_id="session_default",
            cwd="/workspace/default",
            fresh_session=True,
            config_overrides={"reasoning_effort": "medium"},
        ):
            pass

    asyncio.run(drive())

    assert captured == {
        "method": "POST",
        "path": "/acp-llm/turn",
        "tenant_id": "tenant_default",
        "json": {
            "input": "hello",
            "thread_id": "thread_default",
            "cwd": "/workspace/default",
            "model": "gpt-default",
            "fresh_session": True,
            "config_overrides": {"reasoning_effort": "medium"},
            "session_id": "session_default",
        },
    }


def test_acp_resolve_permission_sends_request_id_in_body() -> None:
    client = AcpGatewayClient(
        Settings(acp_gateway_base_url="http://gateway.test", acp_route_prefix="/acp")
    )
    captured: dict = {}

    async def fake_request(method, path, *, tenant_id=None, **kwargs):
        captured.update(method=method, path=path, tenant_id=tenant_id, json=kwargs.get("json"))
        return {"status": "resolved"}

    client.request = fake_request  # type: ignore[assignment]

    result = asyncio.run(
        client.resolve_permission(
            request_id="req_1",
            outcome="selected",
            option_id="allow",
            tenant_id="tenant_default",
        )
    )

    assert result == {"status": "resolved"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/acp/permission"
    assert captured["json"] == {
        "request_id": "req_1",
        "outcome": "selected",
        "option_id": "allow",
    }


def _seed_tenant(settings: Settings) -> None:
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into tenants (id, type, name, slug, status)
            values ('tenant_default', 'team', 'Default Tenant', 'default', 'active')
            on conflict (id) do nothing
            """
        )
        connection.commit()


def _seed_user(
    settings: Settings,
    user_id: str,
    email: str,
    name: str,
    password: str,
) -> None:
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values (?, ?, ?, ?, 'active')
            """,
            (user_id, email, hash_password(password), name),
        )
        connection.commit()


def _seed_tenant_user(
    settings: Settings,
    user_id: str,
    email: str,
    name: str,
    password: str,
    role: str,
) -> None:
    _seed_user(settings, user_id, email, name, password)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into tenant_members (id, tenant_id, user_id, role)
            values (?, ?, ?, ?)
            """,
            (f"{user_id}_member", "tenant_default", user_id, role),
        )
        connection.commit()


def _seed_platform_user(
    settings: Settings,
    user_id: str,
    email: str,
    name: str,
    password: str,
    role: str,
) -> None:
    _seed_user(settings, user_id, email, name, password)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into platform_user_roles (id, user_id, role, assigned_by)
            values (?, ?, ?, ?)
            """,
            (f"{user_id}_platform_role", user_id, role, user_id),
        )
        connection.commit()


class FakeAcpGatewayClient:
    def __init__(self) -> None:
        self.route_prefix = "/acp"
        self.search_route_prefix = "/acp-search"
        self.default_model = "claude-opus"
        self.default_cwd = "/tmp/acp"
        self.tenant_cwd_base = "/tmp/acp-tenants"
        self.turn_calls: list[dict] = []
        self.transcript_calls: list[dict] = []
        self.list_calls: list[dict] = []
        self.fail_next_resume = False
        self._sessions_by_route: dict[str, str] = {}

    def prepare_default_cwd(self) -> str:
        return self.default_cwd

    def prepare_tenant_cwd(self, tenant_id: str) -> str:
        return f"{self.tenant_cwd_base}/{tenant_id}"

    def prepare_user_cwd(self, tenant_id: str, user_id: str) -> str:
        return f"{self.tenant_cwd_base}/{tenant_id}/users/{user_id}"

    async def get_transcript(
        self,
        *,
        session_id: str,
        tenant_id: str | None = None,
        cwd: str | None = None,
        route_prefix: str | None = None,
    ) -> dict:
        self.transcript_calls.append(
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "cwd": cwd,
                "route_prefix": route_prefix,
            }
        )
        return {
            "session_id": session_id,
            "messages": [
                {"role": "user", "text": "hello"},
                {"role": "assistant", "text": "ok"},
            ],
        }

    async def list_sessions(
        self,
        *,
        tenant_id: str | None = None,
        cwd: str | None = None,
        cursor: str | None = None,
        route_prefix: str | None = None,
    ) -> dict:
        self.list_calls.append(
            {"tenant_id": tenant_id, "cwd": cwd, "cursor": cursor, "route_prefix": route_prefix}
        )
        return {"sessions": [], "next_cursor": ""}

    def stream_turn(
        self,
        *,
        thread_id: str,
        input: str,
        tenant_id: str | None = None,
        session_id: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        fresh_session: bool = False,
        config_overrides: dict | None = None,
        search_mode: str | None = None,
        route_prefix: str | None = None,
    ):
        self.turn_calls.append(
            {
                "thread_id": thread_id,
                "input": input,
                "tenant_id": tenant_id,
                "session_id": session_id,
                "cwd": cwd,
                "fresh_session": fresh_session,
                "config_overrides": config_overrides,
                "search_mode": search_mode,
                "route_prefix": route_prefix,
            }
        )

        async def gen():
            if self.fail_next_resume and session_id:
                self.fail_next_resume = False
                yield "event: error"
                yield 'data: {"message": "network error"}'
                yield ""
                return
            bound_session_id = session_id
            if not bound_session_id:
                route_key = route_prefix or self.route_prefix
                bound_session_id = self._sessions_by_route.setdefault(
                    route_key, f"acp_sess_{len(self._sessions_by_route) + 1}"
                )
            yield "event: session"
            yield f'data: {{"session_id": "{bound_session_id}"}}'
            yield ""
            yield "event: delta"
            yield 'data: {"text": "ok"}'
            yield ""
            yield "event: done"
            yield 'data: {"stop_reason": "end_turn"}'
            yield ""

        return gen()


class FakeAcpUsageGatewayClient(FakeAcpGatewayClient):
    def __init__(self) -> None:
        super().__init__()
        self._turn = 0

    def stream_turn(self, **kwargs):
        self.turn_calls.append(kwargs)
        self._turn += 1
        bound_session_id = kwargs.get("session_id") or "acp_sess_usage"

        async def gen():
            yield "event: session"
            yield f'data: {{"session_id": "{bound_session_id}"}}'
            yield ""
            if self._turn == 2:
                yield "event: usage"
                yield (
                    'data: {"data": {"sessionUpdate": "usage_update", '
                    '"used": 120, "size": 258400}}'
                )
                yield ""
            yield "event: delta"
            yield 'data: {"text": "ok"}'
            yield ""
            yield "event: usage"
            final_used = {1: 120, 2: 175, 3: 200}[self._turn]
            yield (
                'data: {"data": {"sessionUpdate": "usage_update", '
                f'"used": {final_used}, "size": 258400}}}}'
            )
            yield ""
            yield "event: done"
            yield 'data: {"stop_reason": "end_turn"}'
            yield ""

        return gen()


class FakeAcpScopedUsageGatewayClient(FakeAcpGatewayClient):
    def __init__(self) -> None:
        super().__init__()
        self._turn_by_mode = {"auto": 0, "off": 0}

    def stream_turn(self, **kwargs):
        base = super().stream_turn(**kwargs)
        mode = kwargs.get("search_mode") or "off"
        self._turn_by_mode[mode] += 1
        turn_number = self._turn_by_mode[mode]
        usage_by_mode = {"auto": (100, 130), "off": (200, 260)}
        used = usage_by_mode[mode][turn_number - 1]

        async def gen():
            async for line in base:
                if line == "event: done":
                    yield "event: usage"
                    yield (
                        'data: {"data": {"sessionUpdate": "usage_update", '
                        f'"used": {used}, "size": 258400}}}}'
                    )
                    yield ""
                yield line

        return gen()


class FakeAcpStaleUsageGatewayClient(FakeAcpGatewayClient):
    def __init__(self) -> None:
        super().__init__()
        self._successful_turns = 0

    def stream_turn(self, **kwargs):
        base = super().stream_turn(**kwargs)

        async def gen():
            async for line in base:
                if line == "event: done":
                    self._successful_turns += 1
                    used = 120 if self._successful_turns == 1 else 130
                    yield "event: usage"
                    yield (
                        'data: {"data": {"sessionUpdate": "usage_update", '
                        f'"used": {used}, "size": 258400}}}}'
                    )
                    yield ""
                yield line

        return gen()


class FakeAcpEmptyStreamGatewayClient(FakeAcpGatewayClient):
    def stream_turn(self, **kwargs):
        self.turn_calls.append(kwargs)

        async def gen():
            if False:
                yield ""

        return gen()


class FakeAcpErrorGatewayClient(FakeAcpGatewayClient):
    def stream_turn(self, **kwargs):
        self.turn_calls.append(kwargs)
        raise ApiError(
            503,
            "ACP_UNAVAILABLE",
            'acp instance capacity exceeded: service "codex-main" reached max_instances 2',
        )


class FakeAcpUnexpectedErrorGatewayClient(FakeAcpGatewayClient):
    def stream_turn(self, **kwargs):
        self.turn_calls.append(kwargs)
        raise RuntimeError("unexpected test failure")


class FakeAcpTransientFirstTurnGatewayClient(FakeAcpGatewayClient):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    def stream_turn(self, **kwargs):
        if not self.failed_once:
            self.failed_once = True
            self.turn_calls.append(kwargs)

            async def failed():
                yield "event: session"
                yield 'data: {"session_id": "acp_sess_wedged"}'
                yield ""
                yield "event: error"
                yield 'data: {"message": "acp turn idle timeout: no turn events for 25s"}'
                yield ""

            return failed()
        return super().stream_turn(**kwargs)


class FakeAcpFailedRetryGatewayClient(FakeAcpGatewayClient):
    def __init__(self, retry_error: Exception) -> None:
        super().__init__()
        self.retry_error = retry_error

    def stream_turn(self, **kwargs):
        self.turn_calls.append(kwargs)
        if len(self.turn_calls) == 1:

            async def failed():
                yield "event: error"
                yield 'data: {"message": "acp turn idle timeout: no turn events for 25s"}'
                yield ""

            return failed()
        raise self.retry_error


class FakeAcpReasoningGatewayClient(FakeAcpGatewayClient):
    def stream_turn(
        self,
        *,
        thread_id: str,
        input: str,
        tenant_id: str | None = None,
        session_id: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        fresh_session: bool = False,
        config_overrides: dict | None = None,
        search_mode: str | None = None,
        route_prefix: str | None = None,
    ):
        self.turn_calls.append(
            {
                "thread_id": thread_id,
                "input": input,
                "tenant_id": tenant_id,
                "session_id": session_id,
                "cwd": cwd,
                "fresh_session": fresh_session,
                "config_overrides": config_overrides,
                "search_mode": search_mode,
                "route_prefix": route_prefix,
            }
        )

        async def gen():
            yield "event: session"
            yield 'data: {"session_id": "acp_sess_1"}'
            yield ""
            yield "event: reasoning"
            yield 'data: {"text": "thinking"}'
            yield ""
            yield "event: tool_call"
            yield (
                'data: {"data": {"title": "Tool: expert_knowledge/search_expert_knowledge", '
                '"rawInput": {"query": "hello", "turnId": "turn_internal"}, '
                '"status": "in_progress"}}'
            )
            yield ""
            yield "event: tool_call"
            yield (
                'data: {"data": {"content": [], "rawOutput": {}, '
                '"status": "completed"}}'
            )
            yield ""
            yield "event: delta"
            yield 'data: {"text": "final answer"}'
            yield ""
            yield "event: done"
            yield 'data: {"stop_reason": "end_turn"}'
            yield ""

        return gen()


class FakeAcpTitleGatewayClient(FakeAcpGatewayClient):
    """ACP gateway fake whose turn stream carries a per-turn auto-generated session title.

    The gateway wraps the raw ACP update under `data`, so the title is nested at
    `data.data.title` -- the shape the handler must dig through.
    """

    def __init__(self) -> None:
        super().__init__()
        self._turn = 0

    def stream_turn(self, **kwargs):
        self.turn_calls.append(
            {
                "thread_id": kwargs.get("thread_id"),
                "input": kwargs.get("input"),
                "tenant_id": kwargs.get("tenant_id"),
                "session_id": kwargs.get("session_id"),
                "cwd": kwargs.get("cwd"),
                "config_overrides": kwargs.get("config_overrides"),
                "search_mode": kwargs.get("search_mode"),
                "route_prefix": kwargs.get("route_prefix"),
            }
        )
        self._turn += 1
        title = f"Auto {self._turn}"

        async def gen():
            yield "event: session"
            yield 'data: {"session_id": "acp_sess_1"}'
            yield ""
            yield "event: session_info"
            yield (
                'data: {"data": {"sessionUpdate": "session_info_update", '
                f'"title": "{title}"}}}}'
            )
            yield ""
            yield "event: delta"
            yield 'data: {"text": "ok"}'
            yield ""
            yield "event: done"
            yield 'data: {"stop_reason": "end_turn"}'
            yield ""

        return gen()


class FakeAcpTitleListGatewayClient(FakeAcpGatewayClient):
    """ACP gateway fake whose route-scoped session/list carries the codex-derived title.

    codex-acp never emits `session_info_update`, so its title is only reachable through the
    route-scoped session list, keyed by the agent-assigned ACP session id. The turn stream from
    the base fake emits session/delta/done with no session_info.
    """

    async def list_sessions(
        self,
        *,
        tenant_id: str | None = None,
        cwd: str | None = None,
        cursor: str | None = None,
        route_prefix: str | None = None,
    ) -> dict:
        self.list_calls.append(
            {"tenant_id": tenant_id, "cwd": cwd, "cursor": cursor, "route_prefix": route_prefix}
        )
        return {
            "sessions": [{"session_id": "acp_sess_1", "title": "Codex Title", "cwd": cwd}],
            "next_cursor": "",
        }


def _skill_zip() -> BytesIO:
    content = BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr(
            "amazon-review-analyzer/SKILL.md",
            """---
name: amazon-review-analyzer
description: Analyze Amazon review trends and customer feedback.
version: 1.0.0
allowed-tools:
  - Bash(python scripts/analyze_reviews.py:*)
tags:
  - amazon
  - reviews
---
# Amazon Review Analyzer
""",
        )
        archive.writestr(
            "amazon-review-analyzer/scripts/analyze_reviews.py",
            "print('ok')\n",
        )
    content.seek(0)
    return content


# Knowledge base + document redesign -------------------------------------------------

from app.api.deps import get_object_store  # noqa: E402
from app.services.object_store import (  # noqa: E402
    MinioObjectStore,
    ObjectStat,
    ObjectStore,
    create_object_store,
)


class FakeObjectStore(ObjectStore):
    """In-memory stand-in for MinIO. Tests simulate the client PUT via `put`."""

    def __init__(self, bucket: str = "expert-docs") -> None:
        self._bucket = bucket
        self.objects: dict[str, int] = {}
        self.contents: dict[str, bytes] = {}
        self.content_types: dict[str, str | None] = {}
        self.removed: list[str] = []
        self.fail_remove: set[str] = set()

    @property
    def bucket(self) -> str:
        return self._bucket

    def presigned_put_url(self, object_key, *, expires, content_type=None, content_length=None) -> str:
        return f"https://minio.test/{self._bucket}/{object_key}?put"

    def presigned_get_url(self, object_key, *, expires, response_headers=None) -> str:
        suffix = "?get"
        if response_headers:
            suffix += "&" + "&".join(f"{key}={value}" for key, value in response_headers.items())
        return f"https://minio.test/{self._bucket}/{object_key}{suffix}"

    def stat(self, object_key: str) -> ObjectStat:
        if object_key not in self.objects:
            from app.core.errors import ApiError

            raise ApiError(404, "DOC_OBJECT_NOT_FOUND", "Uploaded object not found")
        return ObjectStat(size=self.objects[object_key], etag="fake-md5")

    def put(self, object_key: str, data: bytes | int, *, content_type=None) -> None:
        self.content_types[object_key] = content_type
        if isinstance(data, bytes):
            self.objects[object_key] = len(data)
            self.contents[object_key] = data
            return
        self.objects[object_key] = data
        self.contents[object_key] = b"\x00" * data

    def read(self, object_key: str, *, max_bytes=None) -> bytes:
        if object_key not in self.contents:
            from app.core.errors import ApiError

            raise ApiError(404, "DOC_OBJECT_NOT_FOUND", "Object not found")
        data = self.contents[object_key]
        if max_bytes is not None and len(data) > max_bytes:
            from app.core.errors import ApiError

            raise ApiError(413, "OBJECT_TOO_LARGE", "Object is too large to read inline")
        return data

    def remove(self, object_key: str) -> None:
        if object_key in self.fail_remove:
            raise RuntimeError("remove failed")
        self.removed.append(object_key)
        self.objects.pop(object_key, None)
        self.contents.pop(object_key, None)
        self.content_types.pop(object_key, None)


def _kb_test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'kb.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )


def _kb_app(settings: Settings, store: FakeObjectStore):
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store
    return app


def _minio_test_settings(
    public_endpoint: str | None, *, allow_local_endpoint: bool = False
) -> Settings:
    return Settings(
        _env_file=None,
        object_storage_backend="minio",
        minio_endpoint="minio:9000",
        minio_public_endpoint=public_endpoint,
        minio_allow_local_endpoint=allow_local_endpoint,
        minio_public_secure=True,
        minio_access_key="example-access",
        minio_secret_key="example-secret",
        minio_bucket="example-bucket",
        minio_secure=False,
    )


def test_minio_presigned_download_uses_explicit_public_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from minio import Minio

    monkeypatch.setattr(Minio, "bucket_exists", lambda *_: True)
    store = MinioObjectStore(_minio_test_settings("objects.example.test"))

    url = store.presigned_get_url(
        "knowledge-bases/kb_example/documents/doc_example/source.txt",
        expires=timedelta(minutes=5),
    )
    parsed = urlsplit(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "objects.example.test"
    assert all(
        marker not in url
        for marker in ("localhost", "127.0.0.1", "minio:9000", "172.18.0.2")
    )


@pytest.mark.parametrize(
    "public_endpoint",
    [
        None,
        "",
        "localhost:9000",
        "127.0.0.1:9000",
        "minio:9000",
        "172.18.0.2:9000",
        "host.docker.internal:9000",
        "https://objects.example.test",
        "objects.example.test/internal-path",
    ],
)
def test_minio_browser_endpoint_fails_closed_when_missing_or_internal(
    public_endpoint: str | None,
) -> None:
    with pytest.raises(ApiError) as exc_info:
        create_object_store(_minio_test_settings(public_endpoint))

    assert exc_info.value.status_code == 503
    assert exc_info.value.code == "OBJECT_STORE_UNAVAILABLE"
    assert exc_info.value.message == "Object storage is unavailable"


@pytest.mark.parametrize(
    "public_endpoint",
    ["localhost:9000", "127.0.0.1:9000", "minio:9000", "172.18.0.2:9000"],
)
def test_minio_browser_endpoint_allows_local_addresses_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch, public_endpoint: str
) -> None:
    from minio import Minio

    monkeypatch.setattr(Minio, "bucket_exists", lambda *_: True)
    store = MinioObjectStore(
        _minio_test_settings(public_endpoint, allow_local_endpoint=True)
    )

    assert store.presigned_get_url("documents/example.txt", expires=timedelta(minutes=5))


def _login(client: TestClient, settings: Settings, user_id: str, email: str, role: str) -> dict[str, str]:
    _seed_platform_user(settings, user_id, email, f"{user_id} name", "secret-pass", role)
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secret-pass"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['accessToken']}"}


def test_kb_crud_has_no_tenant(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        created = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "KB One"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert set(body) == {
            "id",
            "ownerUserId",
            "ownerUserName",
            "name",
            "description",
            "status",
            "indexStatus",
            "indexError",
            "indexWorkspace",
            "metadata",
            "createdAt",
            "updatedAt",
        }
        assert body["ownerUserId"] == "expert_user"
        assert body["ownerUserName"] == "expert_user name"
        assert body["status"] == "active"
        kb_id = body["id"]

        review = client.get(f"/api/v1/knowledge-bases/{kb_id}/index-review", headers=headers)
        assert review.status_code == 200, review.text
        assert review.json()["status"] == "not_required"
        assert review.json()["thresholdBytes"] == 5 * 1024 * 1024

        got = client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
        assert got.status_code == 200
        listed = client.get("/api/v1/knowledge-bases", headers=headers)
        assert listed.status_code == 200
        listed_item = next(item for item in listed.json()["items"] if item["id"] == kb_id)
        assert listed_item["ownerUserName"] == "expert_user name"

        patched = client.patch(
            f"/api/v1/knowledge-bases/{kb_id}", headers=headers, json={"name": "KB Renamed"}
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "KB Renamed"

        deleted = client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers).status_code == 404


def test_kb_archive_and_activate_lifecycle(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        created = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB Lifecycle"}
        )
        assert created.status_code == 201, created.text
        kb_id = created.json()["id"]
        assert created.json()["status"] == "active"

        # Archive flips status to archived and the response reflects it.
        archived = client.post(f"/api/v1/knowledge-bases/{kb_id}/archive", headers=headers)
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        # The default active-only list keeps archived bases out of Expert selectors, while the
        # management view can explicitly request archived or all non-deleted bases.
        listed = client.get("/api/v1/knowledge-bases", headers=headers)
        assert all(item["id"] != kb_id for item in listed.json()["items"])
        archived_list = client.get(
            "/api/v1/knowledge-bases", headers=headers, params={"status": "archived"}
        )
        assert [item["id"] for item in archived_list.json()["items"]] == [kb_id]
        all_list = client.get(
            "/api/v1/knowledge-bases", headers=headers, params={"status": "all"}
        )
        assert [item["id"] for item in all_list.json()["items"]] == [kb_id]
        assert (
            client.get(
                "/api/v1/knowledge-bases", headers=headers, params={"status": "invalid"}
            ).status_code
            == 422
        )
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers).status_code == 200

        # Writes are rejected while archived, and archiving again is a 409.
        rejected = client.patch(
            f"/api/v1/knowledge-bases/{kb_id}", headers=headers, json={"name": "Nope"}
        )
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "KB_ARCHIVED"
        approval = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/index-review/approve",
            headers=headers,
            json={"batchToken": "stale-token"},
        )
        assert approval.status_code == 409
        assert approval.json()["code"] == "KB_ARCHIVED"
        assert (
            client.post(f"/api/v1/knowledge-bases/{kb_id}/archive", headers=headers).status_code
            == 409
        )

        # Activate un-archives it (bypassing the write-gate) and writes work again.
        activated = client.post(f"/api/v1/knowledge-bases/{kb_id}/activate", headers=headers)
        assert activated.status_code == 200, activated.text
        assert activated.json()["status"] == "active"
        # Activating an active base is an idempotent no-op.
        assert (
            client.post(f"/api/v1/knowledge-bases/{kb_id}/activate", headers=headers).status_code
            == 200
        )
        patched = client.patch(
            f"/api/v1/knowledge-bases/{kb_id}", headers=headers, json={"name": "KB Renamed"}
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "KB Renamed"


def test_kb_delete_allows_archived_base(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        created = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Archived KB"}
        )
        assert created.status_code == 201, created.text
        kb_id = created.json()["id"]

        archived = client.post(f"/api/v1/knowledge-bases/{kb_id}/archive", headers=headers)
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"

        deleted = client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
        assert deleted.status_code == 204, deleted.text
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers).status_code == 404


def test_document_upload_flow(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Docs KB"}
        ).json()["id"]

        url_resp = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "guide.pdf", "mimeType": "application/pdf", "fileSizeBytes": 1024},
        )
        assert url_resp.status_code == 200, url_resp.text
        payload = url_resp.json()
        assert payload["objectKey"].startswith(f"knowledge-bases/{kb_id}/uploads/")
        assert "tenants/" not in payload["objectKey"]

        # Simulate the client PUT to MinIO with the declared size.
        store.put(payload["objectKey"], 1024)

        completed = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": payload["uploadSessionId"], "fileSizeBytes": 1024},
        )
        assert completed.status_code == 201, completed.text
        doc = completed.json()
        assert doc["fileType"] == "pdf"
        assert doc["parseStatus"] == "pending"

        listed = client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1

        dl = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{doc['id']}/download-url", headers=headers
        )
        assert dl.status_code == 200
        assert "?get" in dl.json()["downloadUrl"]
        assert "response-content-type=application/pdf" in dl.json()["downloadUrl"]
        assert "response-content-disposition=attachment" in dl.json()["downloadUrl"]
        assert "guide.pdf" in dl.json()["downloadUrl"]

        deleted = client.delete(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{doc['id']}", headers=headers
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers).json()["items"] == []


def test_document_batch_upload_flow(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Batch Docs KB"}
        ).json()["id"]

        url_resp = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-urls",
            headers=headers,
            json={
                "files": [
                    {"fileName": "guide.pdf", "mimeType": "application/pdf", "fileSizeBytes": 1024},
                    {"fileName": "notes.txt", "mimeType": "text/plain", "fileSizeBytes": 12},
                ]
            },
        )
        assert url_resp.status_code == 200, url_resp.text
        results = url_resp.json()["items"]
        assert len(results) == 2
        assert [r["status"] for r in results] == ["created", "created"]
        assert all(set(r) == {"fileName", "status", "upload", "error"} for r in results)
        uploads = [r["upload"] for r in results]
        assert all(upload["method"] == "PUT" for upload in uploads)
        assert all(upload["uploadUrl"] for upload in uploads)
        assert all(upload["uploadSessionId"] for upload in uploads)

        store.put(uploads[0]["objectKey"], 1024)
        store.put(uploads[1]["objectKey"], 12)

        completed = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-uploads",
            headers=headers,
            json={
                "items": [
                    {"uploadSessionId": uploads[0]["uploadSessionId"], "fileSizeBytes": 1024},
                    {"uploadSessionId": uploads[1]["uploadSessionId"], "fileSizeBytes": 12},
                ]
            },
        )
        assert completed.status_code == 200, completed.text
        items = completed.json()["items"]
        assert [item["status"] for item in items] == ["completed", "completed"]
        assert {item["document"]["fileName"] for item in items} == {"guide.pdf", "notes.txt"}

        listed = client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 2


def test_complete_uploads_is_non_atomic_and_reports_per_item_failures(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Partial KB"}
        ).json()["id"]

        url_resp = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-urls",
            headers=headers,
            json={"files": [{"fileName": "ok.pdf", "mimeType": "application/pdf", "fileSizeBytes": 8}]},
        )
        upload = url_resp.json()["items"][0]["upload"]
        store.put(upload["objectKey"], 8)

        # First item completes; second references an unknown session and must fail on its own
        # without aborting the first (the batch is non-atomic).
        completed = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-uploads",
            headers=headers,
            json={
                "items": [
                    {"uploadSessionId": upload["uploadSessionId"], "fileSizeBytes": 8},
                    {"uploadSessionId": "upl_does_not_exist", "fileSizeBytes": 8},
                ]
            },
        )
        assert completed.status_code == 200, completed.text
        items = completed.json()["items"]
        assert items[0]["status"] == "completed"
        assert items[0]["document"]["fileName"] == "ok.pdf"
        assert items[1]["status"] == "failed"
        assert items[1]["error"]["code"] == "UPLOAD_SESSION_NOT_FOUND"

        # The successful item was committed even though a sibling failed.
        listed = client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers)
        assert [doc["fileName"] for doc in listed.json()["items"]] == ["ok.pdf"]


def test_complete_upload_rejects_duplicate_content_and_removes_upload_object(
    tmp_path: Path,
) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Duplicate guard KB"}
        ).json()["id"]

        uploads = []
        for file_name in ("original.md", "copy.md"):
            upload = client.post(
                f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
                headers=headers,
                json={
                    "fileName": file_name,
                    "mimeType": "text/markdown",
                    "fileSizeBytes": 17,
                },
            ).json()
            store.put(upload["objectKey"], b"duplicate content")
            uploads.append(upload)

        original = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": uploads[0]["uploadSessionId"]},
        )
        duplicate = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": uploads[1]["uploadSessionId"]},
        )

        assert original.status_code == 201, original.text
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["code"] == "KB_DOCUMENT_DUPLICATE_CONTENT"
        assert duplicate.json()["details"] == {
            "duplicateDocumentId": original.json()["id"],
            "duplicateFileName": "original.md",
        }
        assert uploads[1]["objectKey"] in store.removed
        listed = client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers)
        assert [item["fileName"] for item in listed.json()["items"]] == ["original.md"]


def test_complete_upload_size_mismatch_is_rejected(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]
        payload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "a.txt", "fileSizeBytes": 100},
        ).json()

        # Client uploaded a larger object than declared.
        store.put(payload["objectKey"], 999)
        resp = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": payload["uploadSessionId"]},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "UPLOAD_SIZE_MISMATCH"
        # No document created, object removed.
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers).json()["items"] == []
        assert payload["objectKey"] in store.removed


@pytest.mark.asyncio
async def test_kb_delete_is_soft_and_gc_reclaims_objects(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "Doomed KB"}
        ).json()["id"]

        payload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "guide.pdf", "mimeType": "application/pdf", "fileSizeBytes": 512},
        ).json()
        object_key = payload["objectKey"]
        store.put(object_key, 512)
        completed = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": payload["uploadSessionId"], "fileSizeBytes": 512},
        )
        assert completed.status_code == 201, completed.text
        version_key = completed.json()["storageKey"]

        # Delete is a soft delete: the base disappears from all reads at once, but the object is
        # NOT reclaimed inline -- a hard cascade would have stranded it.
        assert client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers).status_code == 204
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers).status_code == 404
        assert all(
            item["id"] != kb_id
            for item in client.get("/api/v1/knowledge-bases", headers=headers).json()["items"]
        )
        assert version_key not in store.removed

        # GC reclaims the object, then hard-deletes the rows; a second pass is a no-op.
        from app.db import open_database_connection
        from app.services.document_service import DocumentService

        with open_database_connection(settings) as connection:
            service = DocumentService(connection, store, settings)
            assert await service.purge_deleted_knowledge_bases() == 1
            assert await service.purge_deleted_knowledge_bases() == 0
        assert version_key in store.removed


def test_complete_upload_concurrent_completion_maps_to_409(tmp_path: Path, monkeypatch) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]
        payload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "a.txt", "fileSizeBytes": 64},
        ).json()
        store.put(payload["objectKey"], 64)
        body = {"uploadSessionId": payload["uploadSessionId"], "fileSizeBytes": 64}

        first = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload", headers=headers, json=body
        )
        assert first.status_code == 201, first.text
        immutable_key = first.json()["storageKey"]

        # Simulate a second request that read the session as still `initiated` (the lost race):
        # it passes the status gate and collides on the documents primary key. The guard must
        # turn that into a 409, never a 500.
        from app.services.document_repository import DocumentRepository

        original_get_session = DocumentRepository.get_session

        def stale_get_session(self, session_id):
            session = original_get_session(self, session_id)
            if session is not None:
                session.status = "initiated"
            return session

        monkeypatch.setattr(DocumentRepository, "get_session", stale_get_session)
        store.put(payload["objectKey"], 64)
        second = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload", headers=headers, json=body
        )
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "UPLOAD_ALREADY_COMPLETED"
        # Still exactly one document.
        listed = client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers)
        assert len(listed.json()["items"]) == 1
        assert immutable_key in store.objects


def test_document_reads_do_not_require_object_store(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store
    with TestClient(app) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]
        payload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "a.txt", "fileSizeBytes": 32},
        ).json()
        store.put(payload["objectKey"], 32)
        doc_id = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": payload["uploadSessionId"], "fileSizeBytes": 32},
        ).json()["id"]

        # Object storage is now unavailable. Pure-DB routes must not depend on it.
        def broken_store() -> ObjectStore:
            raise RuntimeError("object store is down")

        app.dependency_overrides[get_object_store] = broken_store
        assert client.get(f"/api/v1/knowledge-bases/{kb_id}/docs", headers=headers).status_code == 200
        assert (
            client.get(f"/api/v1/knowledge-bases/{kb_id}/docs/{doc_id}", headers=headers).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v1/knowledge-bases/{kb_id}/docs/{doc_id}",
                headers=headers,
                json={"fileName": "b.txt"},
            ).status_code
            == 200
        )
        assert (
            client.delete(
                f"/api/v1/knowledge-bases/{kb_id}/docs/{doc_id}", headers=headers
            ).status_code
            == 204
        )

        # Routes that genuinely mint presigned URLs still surface the broken store.
        with pytest.raises(RuntimeError):
            client.post(
                f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
                headers=headers,
                json={"fileName": "c.txt", "fileSizeBytes": 10},
            )


def test_document_local_object_store_upload_and_download(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'kb.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
        object_storage_public_base_url="http://localhost:3000",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]

        upload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "local.txt", "mimeType": "text/plain", "fileSizeBytes": 11},
        )
        assert upload.status_code == 200, upload.text
        upload_body = upload.json()
        assert upload_body["uploadUrl"].startswith("/api/v1/storage/objects/")
        assert str(tmp_path) not in upload_body["uploadUrl"]

        put = client.put(
            upload_body["uploadUrl"],
            content=b"hello local",
            headers=upload_body["headers"],
        )
        assert put.status_code == 204, put.text

        completed = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": upload_body["uploadSessionId"]},
        )
        assert completed.status_code == 201, completed.text
        document_id = completed.json()["id"]

        download = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document_id}/download-url",
            headers=headers,
        )
        assert download.status_code == 200, download.text
        download_url = download.json()["downloadUrl"]
        assert download_url.startswith("/api/v1/storage/objects/")
        assert str(tmp_path) not in download_url

        content = client.get(download_url)
        assert content.status_code == 200
        assert content.headers["content-type"].startswith("text/plain")
        assert "attachment" in content.headers["content-disposition"]
        assert "local.txt" in content.headers["content-disposition"]
        assert content.content == b"hello local"


def test_document_local_object_store_rejects_bad_uploads(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'kb.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]

        upload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "small.txt", "mimeType": "text/plain", "fileSizeBytes": 5},
        ).json()

        wrong_type = client.put(
            upload["uploadUrl"],
            content=b"small",
            headers={"Content-Type": "application/json"},
        )
        assert wrong_type.status_code == 400
        assert wrong_type.json()["code"] == "OBJECT_CONTENT_TYPE_MISMATCH"

        too_large = client.put(
            upload["uploadUrl"],
            content=b"too large",
            headers=upload["headers"],
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "OBJECT_TOO_LARGE"


def test_document_upload_url_rejects_files_over_configured_limit(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    settings.object_storage_max_upload_bytes = 8
    store = FakeObjectStore()

    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]

        response = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "a.txt", "fileSizeBytes": 9},
        )
        assert response.status_code == 413, response.text
        assert response.json()["code"] == "OBJECT_TOO_LARGE"

        with open_database_connection(settings) as connection:
            row = connection.execute("select count(*) as count from document_upload_sessions").fetchone()
        assert row is not None
        assert row["count"] == 0


def test_upload_url_returns_503_when_object_store_unavailable(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    settings.object_storage_backend = "minio"
    app = create_app(settings)
    with TestClient(app) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]

        response = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "a.txt", "fileSizeBytes": 32},
        )
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["code"] == "OBJECT_STORE_UNAVAILABLE"
        assert "Object storage is unavailable" in body["message"]


def test_storage_gc_endpoint_reclaims_document_and_library_objects(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        _seed_tenant(settings)
        admin = _login(client, settings, "admin_user", "admin@example.com", "admin")
        tenant_user = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=admin, json={"name": "KB"}
        ).json()["id"]

        # (a) A soft-deleted document -> purgedDocuments.
        doc_payload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=admin,
            json={"fileName": "doc.txt", "fileSizeBytes": 16},
        ).json()
        store.put(doc_payload["objectKey"], 16)
        doc_id = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=admin,
            json={"uploadSessionId": doc_payload["uploadSessionId"], "fileSizeBytes": 16},
        ).json()["id"]
        client.delete(f"/api/v1/knowledge-bases/{kb_id}/docs/{doc_id}", headers=admin)

        # (b) An expired, never-completed upload session -> expiredSessions.
        orphan = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=admin,
            json={"fileName": "orphan.txt", "fileSizeBytes": 8},
        ).json()
        store.put(orphan["objectKey"], 8)
        # Force the session past its TTL without waiting on the clock.
        with open_database_connection(settings) as connection:
            connection.execute(
                "update document_upload_sessions set expires_at = ? where id = ?",
                ("2000-01-01T00:00:00+00:00", orphan["uploadSessionId"]),
            )
            connection.commit()

        # (c) A soft-deleted knowledge base -> purgedKnowledgeBases.
        kb2_id = client.post(
            "/api/v1/knowledge-bases", headers=admin, json={"name": "KB2"}
        ).json()["id"]
        kb2_doc = client.post(
            f"/api/v1/knowledge-bases/{kb2_id}/docs/upload-url",
            headers=admin,
            json={"fileName": "k2.txt", "fileSizeBytes": 4},
        ).json()
        store.put(kb2_doc["objectKey"], 4)
        client.post(
            f"/api/v1/knowledge-bases/{kb2_id}/docs/complete-upload",
            headers=admin,
            json={"uploadSessionId": kb2_doc["uploadSessionId"], "fileSizeBytes": 4},
        )
        client.delete(f"/api/v1/knowledge-bases/{kb2_id}", headers=admin)

        # (d) An expired, never-completed library upload session -> expiredLibrarySessions.
        library_orphan = client.post(
            "/api/v1/library/files/upload-url",
            headers=tenant_user,
            json={"fileName": "orphan.md", "mimeType": "text/markdown", "fileSizeBytes": 7},
        ).json()
        store.put(library_orphan["objectKey"], 7)
        with open_database_connection(settings) as connection:
            connection.execute(
                "update library_upload_sessions set expires_at = ? where id = ?",
                ("2000-01-01T00:00:00+00:00", library_orphan["uploadSessionId"]),
            )
            connection.commit()

        # (e) A soft-deleted library file -> purgedLibraryFiles.
        library_file, library_upload = _upload_library_file(
            client,
            tenant_user,
            file_name="deleted.md",
            content=b"delete me",
            mime_type="text/markdown",
            store=store,
        )
        client.delete(f"/api/v1/library/files/{library_file['id']}", headers=tenant_user)

        resp = client.post("/api/v1/ops/storage/gc", headers=admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "expiredSessions": 1,
            "purgedDocuments": 1,
            "purgedKnowledgeBases": 1,
            "expiredLibrarySessions": 1,
            "purgedLibraryFiles": 1,
            "purgedTemporaryFiles": 0,
        }
        for key in (
            doc_payload["objectKey"],
            orphan["objectKey"],
            kb2_doc["objectKey"],
            library_orphan["objectKey"],
            library_upload["objectKey"],
        ):
            assert key in store.removed

        # Idempotent: a second pass reclaims nothing.
        assert client.post("/api/v1/ops/storage/gc", headers=admin).json() == {
            "expiredSessions": 0,
            "purgedDocuments": 0,
            "purgedKnowledgeBases": 0,
            "expiredLibrarySessions": 0,
            "purgedLibraryFiles": 0,
            "purgedTemporaryFiles": 0,
        }


def test_storage_gc_keeps_rows_when_object_remove_fails(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        _seed_tenant(settings)
        admin = _login(client, settings, "admin_user", "admin@example.com", "admin")
        tenant_user = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=admin, json={"name": "KB"}
        ).json()["id"]

        deleted_doc = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=admin,
            json={"fileName": "deleted.txt", "fileSizeBytes": 16},
        ).json()
        store.put(deleted_doc["objectKey"], 16)
        completed_deleted_doc = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=admin,
            json={"uploadSessionId": deleted_doc["uploadSessionId"], "fileSizeBytes": 16},
        ).json()
        deleted_doc_id = completed_deleted_doc["id"]
        assert (
            client.delete(
                f"/api/v1/knowledge-bases/{kb_id}/docs/{deleted_doc_id}", headers=admin
            ).status_code
            == 204
        )

        orphan = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=admin,
            json={"fileName": "orphan.txt", "fileSizeBytes": 8},
        ).json()
        store.put(orphan["objectKey"], 8)
        with open_database_connection(settings) as connection:
            connection.execute(
                "update document_upload_sessions set expires_at = ? where id = ?",
                ("2000-01-01T00:00:00+00:00", orphan["uploadSessionId"]),
            )
            connection.commit()

        kb2_id = client.post(
            "/api/v1/knowledge-bases", headers=admin, json={"name": "KB2"}
        ).json()["id"]
        kb_doc = client.post(
            f"/api/v1/knowledge-bases/{kb2_id}/docs/upload-url",
            headers=admin,
            json={"fileName": "kb.txt", "fileSizeBytes": 4},
        ).json()
        store.put(kb_doc["objectKey"], 4)
        completed_kb_doc = client.post(
            f"/api/v1/knowledge-bases/{kb2_id}/docs/complete-upload",
            headers=admin,
            json={"uploadSessionId": kb_doc["uploadSessionId"], "fileSizeBytes": 4},
        ).json()
        assert client.delete(f"/api/v1/knowledge-bases/{kb2_id}", headers=admin).status_code == 204

        library_orphan = client.post(
            "/api/v1/library/files/upload-url",
            headers=tenant_user,
            json={"fileName": "orphan.md", "mimeType": "text/markdown", "fileSizeBytes": 7},
        ).json()
        store.put(library_orphan["objectKey"], 7)
        with open_database_connection(settings) as connection:
            connection.execute(
                "update library_upload_sessions set expires_at = ? where id = ?",
                ("2000-01-01T00:00:00+00:00", library_orphan["uploadSessionId"]),
            )
            connection.commit()

        library_file, library_upload = _upload_library_file(
            client,
            tenant_user,
            file_name="deleted.md",
            content=b"delete me",
            mime_type="text/markdown",
            store=store,
        )
        assert (
            client.delete(
                f"/api/v1/library/files/{library_file['id']}",
                headers=tenant_user,
            ).status_code
            == 200
        )

        store.fail_remove.update(
            {
                completed_deleted_doc["storageKey"],
                orphan["objectKey"],
                completed_kb_doc["storageKey"],
                library_orphan["objectKey"],
                library_upload["objectKey"],
            }
        )
        assert client.post("/api/v1/ops/storage/gc", headers=admin).json() == {
            "expiredSessions": 0,
            "purgedDocuments": 0,
            "purgedKnowledgeBases": 0,
            "expiredLibrarySessions": 0,
            "purgedLibraryFiles": 0,
            "purgedTemporaryFiles": 0,
        }

        with open_database_connection(settings) as connection:
            doc_row = connection.execute(
                "select id from documents where id = ?", (deleted_doc_id,)
            ).fetchone()
            session_row = connection.execute(
                "select status from document_upload_sessions where id = ?", (orphan["uploadSessionId"],)
            ).fetchone()
            kb_row = connection.execute(
                "select id from knowledge_bases where id = ?", (kb2_id,)
            ).fetchone()
            library_session_row = connection.execute(
                "select status from library_upload_sessions where id = ?",
                (library_orphan["uploadSessionId"],),
            ).fetchone()
            library_file_row = connection.execute(
                "select id from library_files where id = ?",
                (library_file["id"],),
            ).fetchone()
        assert doc_row is not None
        assert session_row["status"] == "initiated"
        assert kb_row is not None
        assert library_session_row["status"] == "initiated"
        assert library_file_row is not None

        store.fail_remove.clear()
        assert client.post("/api/v1/ops/storage/gc", headers=admin).json() == {
            "expiredSessions": 1,
            "purgedDocuments": 1,
            "purgedKnowledgeBases": 1,
            "expiredLibrarySessions": 1,
            "purgedLibraryFiles": 1,
            "purgedTemporaryFiles": 0,
        }


def test_sqlite_unique_violation_detection_is_specific() -> None:
    import sqlite3

    from app.services._sql import is_unique_violation

    assert is_unique_violation(sqlite3.IntegrityError("UNIQUE constraint failed: documents.id"))
    assert is_unique_violation(sqlite3.IntegrityError("PRIMARY KEY must be unique"))
    assert not is_unique_violation(sqlite3.IntegrityError("CHECK constraint failed: file_type"))
    assert not is_unique_violation(sqlite3.IntegrityError("FOREIGN KEY constraint failed"))


def test_storage_gc_endpoint_requires_system_ops(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        # `expert` authors knowledge bases but holds no system:ops permission.
        expert = _login(client, settings, "expert_user", "expert@example.com", "expert")
        resp = client.post("/api/v1/ops/storage/gc", headers=expert)
        assert resp.status_code == 403


def _library_test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'library.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )


def _library_headers(
    client: TestClient,
    settings: Settings,
    *,
    user_id: str,
    email: str,
) -> dict[str, str]:
    _seed_tenant_user(settings, user_id, email, f"{user_id} name", "secret-pass", "member")
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secret-pass", "tenantId": "tenant_default"},
    )
    assert login.status_code == 200, login.text
    return {
        "Authorization": f"Bearer {login.json()['accessToken']}",
        "x-tenant-id": "tenant_default",
    }


def _upload_library_file(
    client: TestClient,
    headers: dict[str, str],
    *,
    file_name: str,
    content: bytes,
    mime_type: str,
    store: FakeObjectStore | None = None,
    lifecycle: str = "permanent",
) -> tuple[dict, dict]:
    created = client.post(
        "/api/v1/library/files/upload-url",
        headers=headers,
        json={
            "fileName": file_name,
            "mimeType": mime_type,
            "fileSizeBytes": len(content),
        },
    )
    assert created.status_code == 200, created.text
    upload = created.json()
    if store is None:
        put = client.put(upload["uploadUrl"], headers=upload["headers"], content=content)
        assert put.status_code == 204, put.text
    else:
        store.put(upload["objectKey"], content, content_type=mime_type)

    completed = client.post(
        "/api/v1/library/files/complete-upload",
        headers=headers,
        json={"uploadSessionId": upload["uploadSessionId"], "lifecycle": lifecycle},
    )
    assert completed.status_code == 201, completed.text
    return completed.json(), upload


def test_library_upload_list_preview_download_and_delete(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        item, upload = _upload_library_file(
            client,
            headers,
            file_name="notes.md",
            content=b"# Hello\nbody",
            mime_type="text/markdown",
            store=store,
        )
        assert item["name"] == "notes.md"
        assert item["type"] == "file"
        assert item["sizeBytes"] == 12
        assert item["previewSupported"] is True
        file_id = item["id"]

        object_key = upload["objectKey"]
        assert object_key.startswith(f"library/users/tenant_user/{file_id}/")

        listed = client.get("/api/v1/library/files", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["id"] == file_id

        preview = client.get(f"/api/v1/library/files/{file_id}/preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["previewType"] == "text"
        assert preview.json()["content"] == "# Hello\nbody"

        download = client.get(f"/api/v1/library/files/{file_id}/download", headers=headers)
        assert download.status_code == 200
        assert download.json()["downloadUrl"].endswith("?disposition=attachment")

        deleted = client.delete(f"/api/v1/library/files/{file_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json() == {"id": file_id, "status": "deleted"}
        assert client.get("/api/v1/library/files", headers=headers).json()["items"] == []
        assert client.get(f"/api/v1/library/files/{file_id}/download", headers=headers).status_code == 404

        with open_database_connection(settings) as connection:
            row = connection.execute(
                "select deleted_at from library_files where id = ?",
                (file_id,),
            ).fetchone()
        assert row is not None
        assert row["deleted_at"] is not None
        assert object_key not in store.removed


def test_library_local_object_store_download_url_is_backend_controlled(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'library.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        item, _ = _upload_library_file(
            client,
            headers,
            file_name="notes.md",
            content=b"# Local",
            mime_type="text/markdown",
        )
        file_id = item["id"]

        download = client.get(f"/api/v1/library/files/{file_id}/download", headers=headers)
        assert download.status_code == 200
        download_url = download.json()["downloadUrl"]
        assert download_url.startswith(f"/api/v1/library/files/{file_id}/content")
        assert str(tmp_path) not in download_url

        assert client.get(download_url).status_code == 401
        content = client.get(download_url, headers=headers)
        assert content.status_code == 200
        assert content.content == b"# Local"


def test_library_presigned_upload_flow(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        created = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={
                "fileName": "notes.md",
                "mimeType": "text/markdown",
                "fileSizeBytes": 12,
                "contentHash": "client-declared-sha256",
            },
        )
        assert created.status_code == 200, created.text
        upload = created.json()
        assert upload["uploadUrl"].startswith("https://minio.test/expert-docs/library/")
        assert upload["headers"] == {"Content-Type": "text/markdown"}
        assert upload["objectKey"].startswith("library/users/tenant_user/")

        store.put(upload["objectKey"], b"# Hello\nbody", content_type="text/markdown")
        completed = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={
                "uploadSessionId": upload["uploadSessionId"],
                "contentHash": "different-client-declared-sha256",
            },
        )
        assert completed.status_code == 201, completed.text
        item = completed.json()
        assert item["id"] == upload["fileId"]
        assert item["name"] == "notes.md"
        assert item["sizeBytes"] == 12
        assert item["previewSupported"] is True

        preview = client.get(f"/api/v1/library/files/{item['id']}/preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["content"] == "# Hello\nbody"
        with open_database_connection(settings) as connection:
            file_row = connection.execute(
                "select content_hash from library_files where id = ?",
                (item["id"],),
            ).fetchone()
            session_row = connection.execute(
                "select content_hash from library_upload_sessions where id = ?",
                (upload["uploadSessionId"],),
            ).fetchone()
        assert file_row is not None
        assert file_row["content_hash"] is None
        assert session_row is not None
        assert session_row["content_hash"] is None


def test_library_local_object_store_presigned_upload(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'library.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        created = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={
                "fileName": "local.txt",
                "mimeType": "text/plain",
                "fileSizeBytes": 5,
            },
        )
        assert created.status_code == 200, created.text
        upload = created.json()
        assert upload["uploadUrl"].startswith("/api/v1/storage/objects/")
        assert str(tmp_path) not in upload["uploadUrl"]

        put = client.put(upload["uploadUrl"], headers=upload["headers"], content=b"hello")
        assert put.status_code == 204, put.text
        completed = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={"uploadSessionId": upload["uploadSessionId"]},
        )
        assert completed.status_code == 201, completed.text
        file_id = completed.json()["id"]

        download = client.get(f"/api/v1/library/files/{file_id}/download", headers=headers)
        assert download.status_code == 200
        content = client.get(download.json()["downloadUrl"], headers=headers)
        assert content.status_code == 200
        assert content.content == b"hello"


def test_library_complete_upload_size_mismatch_is_rejected(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        created = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={
                "fileName": "oversized.txt",
                "mimeType": "text/plain",
                "fileSizeBytes": 5,
            },
        )
        assert created.status_code == 200, created.text
        upload = created.json()
        store.put(upload["objectKey"], b"too large")

        completed = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={"uploadSessionId": upload["uploadSessionId"]},
        )
        assert completed.status_code == 400
        assert completed.json()["code"] == "LIBRARY_UPLOAD_SIZE_MISMATCH"
        assert upload["objectKey"] in store.removed
        assert client.get("/api/v1/library/files", headers=headers).json()["items"] == []


def test_library_files_are_isolated_by_current_user(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        alice = _library_headers(
            client,
            settings,
            user_id="alice",
            email="alice@example.com",
        )
        bob = _library_headers(
            client,
            settings,
            user_id="bob",
            email="bob@example.com",
        )

        item, _ = _upload_library_file(
            client,
            alice,
            file_name="private.txt",
            content=b"secret",
            mime_type="text/plain",
            store=store,
        )
        file_id = item["id"]

        assert client.get("/api/v1/library/files", headers=alice).json()["total"] == 1
        assert client.get("/api/v1/library/files", headers=bob).json()["total"] == 0
        assert client.get(f"/api/v1/library/files/{file_id}/download", headers=bob).status_code == 404
        assert client.delete(f"/api/v1/library/files/{file_id}", headers=bob).status_code == 404


def test_library_search_type_filter_and_image_preview_url(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        image, _ = _upload_library_file(
            client,
            headers,
            file_name="chart.png",
            content=b"\x89PNG\r\n\x1a\nimage",
            mime_type="image/png",
            store=store,
        )
        _upload_library_file(
            client,
            headers,
            file_name="report.pdf",
            content=b"%PDF-1.7",
            mime_type="application/pdf",
            store=store,
        )

        images = client.get("/api/v1/library/files", headers=headers, params={"type": "image"})
        assert images.status_code == 200
        assert [item["name"] for item in images.json()["items"]] == ["chart.png"]

        search = client.get("/api/v1/library/files", headers=headers, params={"keyword": "report"})
        assert search.status_code == 200
        assert [item["name"] for item in search.json()["items"]] == ["report.pdf"]

        preview = client.get(
            f"/api/v1/library/files/{image['id']}/preview",
            headers=headers,
        )
        assert preview.status_code == 200
        assert preview.json()["previewType"] == "url"
        assert preview.json()["url"].endswith("?disposition=inline")


def test_library_pdf_preview_returns_inline_pdf_url(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        item, _ = _upload_library_file(
            client,
            headers,
            file_name="report.pdf",
            content=b"%PDF-1.7",
            mime_type="application/pdf",
            store=store,
        )
        assert item["mimeType"] == "application/pdf"
        assert item["previewSupported"] is True

        listed = client.get("/api/v1/library/files", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["previewSupported"] is True

        preview = client.get(f"/api/v1/library/files/{item['id']}/preview", headers=headers)
        assert preview.status_code == 200
        body = preview.json()
        assert body["previewType"] == "url"
        assert body["mimeType"] == "application/pdf"
        assert body["url"].endswith("?disposition=inline")


def test_library_content_disposition_escapes_filename() -> None:
    from app.services.library_service import _inline_content_disposition

    header = _inline_content_disposition('a".pdf')
    assert header == 'inline; filename="a_.pdf"; filename*=UTF-8\'\'a%22.pdf'
    assert 'filename="a".pdf"' not in header


def test_library_preview_supported_is_derived_from_file_type_not_db_flag(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        item, _ = _upload_library_file(
            client,
            headers,
            file_name="legacy.pdf",
            content=b"%PDF-1.7",
            mime_type="application/pdf",
            store=store,
        )
        file_id = item["id"]

        with open_database_connection(settings) as connection:
            connection.execute(
                "update library_files set preview_supported = 0 where id = ?",
                (file_id,),
            )
            connection.commit()

        listed = client.get("/api/v1/library/files", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["previewSupported"] is True

        preview = client.get(f"/api/v1/library/files/{file_id}/preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["previewType"] == "url"


def test_library_docx_preview_extracts_text(tmp_path: Path) -> None:
    settings = _library_test_settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store

    docx = BytesIO()
    with ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Hello DOCX</w:t></w:r></w:p>
                <w:p><w:r><w:t>Second line</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )
    docx.seek(0)

    with TestClient(app) as client:
        _seed_tenant(settings)
        headers = _library_headers(
            client,
            settings,
            user_id="tenant_user",
            email="tenant@example.com",
        )

        item, _ = _upload_library_file(
            client,
            headers,
            file_name="proposal.docx",
            content=docx.getvalue(),
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            store=store,
        )
        assert item["previewSupported"] is True

        listed = client.get("/api/v1/library/files", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["previewSupported"] is True

        preview = client.get(f"/api/v1/library/files/{item['id']}/preview", headers=headers)
        assert preview.status_code == 200
        body = preview.json()
        assert body["previewType"] == "text"
        assert body["content"] == "Hello DOCX\nSecond line"


def test_upload_url_rejects_unsupported_type(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _login(client, settings, "expert_user", "expert@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=headers, json={"name": "KB"}
        ).json()["id"]
        resp = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=headers,
            json={"fileName": "malware.exe", "fileSizeBytes": 10},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "DOC_UNSUPPORTED_TYPE"


def test_kb_access_is_permission_based_not_owner_based(tmp_path: Path) -> None:
    settings = _kb_test_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        creator = _login(client, settings, "creator_user", "creator@example.com", "expert")
        other = _login(client, settings, "other_user", "other@example.com", "expert")
        kb_id = client.post(
            "/api/v1/knowledge-bases", headers=creator, json={"name": "Platform KB"}
        ).json()["id"]
        # Knowledge bases are platform-owned: any platform user holding kb:delete may delete
        # one, regardless of who created it. ownerUserId is attribution, not access control.
        resp = client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=other)
        assert resp.status_code == 204

# Streaming Markdown normalization ----------------------------------------------------

from app.services.chat_service import (  # noqa: E402
    _normalize_answer_markdown_delta,
    _SmoothTextBuffer,
)


def test_markdown_delta_skips_line_start_markers_on_midline_fragments() -> None:
    # A chunk that does not begin at a line start must not be reinterpreted as a heading
    # or list marker (e.g. "#5" must stay "#5", not become "# 5").
    assert _normalize_answer_markdown_delta("#5 wins", at_line_start=False) == "#5 wins"
    assert _normalize_answer_markdown_delta("#5 wins", at_line_start=True) == "# 5 wins"
    # Lines after an embedded newline are always genuine line starts.
    assert _normalize_answer_markdown_delta("tail #hi", at_line_start=False) == "tail #hi"
    assert _normalize_answer_markdown_delta("a\n#hi", at_line_start=False) == "a\n# hi"


def test_smooth_text_buffer_tracks_line_start() -> None:
    buf = _SmoothTextBuffer(max_chars=8, punctuation=False)
    # First chunk begins at a line start.
    assert buf.push("abcdefgh") == "abcdefgh"
    assert buf.chunk_at_line_start is True
    # The previous chunk had no trailing newline, so the next one is mid-line.
    assert buf.push("ijklmnop") == "ijklmnop"
    assert buf.chunk_at_line_start is False
    # A chunk that ends on a newline makes the following chunk a line start again.
    assert buf.push("qr\nstuvwx") == "qr\n"
    assert buf.flush() == "stuvwx"
    assert buf.chunk_at_line_start is True



def _chat_attachment_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'chat_attachments.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )


def _chat_attachment_login(client: TestClient, settings: Settings) -> dict[str, str]:
    _seed_tenant(settings)
    _seed_tenant_user(
        settings, "tenant_user", "tenant@example.com", "Tenant User", "tenant-secret", "member"
    )
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "tenant@example.com",
            "password": "tenant-secret",
            "tenantId": "tenant_default",
        },
    )
    assert login.status_code == 200, login.text
    return {
        "Authorization": f"Bearer {login.json()['accessToken']}",
        "x-tenant-id": "tenant_default",
    }


def test_library_temporary_upload_lifecycle_and_promote(tmp_path: Path) -> None:
    settings = _chat_attachment_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _chat_attachment_login(client, settings)

        # 1. Upload a temporary file through the unified library endpoint (unbound: no session yet).
        completed, _ = _upload_library_file(
            client,
            headers,
            file_name="report.pdf",
            mime_type="application/pdf",
            content=b"%PDF-1.7\n" + b"x" * 1015,
            store=store,
            lifecycle="temporary",
        )
        file_id = completed["id"]
        assert completed["lifecycle"] == "temporary"
        assert completed["expiresAt"] is not None

        # 2. It shows in the temporary (unbound) listing, not in the permanent library listing.
        pending = client.get("/api/v1/library/files?lifecycle=temporary", headers=headers)
        assert [item["id"] for item in pending.json()["items"]] == [file_id]
        library = client.get("/api/v1/library/files", headers=headers)
        assert file_id not in [item["id"] for item in library.json()["items"]]

        # 3. Promote it; it becomes a permanent library file with no byte copy.
        promoted = client.post(f"/api/v1/library/files/{file_id}/promote", headers=headers)
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["lifecycle"] == "permanent"

        # 4. Now in the library listing and gone from the temporary listing.
        assert file_id in [
            item["id"]
            for item in client.get("/api/v1/library/files", headers=headers).json()["items"]
        ]
        assert client.get(
            "/api/v1/library/files?lifecycle=temporary", headers=headers
        ).json()["items"] == []

        # 5. Re-promoting a now-permanent file is a 409.
        assert (
            client.post(f"/api/v1/library/files/{file_id}/promote", headers=headers).status_code
            == 409
        )


def test_library_permanent_upload_is_visible(tmp_path: Path) -> None:
    settings = _chat_attachment_settings(tmp_path)
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _chat_attachment_login(client, settings)
        completed, _ = _upload_library_file(
            client,
            headers,
            file_name="keep.png",
            mime_type="image/png",
            content=b"\x89PNG\r\n\x1a\n" + b"y" * 504,
            store=store,
            lifecycle="permanent",
        )
        assert completed["lifecycle"] == "permanent"
        assert completed["expiresAt"] is None
        library = client.get("/api/v1/library/files", headers=headers)
        assert completed["id"] in [item["id"] for item in library.json()["items"]]


def _chat_attachment_acp_app(settings: Settings, store: FakeObjectStore, fake_acp):
    app = create_app(settings)
    app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp
    app.dependency_overrides[get_object_store] = lambda: store
    return app


def _acp_attachment_settings(tmp_path: Path, name: str) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / name}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
        library_delivery_public_base_url="http://backend.test",
    )


def test_object_key_is_ascii_for_unicode_filename() -> None:
    # A non-ASCII object key forces \uXXXX escapes into the signed presigned-URL token; clients
    # that re-encode the URL strip the backslashes and break the signature (401). The storage key
    # must therefore stay ASCII while original_name keeps the real (unicode) display name.
    from app.services.library_service import _ascii_key_name, _object_key

    key = _object_key(
        "personal", "tenant_x", "user_y", "file_z", "ChatGPT-销售售前AI培训内容.pdf"
    )
    assert key.isascii()
    assert key == "library/users/user_y/file_z/ChatGPT-_AI.pdf"
    assert _ascii_key_name("报告.PDF") == "file.PDF"
    assert _ascii_key_name("无扩展名文件") == "file"
    assert _ascii_key_name("正常 file (1).docx") == "file_1.docx"


def test_turn_autobinds_attachment_delivers_url_and_records_provenance(tmp_path: Path) -> None:
    settings = _acp_attachment_settings(tmp_path, "turn_attach.sqlite3")
    store = FakeObjectStore()
    fake_acp = FakeAcpGatewayClient()
    with TestClient(_chat_attachment_acp_app(settings, store, fake_acp)) as client:
        headers = _chat_attachment_login(client, settings)
        session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

        # Upload a temporary file (unbound) via the unified library endpoint.
        content = b"The mitochondria is the powerhouse of the cell."
        file_id = _upload_library_file(
            client,
            headers,
            file_name="notes.txt",
            mime_type="text/plain",
            content=content,
            store=store,
            lifecycle="temporary",
        )[0]["id"]

        turn = client.post(
            f"/api/v1/chat/sessions/{session_id}/turns",
            headers=headers,
            json={"question": "Summarize this", "attachmentFileIds": [file_id]},
        )
        assert turn.status_code == 200, turn.text

        # §8.2 delivery: a short-lived Backend capability URL is appended to the runtime input,
        # never the file content; request_text stays the bare question.
        delivered_input = fake_acp.turn_calls[0]["input"]
        assert "Summarize this" in delivered_input
        assert "[Attachment: notes.txt (text/plain)]" in delivered_input
        assert "http://backend.test/api/v1/library/delivery/" in delivered_input
        # The raw content is never inlined.
        assert "powerhouse of the cell" not in delivered_input

        # Auto-bind: the file is now bound to this session and shows in its session listing.
        bound = client.get(
            f"/api/v1/library/files?lifecycle=temporary&sessionId={session_id}", headers=headers
        )
        assert file_id in [item["id"] for item in bound.json()["items"]]
        # The no-session listing still returns it: without sessionId it lists ALL of the caller's
        # temporary files (bound and unbound), not just the unbound ones.
        assert file_id in [
            item["id"]
            for item in client.get(
                "/api/v1/library/files?lifecycle=temporary", headers=headers
            ).json()["items"]
        ]
        # A different session's listing does not include it.
        other_session = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
        assert file_id not in [
            item["id"]
            for item in client.get(
                f"/api/v1/library/files?lifecycle=temporary&sessionId={other_session}",
                headers=headers,
            ).json()["items"]
        ]

        # §9 provenance snapshot on the turn.
        messages = client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", headers=headers
        ).json()["items"]
        snapshot = messages[0]["attachments"]
        assert len(snapshot) == 1
        assert snapshot[0]["fileId"] == file_id
        assert snapshot[0]["name"] == "notes.txt"
        assert messages[0]["requestText"] == "Summarize this"


def test_turn_rejects_attachment_bound_to_another_session(tmp_path: Path) -> None:
    settings = _acp_attachment_settings(tmp_path, "turn_attach_deny.sqlite3")
    store = FakeObjectStore()
    fake_acp = FakeAcpGatewayClient()
    with TestClient(_chat_attachment_acp_app(settings, store, fake_acp)) as client:
        headers = _chat_attachment_login(client, settings)
        s1 = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
        s2 = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
        file_id = _upload_library_file(
            client,
            headers,
            file_name="p.txt",
            mime_type="text/plain",
            content=b"private to session one",
            store=store,
            lifecycle="temporary",
        )[0]["id"]

        # First reference in s1 auto-binds the file to s1.
        first = client.post(
            f"/api/v1/chat/sessions/{s1}/turns",
            headers=headers,
            json={"question": "bind it", "attachmentFileIds": [file_id]},
        )
        assert first.status_code == 200, first.text

        # Referencing the s1-bound file from s2 is denied (§5), cleanly, before any runtime call.
        fake_acp.turn_calls.clear()
        denied = client.post(
            f"/api/v1/chat/sessions/{s2}/turns",
            headers=headers,
            json={"question": "leak it", "attachmentFileIds": [file_id]},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "LIBRARY_FILE_FORBIDDEN"
        assert fake_acp.turn_calls == []

        messages = client.get(
            f"/api/v1/chat/sessions/{s2}/messages", headers=headers
        ).json()["items"]
        assert len(messages) == 1
        assert messages[0]["requestText"] == "leak it"
        assert messages[0]["status"] == "failed"
        assert messages[0]["responseText"] == ""
        assert messages[0]["errorMessage"]


def test_temporary_file_gc_hard_deletes_expired(tmp_path: Path) -> None:
    # A negative retention window makes complete-upload mint an already-expired temporary file,
    # so the temporary-file GC pass has something to reclaim without sleeping.
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'temp_gc.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        chat_attachment_retention_seconds=-10,
    )
    store = FakeObjectStore()
    with TestClient(_kb_app(settings, store)) as client:
        headers = _chat_attachment_login(client, settings)
        upload = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={"fileName": "ephemeral.txt", "mimeType": "text/plain", "fileSizeBytes": 4},
        ).json()
        store.put(upload["objectKey"], b"test")
        file_id = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={"uploadSessionId": upload["uploadSessionId"], "lifecycle": "temporary"},
        ).json()["id"]
        object_key = upload["objectKey"]
        assert object_key in store.objects

        # The already-expired file is not listed (not-expired filter) but is GC-eligible.
        assert client.get(
            "/api/v1/library/files?lifecycle=temporary", headers=headers
        ).json()["items"] == []

        from app.services.library_repository import LibraryRepository
        from app.services.library_service import LibraryService

        with open_database_connection(settings) as connection:
            purged = LibraryService(connection, store, settings).purge_expired_temporary_files()
            assert purged == 1
            assert object_key not in store.objects
            assert object_key in store.removed
            assert LibraryRepository(connection).get_file(
                "tenant_user", "tenant_default", file_id
            ) is None
