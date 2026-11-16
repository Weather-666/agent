import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_expert_publication_service,
    get_object_store,
    get_skill_storage,
)
from app.core.config import Settings
from app.core.security import hash_password
from app.db import migrate_database, open_database_connection
from app.main import create_app
from app.services.audit_repository import AuditRepository
from app.services.expert_service import ExpertService
from app.services.object_store import ObjectStat, ObjectStore
from app.services.skill_storage import SkillStorage


ADMIN_PASSWORD = "audit-admin-secret"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'audit.sqlite3'}",
        jwt_secret="audit-test-secret-with-at-least-32-bytes",
        default_tenant_id="tenant_default",
    )


def _seed_user(
    settings: Settings,
    user_id: str,
    email: str,
    name: str,
    password: str,
    platform_role: str | None = None,
) -> None:
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values (?, ?, ?, ?, 'active')
            """,
            (user_id, email, hash_password(password), name),
        )
        if platform_role:
            connection.execute(
                """
                insert into platform_user_roles (id, user_id, role, assigned_by)
                values (?, ?, ?, ?)
                """,
                (f"role_{user_id}", user_id, platform_role, user_id),
            )
        connection.commit()


def _login(
    client: TestClient,
    email: str,
    password: str,
    *,
    request_id: str | None = None,
) -> tuple[dict[str, str], dict]:
    headers = {"X-Request-ID": request_id} if request_id else {}
    response = client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}, response.json()


def _audit_rows(settings: Settings, action: str | None = None) -> list[dict]:
    with open_database_connection(settings) as connection:
        sql = "select * from audit_events"
        params: tuple[str, ...] = ()
        if action:
            sql += " where action = ?"
            params = (action,)
        sql += " order by occurred_at asc, id asc"
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def test_audit_schema_is_idempotent_preserves_rows_and_is_postgres_shaped(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    migrate_database(settings)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into audit_events (
              id, request_id, occurred_at, category, action, operation_type,
              actor_user_id, actor_name, actor_email, actor_platform_roles,
              resource_type, resource_id, resource_name, changes, metadata, client_ip
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit_existing",
                "req_existing",
                datetime.now(timezone.utc).isoformat(),
                "plan",
                "plan.create",
                "create",
                "user_existing",
                "Existing Admin",
                "existing@example.com",
                '["admin"]',
                "plan",
                "plan_existing",
                "Existing Plan",
                "{}",
                "{}",
                None,
            ),
        )
        connection.commit()

    migrate_database(settings)

    with open_database_connection(settings) as connection:
        columns = {
            row["name"] for row in connection.execute("pragma table_info(audit_events)").fetchall()
        }
        indexes = {
            row["name"]
            for row in connection.execute("pragma index_list(audit_events)").fetchall()
        }
        preserved = connection.execute(
            "select resource_name from audit_events where id = 'audit_existing'"
        ).fetchone()

    assert preserved["resource_name"] == "Existing Plan"
    assert {"changes", "metadata", "client_ip", "actor_platform_roles"} <= columns
    assert not {
        "outcome",
        "result",
        "success",
        "failed",
        "http_status",
        "error_code",
        "error_message",
    }.intersection(columns)
    assert {
        "idx_audit_events_occurred",
        "idx_audit_events_category_occurred",
        "idx_audit_events_operation_occurred",
        "idx_audit_events_actor_occurred",
        "idx_audit_events_resource_occurred",
        "idx_audit_events_request",
    } <= indexes

    schema = (Path(__file__).parents[1] / "infra/sql/010_audit_events.sql").read_text(
        encoding="utf-8"
    )
    assert "jsonb" in schema
    assert "timestamptz" in schema
    assert "pragma" not in schema.casefold()
    assert "drop table" not in schema.casefold()


def test_audit_permissions_platform_login_and_request_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        _seed_user(
            settings,
            "admin_user",
            "admin@example.com",
            "Audit Admin",
            ADMIN_PASSWORD,
            "admin",
        )
        _seed_user(
            settings,
            "operator_user",
            "operator@example.com",
            "Audit Operator",
            "operator-secret",
            "operator",
        )
        _seed_user(
            settings,
            "expert_user",
            "expert@example.com",
            "Audit Expert",
            "expert-secret",
            "expert",
        )
        _seed_user(
            settings,
            "regular_user",
            "regular@example.com",
            "Regular User",
            "regular-secret",
        )

        admin_headers, admin_login = _login(
            client,
            "admin@example.com",
            ADMIN_PASSWORD,
            request_id="req_admin_login",
        )
        operator_headers, _ = _login(
            client,
            "operator@example.com",
            "operator-secret",
            request_id="x" * 200,
        )
        expert_headers, _ = _login(client, "expert@example.com", "expert-secret")
        _, _ = _login(client, "regular@example.com", "regular-secret")

        allowed = client.get("/api/v1/audit-events", headers=admin_headers)
        assert allowed.status_code == 200, allowed.text
        assert client.get("/api/v1/audit-events", headers=operator_headers).status_code == 403
        assert client.get("/api/v1/audit-events", headers=expert_headers).status_code == 403
        assert client.get("/api/v1/audit-events").status_code == 401

        login_items = [
            item
            for item in allowed.json()["items"]
            if item["action"] == "auth.platform_login"
        ]
        assert {item["actor"]["userId"] for item in login_items} == {
            "admin_user",
            "operator_user",
            "expert_user",
        }
        assert all(item["clientIp"] is None for item in login_items)
        assert all("result" not in item and "outcome" not in item for item in login_items)
        assert next(
            item for item in login_items if item["actor"]["userId"] == "admin_user"
        )["requestId"] == "req_admin_login"
        operator_event = next(
            item for item in login_items if item["actor"]["userId"] == "operator_user"
        )
        assert operator_event["requestId"].startswith("req_")
        assert operator_event["requestId"] != "x" * 200

        logout = client.post(
            "/api/v1/auth/logout",
            headers={"X-Request-ID": "req_admin_logout"},
            json={"refreshToken": admin_login["refreshToken"]},
        )
        assert logout.status_code == 204
        assert logout.headers["x-request-id"] == "req_admin_logout"

        auth_items = client.get(
            "/api/v1/audit-events",
            headers=admin_headers,
            params={"category": "auth"},
        ).json()["items"]
        assert auth_items
        assert all(item["action"] == "auth.platform_login" for item in auth_items)


def test_platform_management_actions_changes_snapshots_and_redaction(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage = FakeSkillStorage()
    app = create_app(settings)
    app.dependency_overrides[get_skill_storage] = lambda: storage

    class AuditOnlyPublicationService:
        async def change_status(
            self,
            principal,
            expert_id: str,
            status: str,
            *,
            request_id: str,
        ):
            with open_database_connection(settings) as connection:
                return ExpertService(connection).update_status(
                    principal,
                    expert_id,
                    status,
                    request_id=request_id,
                )

    app.dependency_overrides[get_expert_publication_service] = (
        AuditOnlyPublicationService
    )
    with TestClient(app) as client:
        _seed_user(
            settings,
            "admin_user",
            "admin@example.com",
            "Audit Admin",
            ADMIN_PASSWORD,
            "admin",
        )
        _seed_user(
            settings,
            "member_user",
            "member@example.com",
            "Tenant Member",
            "member-secret",
        )
        _seed_user(
            settings,
            "operator_user",
            "operator@example.com",
            "Audit Operator",
            "operator-secret",
            "operator",
        )
        headers, login_payload = _login(client, "admin@example.com", ADMIN_PASSWORD)
        operator_headers, _ = _login(client, "operator@example.com", "operator-secret")

        invited = client.post(
            "/api/v1/users/platform",
            headers={**headers, "X-Request-ID": "req_management"},
            json={
                "email": "invited@example.com",
                "name": "Invited User",
                "roles": ["expert"],
            },
        )
        assert invited.status_code == 201, invited.text
        invited_body = invited.json()
        invited_id = invited_body["id"]
        activation_token = invited_body["activationToken"]

        assert client.patch(
            f"/api/v1/users/{invited_id}",
            headers=headers,
            json={"name": "Renamed User"},
        ).status_code == 200
        assert client.post(
            f"/api/v1/rbac/platform/users/{invited_id}/roles",
            headers=headers,
            json={"role": "operator"},
        ).status_code == 204
        assert client.delete(
            f"/api/v1/rbac/platform/users/{invited_id}/roles/operator", headers=headers
        ).status_code == 204

        tenant = client.post(
            "/api/v1/tenants",
            headers=headers,
            json={"name": "Audit Tenant", "slug": "audit-tenant", "ownerUserId": invited_id},
        )
        assert tenant.status_code == 201, tenant.text
        tenant_id = tenant.json()["id"]
        assert client.patch(
            f"/api/v1/tenants/{tenant_id}",
            headers=headers,
            json={"name": "Renamed Tenant"},
        ).status_code == 200
        assert client.patch(
            f"/api/v1/tenants/{tenant_id}/status",
            headers=headers,
            json={"status": "disabled"},
        ).status_code == 200
        assert client.patch(
            f"/api/v1/tenants/{tenant_id}/subscription",
            headers=headers,
            json={"planId": "plan_business", "billingPeriod": "yearly", "status": "active"},
        ).status_code == 200
        assert client.post(
            f"/api/v1/tenants/{tenant_id}/members",
            headers=headers,
            json={"userId": "member_user", "role": "member"},
        ).status_code == 201
        assert client.patch(
            f"/api/v1/tenants/{tenant_id}/members/member_user",
            headers=headers,
            json={"role": "admin"},
        ).status_code == 200
        assert client.delete(
            f"/api/v1/tenants/{tenant_id}/members/member_user", headers=headers
        ).status_code == 204

        category = client.post(
            "/api/v1/expert-categories",
            headers=headers,
            json={"name": "Audit Category", "description": "Safe category summary"},
        )
        assert category.status_code == 201, category.text
        category_id = category.json()["id"]
        assert client.patch(
            f"/api/v1/expert-categories/{category_id}",
            headers=headers,
            json={"name": "Renamed Category"},
        ).status_code == 200
        expert = client.post(
            "/api/v1/experts",
            headers=headers,
            json={
                "name": "Audit Expert",
                "categoryId": category_id,
                "abilityIntro": "Safe public ability",
            },
        )
        assert expert.status_code == 201, expert.text
        expert_id = expert.json()["id"]
        assert client.patch(
            f"/api/v1/experts/{expert_id}",
            headers=headers,
            json={"name": "Renamed Expert", "tags": ["audit"]},
        ).status_code == 200
        assert client.patch(
            f"/api/v1/experts/{expert_id}/status",
            headers=headers,
            json={"status": "published"},
        ).status_code == 200

        created_plan = client.post(
            "/api/v1/plans",
            headers=headers,
            json={
                "code": "audit_pro",
                "name": "Audit Plan",
                "level": 21,
                "description": "Audit plan description",
            },
        )
        assert created_plan.status_code == 201, created_plan.text
        plan_id = created_plan.json()["id"]
        assert client.patch(
            f"/api/v1/plans/{plan_id}",
            headers=headers,
            json={"name": "Renamed Plan", "upgradeRules": {"safeRule": True}},
        ).status_code == 200
        assert client.put(
            f"/api/v1/plans/{plan_id}/prices",
            headers=headers,
            json={
                "items": [
                    {
                        "billingPeriod": "monthly",
                        "currency": "CNY",
                        "amountCents": 9900,
                    }
                ]
            },
        ).status_code == 200
        assert client.put(
            f"/api/v1/plans/{plan_id}/entitlements",
            headers=headers,
            json={
                "monthlyCreditLimit": 10,
                "allExperts": False,
                "seatLimit": 1,
                "singleTurnTokenLimit": None,
                "modelTiers": ["core"],
                "features": {"safeFeature": True},
            },
        ).status_code == 200
        assert client.put(
            f"/api/v1/plans/{plan_id}/experts",
            headers=headers,
            json={"expertIds": [expert_id]},
        ).status_code == 200

        skill_zip = _skill_zip()
        created_skill = client.post(
            "/api/v1/skills",
            headers=headers,
            data={"slug": "audit-skill"},
            files={"file": ("audit-skill.zip", skill_zip, "application/zip")},
        )
        assert created_skill.status_code == 201, created_skill.text
        assert client.put(
            "/api/v1/skills/audit-skill",
            headers=headers,
            json={"version": "2.0", "tags": ["updated"]},
        ).status_code == 200
        assert client.delete(
            "/api/v1/skills/audit-skill", headers=headers, params={"delete_files": True}
        ).status_code == 204

        assert client.delete(f"/api/v1/plans/{plan_id}", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/experts/{expert_id}", headers=headers).status_code == 204
        assert client.delete(
            f"/api/v1/expert-categories/{category_id}", headers=headers
        ).status_code == 204
        assert client.patch(
            f"/api/v1/users/{invited_id}/status",
            headers=headers,
            json={"status": "disabled"},
        ).status_code == 200

        action_set = {row["action"] for row in _audit_rows(settings)}
        assert {
            "platform_user.invite",
            "user.update",
            "user.status_change",
            "platform_role.grant",
            "platform_role.revoke",
            "tenant.create",
            "tenant.update",
            "tenant.status_change",
            "tenant.subscription_change",
            "tenant_member.add",
            "tenant_member.role_change",
            "tenant_member.remove",
            "expert_category.create",
            "expert_category.update",
            "expert_category.delete",
            "expert.create",
            "expert.update",
            "expert.status_change",
            "expert.delete",
            "plan.create",
            "plan.update",
            "plan.prices_replace",
            "plan.entitlements_replace",
            "plan.experts_replace",
            "plan.delete",
            "skill.create",
            "skill.update",
            "skill.delete",
        } <= action_set

        plan_update = _audit_rows(settings, "plan.update")[0]
        plan_changes = json.loads(plan_update["changes"])
        assert plan_changes["name"] == {"before": "Audit Plan", "after": "Renamed Plan"}
        assert plan_changes["upgradeRulesChanged"] == {"before": False, "after": True}
        plan_delete = _audit_rows(settings, "plan.delete")[0]
        assert plan_delete["resource_name"] == "Renamed Plan"
        assert json.loads(plan_delete["metadata"])["code"] == "audit_pro"

        plan_event_count = len(_audit_rows(settings, "plan.create"))
        assert client.post(
            "/api/v1/plans",
            headers=headers,
            json={"code": "bad", "name": "Invalid", "level": 0, "description": "bad"},
        ).status_code == 422
        assert client.patch(
            "/api/v1/plans/plan_missing", headers=headers, json={"name": "Missing"}
        ).status_code == 404
        assert client.delete("/api/v1/plans/plan_free", headers=headers).status_code == 409
        assert client.post(
            "/api/v1/plans",
            headers=operator_headers,
            json={"code": "forbidden", "name": "Forbidden", "level": 30, "description": "x"},
        ).status_code == 403
        assert len(_audit_rows(settings, "plan.create")) == plan_event_count

        raw_audit = json.dumps(_audit_rows(settings), ensure_ascii=False)
        assert ADMIN_PASSWORD not in raw_audit
        assert login_payload["accessToken"] not in raw_audit
        assert login_payload["refreshToken"] not in raw_audit
        assert activation_token not in raw_audit
        assert "DO_NOT_AUDIT_SKILL_BODY" not in raw_audit


def test_document_batch_logs_only_completed_items_and_preserves_delete_snapshots(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    store = FakeObjectStore()
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store
    with TestClient(app) as client:
        _seed_user(
            settings,
            "admin_user",
            "admin@example.com",
            "Audit Admin",
            ADMIN_PASSWORD,
            "admin",
        )
        headers, _ = _login(client, "admin@example.com", ADMIN_PASSWORD)
        kb = client.post(
            "/api/v1/knowledge-bases",
            headers=headers,
            json={"name": "Document Audit KB"},
        )
        assert kb.status_code == 201, kb.text
        kb_id = kb.json()["id"]

        uploads = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-urls",
            headers=headers,
            json={
                "files": [
                    {"fileName": "success-1.txt", "mimeType": "text/plain", "fileSizeBytes": 4},
                    {"fileName": "success-2.txt", "mimeType": "text/plain", "fileSizeBytes": 3},
                    {"fileName": "failed.txt", "mimeType": "text/plain", "fileSizeBytes": 5},
                ]
            },
        )
        assert uploads.status_code == 200, uploads.text
        upload_items = uploads.json()["items"]
        upload_specs = [item["upload"] for item in upload_items]
        assert _audit_rows(settings, "document.upload_completed") == []
        store.put(upload_specs[0]["objectKey"], b"done")
        store.put(upload_specs[1]["objectKey"], b"yes")

        batch = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-uploads",
            headers={**headers, "X-Request-ID": "req_document_batch"},
            json={
                "items": [
                    {"uploadSessionId": upload_specs[0]["uploadSessionId"]},
                    {"uploadSessionId": upload_specs[1]["uploadSessionId"]},
                    {"uploadSessionId": upload_specs[2]["uploadSessionId"]},
                ]
            },
        )
        assert batch.status_code == 200, batch.text
        assert [item["status"] for item in batch.json()["items"]] == [
            "completed",
            "completed",
            "failed",
        ]
        document = batch.json()["items"][0]["document"]

        upload_events = _audit_rows(settings, "document.upload_completed")
        assert len(upload_events) == 2
        assert {event["request_id"] for event in upload_events} == {"req_document_batch"}
        assert document["id"] in {event["resource_id"] for event in upload_events}
        assert all(event["client_ip"] is None for event in upload_events)
        assert "signed.local" not in json.dumps(upload_events)

        replacement_body = b"replacement"
        replacement_upload = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document['id']}/upload-url",
            headers=headers,
            json={
                "fileName": "success-1.txt",
                "mimeType": "text/plain",
                "fileSizeBytes": len(replacement_body),
            },
        )
        assert replacement_upload.status_code == 200, replacement_upload.text
        replacement_session = replacement_upload.json()
        store.put(replacement_session["objectKey"], replacement_body)
        wrong_endpoint = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=headers,
            json={"uploadSessionId": replacement_session["uploadSessionId"]},
        )
        assert wrong_endpoint.status_code == 400, wrong_endpoint.text
        replacement = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document['id']}/complete-upload",
            headers={**headers, "X-Request-ID": "req_document_replace"},
            json={"uploadSessionId": replacement_session["uploadSessionId"]},
        )
        assert replacement.status_code == 200, replacement.text
        assert replacement.json()["id"] == document["id"]
        replace_events = _audit_rows(settings, "document.source_replaced")
        assert len(replace_events) == 1
        assert replace_events[0]["request_id"] == "req_document_replace"
        replace_metadata = json.loads(replace_events[0]["metadata"])
        assert replace_metadata["previousSourceSha"] != replace_metadata["sourceSha"]

        secret_metadata_value = "https://signed.example.test/private?signature=DO_NOT_STORE"
        updated = client.patch(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document['id']}",
            headers=headers,
            json={
                "fileName": "renamed.txt",
                "metadata": {"sourceUrl": secret_metadata_value},
            },
        )
        assert updated.status_code == 200, updated.text
        assert client.delete(
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document['id']}", headers=headers
        ).status_code == 204
        assert client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers).status_code == 204

        document_update = _audit_rows(settings, "document.update")[0]
        assert secret_metadata_value not in document_update["changes"]
        assert json.loads(document_update["changes"])["metadataChanged"] == {
            "before": False,
            "after": True,
        }
        document_delete = _audit_rows(settings, "document.delete")[0]
        kb_delete = _audit_rows(settings, "knowledge_base.delete")[0]
        assert document_delete["resource_name"] == "renamed.txt"
        assert kb_delete["resource_name"] == "Document Audit KB"
        assert store.last_presigned_url not in json.dumps(_audit_rows(settings))


def test_audit_query_filters_time_sort_pagination_and_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        _seed_user(
            settings,
            "admin_user",
            "admin@example.com",
            "Audit Admin",
            ADMIN_PASSWORD,
            "admin",
        )
        headers, _ = _login(client, "admin@example.com", ADMIN_PASSWORD)
        started = datetime.now(timezone.utc) - timedelta(seconds=1)
        first = client.post(
            "/api/v1/plans",
            headers={**headers, "X-Request-ID": "req_query_create"},
            json={"code": "query_plan", "name": "Searchable Plan", "level": 25, "description": "x"},
        )
        assert first.status_code == 201, first.text
        plan_id = first.json()["id"]
        assert client.patch(
            f"/api/v1/plans/{plan_id}",
            headers={**headers, "X-Request-ID": "req_query_update"},
            json={"name": "Searchable Plan Updated"},
        ).status_code == 200
        ended = datetime.now(timezone.utc) + timedelta(seconds=1)

        by_category = client.get(
            "/api/v1/audit-events",
            headers=headers,
            params={"category": "plan"},
        )
        assert by_category.status_code == 200, by_category.text
        assert [item["action"] for item in by_category.json()["items"]] == [
            "plan.update",
            "plan.create",
        ]

        common = {
            "category": "plan",
            "actorId": "admin_user",
            "resourceType": "plan",
            "resourceId": plan_id,
            "search": "Searchable",
            "from": started.isoformat(),
            "to": ended.isoformat(),
        }
        filtered = client.get("/api/v1/audit-events", headers=headers, params=common)
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["total"] == 2
        only_update = client.get(
            "/api/v1/audit-events",
            headers=headers,
            params={**common, "operationType": "update"},
        )
        assert only_update.json()["total"] == 1
        assert only_update.json()["items"][0]["action"] == "plan.update"

        page = client.get(
            "/api/v1/audit-events",
            headers=headers,
            params={"category": "plan", "page": 2, "pageSize": 1},
        )
        assert page.json()["total"] == 2
        assert page.json()["page"] == 2
        assert page.json()["pageSize"] == 1
        assert page.json()["items"][0]["action"] == "plan.create"
        assert client.get(
            "/api/v1/audit-events", headers=headers, params={"pageSize": 101}
        ).status_code == 422
        invalid_range = client.get(
            "/api/v1/audit-events",
            headers=headers,
            params={"from": ended.isoformat(), "to": started.isoformat()},
        )
        assert invalid_range.status_code == 400
        assert invalid_range.json()["code"] == "AUDIT_TIME_RANGE_INVALID"


def test_business_write_rolls_back_when_audit_insert_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        _seed_user(
            settings,
            "admin_user",
            "admin@example.com",
            "Audit Admin",
            ADMIN_PASSWORD,
            "admin",
        )
        headers, _ = _login(client, "admin@example.com", ADMIN_PASSWORD)
        before = len(_audit_rows(settings, "plan.create"))

        def fail_insert(self, event):
            raise RuntimeError("audit persistence failed")

        monkeypatch.setattr(AuditRepository, "insert", fail_insert)
        response = client.post(
            "/api/v1/plans",
            headers=headers,
            json={
                "code": "rolled_back",
                "name": "Rolled Back Plan",
                "level": 41,
                "description": "must not commit",
            },
        )
        assert response.status_code == 500

        with open_database_connection(settings) as connection:
            plan = connection.execute(
                "select id from plans where code = 'rolled_back'"
            ).fetchone()
        assert plan is None
        assert len(_audit_rows(settings, "plan.create")) == before


class FakeObjectStore(ObjectStore):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.last_presigned_url = ""

    @property
    def bucket(self) -> str:
        return "audit-docs"

    def presigned_put_url(
        self,
        object_key,
        *,
        expires,
        content_type=None,
        content_length=None,
    ) -> str:
        self.last_presigned_url = (
            f"https://signed.local/{object_key}?signature=DO_NOT_STORE_SIGNED_URL"
        )
        return self.last_presigned_url

    def presigned_get_url(self, object_key, *, expires, response_headers=None) -> str:
        return f"https://signed.local/{object_key}?download=DO_NOT_STORE"

    def stat(self, object_key: str) -> ObjectStat:
        if object_key not in self.objects:
            from app.core.errors import ApiError

            raise ApiError(404, "DOC_OBJECT_NOT_FOUND", "Uploaded object not found")
        return ObjectStat(size=len(self.objects[object_key]), etag="fake-etag")

    def put(self, object_key: str, data: bytes, *, content_type=None) -> None:
        self.objects[object_key] = data

    def read(self, object_key: str, *, max_bytes=None) -> bytes:
        return self.objects[object_key]

    def remove(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


class FakeSkillStorage(SkillStorage):
    def __init__(self) -> None:
        self.files: dict[str, dict[str, bytes]] = {}

    def uri_for(self, slug: str) -> str:
        return f"memory://skills/{slug}"

    def put_files(self, slug: str, files: dict[str, bytes]) -> str:
        self.files[slug] = files
        return self.uri_for(slug)

    def get_file(self, slug: str, path: str) -> bytes:
        return self.files[slug][path]

    def delete_skill(self, slug: str) -> None:
        self.files.pop(slug, None)


def _skill_zip() -> bytes:
    content = BytesIO()
    with ZipFile(content, "w") as archive:
        archive.writestr(
            "SKILL.md",
            """---
name: Audit Skill
description: Safe skill description
version: 1.0
allowed-tools:
  - search
tags:
  - audit
---
DO_NOT_AUDIT_SKILL_BODY
""",
        )
        archive.writestr("scripts/run.py", "print('DO_NOT_AUDIT_SKILL_BODY')\n")
    return content.getvalue()
