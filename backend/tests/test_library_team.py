from __future__ import annotations

import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_acp_gateway_client, get_object_store
from app.core.config import Settings
from app.core.errors import ApiError
from app.db import migrate_database, open_database_connection
from app.domain.auth import Principal
from app.domain.library import LibraryUploadUrlRequest
from app.main import create_app
from app.services.library_access_service import LibraryAccessService
from app.services.library_service import (
    LibraryService,
    _validate_actual_format,
    _validate_declared_format,
)
from test_app import FakeAcpGatewayClient, FakeObjectStore, _seed_platform_user, _seed_tenant_user


def _settings(tmp_path: Path, name: str = "library-team.sqlite3") -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / name}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        acp_gateway_base_url="http://gateway.test",
        acp_route_prefix="/acp",
        acp_default_cwd=str(tmp_path / "acp-workspace"),
        library_delivery_public_base_url="http://backend.test",
    )


def _app(settings: Settings, store: FakeObjectStore, fake_acp=None):
    app = create_app(settings)
    app.dependency_overrides[get_object_store] = lambda: store
    if fake_acp is not None:
        app.dependency_overrides[get_acp_gateway_client] = lambda: fake_acp
    return app


def _seed_team(
    settings: Settings,
    team_id: str,
    members: list[tuple[str, str, str]],
    *,
    business_status: str = "active",
) -> None:
    for user_id, email, _ in members:
        _seed_tenant_user(settings, user_id, email, user_id, "secret-pass", "member")
    now = datetime.now(timezone.utc)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into tenants (id, type, name, slug, status)
            values (?, 'team', ?, ?, 'active')
            """,
            (team_id, f"{team_id} name", f"{team_id}-slug"),
        )
        for index, (user_id, _, role) in enumerate(members):
            connection.execute(
                """
                insert into tenant_members (id, tenant_id, user_id, role)
                values (?, ?, ?, ?)
                """,
                (f"member_{team_id}_{index}", team_id, user_id, role),
            )
        period_end = (
            now + timedelta(days=30) if business_status == "active" else now - timedelta(days=1)
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period,
              current_period_start, current_period_end
            ) values (?, ?, 'plan_business', ?, 'yearly', ?, ?)
            """,
            (
                f"subscription_{team_id}_business",
                team_id,
                business_status,
                (now - timedelta(days=2)).isoformat(),
                period_end.isoformat(),
            ),
        )
        connection.execute(
            """
            insert into team_library_entitlement_history (tenant_id, max_quota_bytes)
            values (?, ?)
            on conflict (tenant_id) do nothing
            """,
            (team_id, 20 * 1024**3),
        )
        connection.commit()


def _login(client: TestClient, team_id: str, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secret-pass", "tenantId": team_id},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['accessToken']}",
        "x-tenant-id": team_id,
    }


def _personal_headers(
    client: TestClient, settings: Settings, user_id: str, email: str
) -> dict[str, str]:
    _seed_tenant_user(settings, user_id, email, user_id, "secret-pass", "member")
    headers = _login(client, "tenant_default", email)
    assert (
        client.get("/api/v1/plan-market/current-subscription", headers=headers).status_code == 200
    )
    return headers


def _set_personal_quota(settings: Settings, quota: int) -> None:
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            update plans
            set entitlements = json_set(entitlements, '$.personalLibraryQuotaBytes', ?)
            where id = 'plan_free'
            """,
            (quota,),
        )
        connection.commit()


def _upload(
    client: TestClient,
    store: FakeObjectStore,
    headers: dict[str, str],
    *,
    name: str,
    content: bytes,
    space_type: str = "personal",
    mime_type: str = "text/plain",
) -> tuple[dict, dict]:
    created = client.post(
        "/api/v1/library/files/upload-url",
        headers=headers,
        json={
            "fileName": name,
            "mimeType": mime_type,
            "fileSizeBytes": len(content),
            "spaceType": space_type,
        },
    )
    assert created.status_code == 200, created.text
    upload = created.json()
    store.put(upload["objectKey"], content, content_type=mime_type)
    completed = client.post(
        "/api/v1/library/files/complete-upload",
        headers=headers,
        json={"uploadSessionId": upload["uploadSessionId"]},
    )
    assert completed.status_code == 201, completed.text
    return completed.json(), upload


def _delivery_url(
    client: TestClient,
    fake_acp: FakeAcpGatewayClient,
    headers: dict[str, str],
    file_id: str,
) -> str:
    session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
    turn = client.post(
        f"/api/v1/chat/sessions/{session_id}/turns",
        headers=headers,
        json={"question": "read attachment", "attachmentFileIds": [file_id]},
    )
    assert turn.status_code == 200, turn.text
    match = re.search(
        r"http://backend\.test/api/v1/library/delivery/[^\s]+", fake_acp.turn_calls[-1]["input"]
    )
    assert match is not None
    return match.group(0)


def _downgrade_to_free(settings: Settings, team_id: str) -> None:
    now = datetime.now(timezone.utc)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            update subscriptions set status = 'expired', current_period_end = ?, updated_at = ?
            where tenant_id = ? and plan_id = 'plan_business'
            """,
            ((now - timedelta(seconds=1)).isoformat(), now.isoformat(), team_id),
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period, current_period_start
            ) values (?, ?, 'plan_free', 'active', 'free', ?)
            """,
            (f"subscription_{team_id}_free", team_id, now.isoformat()),
        )
        connection.commit()


def _renew_business(settings: Settings, team_id: str) -> None:
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period,
              current_period_start, current_period_end
            ) values (?, ?, 'plan_business', 'active', 'yearly', ?, ?)
            """,
            (
                f"subscription_{team_id}_renewal",
                team_id,
                now.isoformat(),
                (now + timedelta(days=365)).isoformat(),
            ),
        )
        connection.commit()


def test_personal_quota_reservation_failure_and_delete_release(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "quota.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        headers = _personal_headers(client, settings, "quota_user", "quota@example.com")
        _set_personal_quota(settings, 8)

        first = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={"fileName": "first.txt", "mimeType": "text/plain", "fileSizeBytes": 5},
        )
        assert first.status_code == 200
        spaces = client.get("/api/v1/library/spaces", headers=headers).json()["items"]
        assert spaces[0]["quotaBytes"] == 8
        assert spaces[0]["reservedBytes"] == 5
        denied = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={"fileName": "second.txt", "mimeType": "text/plain", "fileSizeBytes": 4},
        )
        assert denied.status_code == 413
        assert denied.json()["code"] == "LIBRARY_QUOTA_EXCEEDED"

        upload = first.json()
        store.put(upload["objectKey"], b"sixsix")
        mismatch = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={"uploadSessionId": upload["uploadSessionId"]},
        )
        assert mismatch.status_code == 400
        assert (
            client.get("/api/v1/library/spaces", headers=headers).json()["items"][0][
                "reservedBytes"
            ]
            == 0
        )

        item, _ = _upload(client, store, headers, name="valid.txt", content=b"12345")
        assert (
            client.get("/api/v1/library/spaces", headers=headers).json()["items"][0]["usedBytes"]
            == 5
        )
        assert (
            client.delete(f"/api/v1/library/files/{item['id']}", headers=headers).status_code == 200
        )
        assert (
            client.get("/api/v1/library/spaces", headers=headers).json()["items"][0]["usedBytes"]
            == 0
        )


def test_complete_upload_rechecks_current_quota_and_cleans_reservation(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "quota-change.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        headers = _personal_headers(
            client, settings, "quota_change_user", "quota-change@example.com"
        )
        created = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={"fileName": "reserved.txt", "mimeType": "text/plain", "fileSizeBytes": 8},
        )
        assert created.status_code == 200, created.text
        upload = created.json()
        store.put(upload["objectKey"], b"reserved", content_type="text/plain")

        _set_personal_quota(settings, 0)

        rejected = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={"uploadSessionId": upload["uploadSessionId"]},
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["code"] == "LIBRARY_QUOTA_CHANGED"
        assert upload["objectKey"] not in store.contents
        assert upload["objectKey"] in store.removed
        with open_database_connection(settings) as connection:
            assert connection.execute("select count(*) from library_files").fetchone()[0] == 0
            usage = connection.execute(
                """
                select used_bytes, reserved_bytes
                from library_space_usage
                where space_type = 'personal' and owner_key = 'quota_change_user'
                """
            ).fetchone()
            session = connection.execute(
                "select status from library_upload_sessions where id = ?",
                (upload["uploadSessionId"],),
            ).fetchone()
        assert tuple(usage) == (0, 0)
        assert session["status"] == "failed"


def test_personal_quota_reservation_is_atomic_under_concurrency(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "quota-concurrency.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        headers = _personal_headers(
            client, settings, "quota_concurrent_user", "quota-concurrent@example.com"
        )
        _set_personal_quota(settings, 8)

        principal = Principal(
            user_id="quota_concurrent_user",
            email="quota-concurrent@example.com",
            active_tenant_id="tenant_default",
        )

        def allocate(index: int) -> str:
            try:
                with open_database_connection(settings) as connection:
                    LibraryService(connection, store, settings).create_upload_url(
                        principal,
                        LibraryUploadUrlRequest(
                            fileName=f"concurrent-{index}.txt",
                            mimeType="text/plain",
                            fileSizeBytes=5,
                        ),
                    )
                return "created"
            except ApiError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(allocate, range(2)))
        assert sorted(outcomes) == ["LIBRARY_QUOTA_EXCEEDED", "created"]
        spaces = client.get("/api/v1/library/spaces", headers=headers).json()["items"]
        assert spaces[0]["reservedBytes"] == 5


def test_name_suffix_and_rename_conflict(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "names.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        _seed_tenant_user(
            settings, "name_user", "names@example.com", "Names", "secret-pass", "member"
        )
        headers = _login(client, "tenant_default", "names@example.com")
        first, _ = _upload(client, store, headers, name="notes.txt", content=b"one")
        second_created = client.post(
            "/api/v1/library/files/upload-url",
            headers=headers,
            json={"fileName": "notes.txt", "mimeType": "text/plain", "fileSizeBytes": 3},
        )
        assert second_created.json()["nameConflict"] is True
        assert second_created.json()["suggestedName"] == "notes (1).txt"
        second_upload = second_created.json()
        store.put(second_upload["objectKey"], b"two")
        second = client.post(
            "/api/v1/library/files/complete-upload",
            headers=headers,
            json={"uploadSessionId": second_upload["uploadSessionId"]},
        ).json()
        assert second["name"] == "notes (1).txt"

        conflict = client.patch(
            f"/api/v1/library/files/{second['id']}", headers=headers, json={"name": "notes.txt"}
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "LIBRARY_NAME_CONFLICT"
        client.delete(f"/api/v1/library/files/{first['id']}", headers=headers)
        renamed = client.patch(
            f"/api/v1/library/files/{second['id']}", headers=headers, json={"name": "notes.txt"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "notes.txt"


def test_batch_uploads_report_each_result(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "batch.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        headers = _personal_headers(client, settings, "batch_user", "batch@example.com")
        created = client.post(
            "/api/v1/library/files/upload-urls",
            headers=headers,
            json={
                "items": [
                    {"fileName": "ok.txt", "mimeType": "text/plain", "fileSizeBytes": 2},
                    {
                        "fileName": "bad.exe",
                        "mimeType": "application/octet-stream",
                        "fileSizeBytes": 2,
                    },
                ]
            },
        ).json()["items"]
        assert [item["status"] for item in created] == ["created", "failed"]
        upload = created[0]["item"]
        store.put(upload["objectKey"], b"ok", content_type="text/plain")

        completed = client.post(
            "/api/v1/library/files/complete-uploads",
            headers=headers,
            json={
                "items": [
                    {"uploadSessionId": upload["uploadSessionId"]},
                    {"uploadSessionId": "upl_missing"},
                ]
            },
        ).json()["items"]
        assert [item["status"] for item in completed] == ["completed", "failed"]


def test_team_list_reuses_one_space_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(tmp_path, "list-access.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        team_id = "tenant_list_access"
        _seed_team(settings, team_id, [("list_admin", "list-admin@example.com", "admin")])
        headers = _login(client, team_id, "list-admin@example.com")
        for name in ("first.txt", "second.txt"):
            _upload(client, store, headers, name=name, content=name.encode(), space_type="team")

        original = LibraryAccessService.space_access
        calls = 0

        def counted(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return original(self, *args, **kwargs)

        monkeypatch.setattr(LibraryAccessService, "space_access", counted)
        listed = client.get("/api/v1/library/files", headers=headers, params={"spaceType": "team"})
        assert listed.status_code == 200
        assert listed.json()["total"] == 2
        assert calls == 1


def test_team_full_read_only_renewal_and_delivery_revocation(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "team-lifecycle.sqlite3")
    store = FakeObjectStore()
    fake_acp = FakeAcpGatewayClient()
    with TestClient(_app(settings, store, fake_acp)) as client:
        team_id = "tenant_business"
        _seed_team(
            settings,
            team_id,
            [
                ("uploader", "uploader@example.com", "admin"),
                ("admin", "team-admin@example.com", "admin"),
                ("member", "member@example.com", "member"),
            ],
        )
        uploader = _login(client, team_id, "uploader@example.com")
        admin = _login(client, team_id, "team-admin@example.com")
        member = _login(client, team_id, "member@example.com")
        keep, _ = _upload(
            client, store, uploader, name="keep.txt", content=b"team marker", space_type="team"
        )
        removable, _ = _upload(
            client, store, uploader, name="remove.txt", content=b"remove", space_type="team"
        )
        spaces = client.get("/api/v1/library/spaces", headers=member).json()["items"]
        assert spaces[1]["status"] == "full"
        assert spaces[1]["quotaBytes"] == 20 * 1024**3
        assert (
            client.get(
                "/api/v1/library/files", headers=member, params={"spaceType": "team"}
            ).json()["total"]
            == 2
        )

        delivery_url = _delivery_url(client, fake_acp, member, keep["id"])
        assert [client.get(delivery_url).content for _ in range(3)] == [b"team marker"] * 3
        assert client.get(delivery_url).status_code == 410

        revoke_url = _delivery_url(client, fake_acp, member, keep["id"])

        _downgrade_to_free(settings, team_id)
        readonly_spaces = client.get("/api/v1/library/spaces", headers=member).json()["items"]
        assert readonly_spaces[1]["status"] == "read_only"
        assert client.get(revoke_url).status_code == 410
        download = client.get(
            f"/api/v1/library/files/{keep['id']}/download", headers=member
        ).json()["downloadUrl"]
        assert client.get(download, headers=member).content == b"team marker"
        assert (
            client.post(
                "/api/v1/library/files/upload-url",
                headers=member,
                json={
                    "fileName": "denied.txt",
                    "mimeType": "text/plain",
                    "fileSizeBytes": 1,
                    "spaceType": "team",
                },
            ).status_code
            == 403
        )
        assert (
            client.delete(f"/api/v1/library/files/{removable['id']}", headers=member).status_code
            == 403
        )
        assert (
            client.delete(f"/api/v1/library/files/{removable['id']}", headers=admin).status_code
            == 200
        )

        _renew_business(settings, team_id)
        assert (
            client.get("/api/v1/library/spaces", headers=member).json()["items"][1]["status"]
            == "full"
        )
        restored, _ = _upload(
            client, store, member, name="restored.txt", content=b"restored", space_type="team"
        )
        fresh_delivery = _delivery_url(client, fake_acp, member, restored["id"])
        with open_database_connection(settings) as connection:
            connection.execute(
                "delete from tenant_members where tenant_id = ? and user_id = 'member'", (team_id,)
            )
            connection.commit()
        assert client.get(fresh_delivery).status_code == 410
        assert client.get(download, headers=member).status_code in {401, 403, 404}

        with open_database_connection(settings) as connection:
            connection.execute("delete from users where id = 'uploader'")
            connection.commit()
        listed = client.get(
            "/api/v1/library/files", headers=admin, params={"spaceType": "team"}
        ).json()["items"]
        by_id = {item["id"]: item for item in listed}
        assert by_id[keep["id"]]["uploadedByUserId"] is None


def test_team_read_only_uses_persisted_history_after_plan_mutation(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "team-history.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        team_id = "tenant_history"
        _seed_team(
            settings,
            team_id,
            [("history_member", "history-member@example.com", "member")],
        )
        headers = _login(client, team_id, "history-member@example.com")
        _downgrade_to_free(settings, team_id)
        with open_database_connection(settings) as connection:
            connection.execute(
                """
                update plans
                set entitlements = json_set(
                  json_set(entitlements, '$.teamLibraryEnabled', false),
                  '$.teamLibraryQuotaBytes',
                  0
                )
                where id = 'plan_business'
                """
            )
            connection.commit()

        team_space = client.get("/api/v1/library/spaces", headers=headers).json()["items"][1]
        assert team_space["status"] == "read_only"
        assert team_space["quotaBytes"] == 20 * 1024**3


def test_business_seat_limit_and_single_active_team(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "seats.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        _seed_team(settings, "team_a", [("owner_a", "owner-a@example.com", "admin")])
        _seed_team(settings, "team_b", [("owner_b", "owner-b@example.com", "admin")])
        _seed_platform_user(
            settings,
            "platform_admin",
            "platform@example.com",
            "Admin",
            "secret-pass",
            "admin",
        )
        platform = client.post(
            "/api/v1/auth/login",
            json={"email": "platform@example.com", "password": "secret-pass"},
        )
        assert platform.status_code == 200
        headers = {"Authorization": f"Bearer {platform.json()['accessToken']}"}
        for index in range(1, 6):
            _seed_tenant_user(
                settings,
                f"seat_{index}",
                f"seat-{index}@example.com",
                f"Seat {index}",
                "secret-pass",
                "member",
            )
        for index in range(1, 4):
            added = client.post(
                "/api/v1/tenants/team_a/members",
                headers=headers,
                json={"userId": f"seat_{index}", "role": "member"},
            )
            assert added.status_code == 201, added.text

        def add_last_seat(user_id: str) -> tuple[str, int, str | None]:
            response = client.post(
                "/api/v1/tenants/team_a/members",
                headers=headers,
                json={"userId": user_id, "role": "member"},
            )
            return user_id, response.status_code, response.json().get("code")

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(add_last_seat, ("seat_4", "seat_5")))
        assert sorted(status for _, status, _ in outcomes) == [201, 409]
        assert [code for _, status, code in outcomes if status == 409] == [
            "TENANT_SEAT_LIMIT_EXCEEDED"
        ]
        joined = next(user_id for user_id, status, _ in outcomes if status == 201)
        already_joined = client.post(
            "/api/v1/tenants/team_b/members",
            headers=headers,
            json={"userId": joined, "role": "member"},
        )
        assert already_joined.status_code == 409
        assert already_joined.json()["code"] == "TENANT_USER_ALREADY_IN_TEAM"


def test_plan_editor_preserves_library_entitlements_and_accepts_zero(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "plan-library-entitlements.sqlite3")
    store = FakeObjectStore()
    with TestClient(_app(settings, store)) as client:
        _seed_platform_user(
            settings,
            "plan_admin",
            "plan-admin@example.com",
            "Plan Admin",
            "secret-pass",
            "admin",
        )
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "plan-admin@example.com", "password": "secret-pass"},
        )
        headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
        legacy_editor_body = {
            "monthlyCreditLimit": 130000,
            "allExperts": True,
            "seatLimit": 5,
            "singleTurnTokenLimit": None,
            "modelTiers": ["core"],
            "features": {"teamManagement": True},
        }
        preserved = client.put(
            "/api/v1/plans/plan_business/entitlements",
            headers=headers,
            json=legacy_editor_body,
        )
        assert preserved.status_code == 200, preserved.text
        entitlements = preserved.json()["entitlements"]
        assert entitlements["personalLibraryQuotaBytes"] == 2 * 1024**3
        assert entitlements["teamLibraryQuotaBytes"] == 20 * 1024**3
        assert entitlements["teamLibraryEnabled"] is True

        explicit_zero = client.put(
            "/api/v1/plans/plan_business/entitlements",
            headers=headers,
            json={
                **legacy_editor_body,
                "personalLibraryQuotaBytes": 0,
                "teamLibraryQuotaBytes": 0,
                "teamLibraryEnabled": False,
            },
        )
        assert explicit_zero.status_code == 200, explicit_zero.text
        zero_entitlements = explicit_zero.json()["entitlements"]
        assert zero_entitlements["personalLibraryQuotaBytes"] == 0
        assert zero_entitlements["teamLibraryQuotaBytes"] == 0
        assert zero_entitlements["teamLibraryEnabled"] is False


def test_archives_can_be_downloaded_but_never_attached_to_agent(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "archive-agent.sqlite3")
    store = FakeObjectStore()
    fake_acp = FakeAcpGatewayClient()
    with TestClient(_app(settings, store, fake_acp)) as client:
        headers = _personal_headers(client, settings, "archive_user", "archive@example.com")
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("inside.txt", "zip marker")
        archives = [
            ("bundle.zip", "application/zip", buffer.getvalue()),
            ("bundle.rar", "application/vnd.rar", b"Rar!\x1a\x07\x00archive marker"),
        ]
        uploaded = []
        for name, mime_type, content in archives:
            item, _ = _upload(
                client,
                store,
                headers,
                name=name,
                content=content,
                mime_type=mime_type,
            )
            uploaded.append((item, content))
            download_url = client.get(
                f"/api/v1/library/files/{item['id']}/download", headers=headers
            ).json()["downloadUrl"]
            assert client.get(download_url, headers=headers).content == content

            session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
            calls_before = len(fake_acp.turn_calls)
            denied = client.post(
                f"/api/v1/chat/sessions/{session_id}/turns",
                headers=headers,
                json={"question": "inspect archive", "attachmentFileIds": [item["id"]]},
            )
            assert denied.status_code == 400, denied.text
            assert denied.json()["code"] == "LIBRARY_AGENT_FORMAT_UNSUPPORTED"
            assert len(fake_acp.turn_calls) == calls_before

        legacy_token = "ldc_legacy_archive"
        now = datetime.now(timezone.utc)
        with open_database_connection(settings) as connection:
            capability_count = connection.execute(
                "select count(*) from library_delivery_capabilities"
            ).fetchone()[0]
            assert capability_count == 0
            connection.execute(
                """
                insert into chat_turns (
                  id, session_id, tenant_id, user_id, request_text, status
                ) values (
                  'turn_legacy', ?, 'tenant_default', 'archive_user',
                  'legacy archive capability', 'completed'
                )
                """,
                (session_id,),
            )
            connection.execute(
                """
                insert into library_delivery_capabilities (
                  token, file_id, actor_user_id, tenant_id, turn_id,
                  max_uses, expires_at, created_at
                ) values (?, ?, 'archive_user', 'tenant_default', 'turn_legacy', 3, ?, ?)
                """,
                (
                    legacy_token,
                    uploaded[0][0]["id"],
                    (now + timedelta(minutes=5)).isoformat(),
                    now.isoformat(),
                ),
            )
            connection.commit()
        legacy_delivery = client.get(f"/api/v1/library/delivery/{legacy_token}")
        assert legacy_delivery.status_code == 400
        assert legacy_delivery.json()["code"] == "LIBRARY_AGENT_FORMAT_UNSUPPORTED"
        with open_database_connection(settings) as connection:
            assert (
                connection.execute(
                    "select use_count from library_delivery_capabilities where token = ?",
                    (legacy_token,),
                ).fetchone()[0]
                == 0
            )


def test_successful_browser_and_agent_reads_are_safely_audited(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "read-audit.sqlite3")
    store = FakeObjectStore()
    fake_acp = FakeAcpGatewayClient()
    with TestClient(_app(settings, store, fake_acp)) as client:
        headers = _personal_headers(client, settings, "audit_reader", "audit-reader@example.com")
        content = b"unique read audit content"
        item, upload = _upload(client, store, headers, name="audited.txt", content=content)
        content_url = f"/api/v1/library/files/{item['id']}/content?disposition=attachment"
        assert client.get(content_url, headers=headers).content == content

        delivery_url = _delivery_url(client, fake_acp, headers, item["id"])
        delivery_token = delivery_url.rsplit("/", 1)[-1]
        assert client.get(delivery_url).content == content

        with open_database_connection(settings) as connection:
            rows = connection.execute(
                """
                select action, operation_type, resource_id, resource_name, metadata
                from audit_events
                where action in ('library.content_read', 'library.agent_delivery_consumed')
                order by occurred_at, id
                """
            ).fetchall()
        assert [row["action"] for row in rows] == [
            "library.content_read",
            "library.agent_delivery_consumed",
        ]
        assert all(row["operation_type"] == "read" for row in rows)
        serialized = json.dumps([dict(row) for row in rows])
        for sensitive in (
            "storageObjectKey",
            upload["objectKey"],
            delivery_url,
            delivery_token,
            content.decode(),
        ):
            assert sensitive not in serialized


@pytest.mark.parametrize(
    ("extension", "mime_type", "content"),
    [
        ("pdf", "application/pdf", b"%PDF-1.7"),
        ("jpg", "image/jpeg", b"\xff\xd8\xffdata"),
        ("png", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("webp", "image/webp", b"RIFF\x04\x00\x00\x00WEBP"),
        ("rar", "application/vnd.rar", b"Rar!\x1a\x07\x00"),
        ("md", "text/markdown", b"# markdown"),
    ],
)
def test_library_format_validation_accepts_allowed_signatures(
    extension: str, mime_type: str, content: bytes
) -> None:
    _validate_declared_format(extension, mime_type, len(content))
    _validate_actual_format(extension, content)


def test_library_format_validation_rejects_spoof() -> None:
    with pytest.raises(Exception):
        _validate_actual_format("pdf", b"not a pdf")
    with pytest.raises(Exception):
        _validate_declared_format("exe", "application/octet-stream", 10)


def test_sqlite_migrations_preserve_history_and_audit(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "replay.sqlite3")
    migrate_database(settings)
    now = datetime.now(timezone.utc)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into audit_events (
              id, request_id, occurred_at, category, action, operation_type,
              actor_user_id, actor_name, actor_email, resource_type, resource_id
            ) values (
              'audit_legacy', 'request_legacy', ?, 'library', 'library.delete', 'delete',
              'legacy_user', 'Legacy', 'legacy@example.com', 'library_file', 'file_legacy'
            )
            """,
            (now.isoformat(),),
        )
        connection.execute("alter table audit_events rename to audit_events_current")
        connection.execute("create table audit_events as select * from audit_events_current")
        connection.execute("drop table audit_events_current")
        connection.execute(
            """
            insert into tenants (id, type, name, slug, status)
            values ('tenant_historical_backfill', 'team', 'Historical', 'historical-backfill', 'active')
            """
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period,
              current_period_start, current_period_end
            ) values (?, 'tenant_historical_backfill', 'plan_business', 'expired', 'yearly', ?, ?)
            """,
            (
                "subscription_historical_backfill",
                (now - timedelta(days=366)).isoformat(),
                (now - timedelta(days=1)).isoformat(),
            ),
        )
        connection.execute(
            """
            update plans
            set entitlements = json_set(
              json_set(entitlements, '$.teamLibraryEnabled', false),
              '$.teamLibraryQuotaBytes',
              0
            )
            where id = 'plan_business'
            """
        )
        connection.execute(
            """
            insert into tenants (id, type, name, slug, status)
            values ('tenant_custom_expired', 'team', 'Custom expired', 'custom-expired', 'active')
            """
        )
        connection.execute(
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period,
              current_period_start, current_period_end
            ) values (?, 'tenant_custom_expired', 'plan_free', 'expired', 'free', ?, ?)
            """,
            (
                "subscription_custom_expired",
                (now - timedelta(days=30)).isoformat(),
                (now - timedelta(days=1)).isoformat(),
            ),
        )
        connection.execute(
            """
            update plans
            set entitlements = json_set(
              json_set(entitlements, '$.teamLibraryEnabled', true),
              '$.teamLibraryQuotaBytes',
              21474836480
            )
            where id = 'plan_free'
            """
        )
        connection.commit()
    migrate_database(settings)
    migrate_database(settings)
    with open_database_connection(settings) as connection:
        columns = {
            row[1] for row in connection.execute("pragma table_info(library_files)").fetchall()
        }
        assert {"space_type", "owner_user_id", "owner_tenant_id", "display_name"} <= columns
        history = connection.execute(
            """
            select max_quota_bytes
            from team_library_entitlement_history
            where tenant_id = 'tenant_historical_backfill'
            """
        ).fetchall()
        assert len(history) == 1
        assert history[0]["max_quota_bytes"] == 20 * 1024**3
        assert (
            connection.execute(
                """
                select count(*) from team_library_entitlement_history
                where tenant_id = 'tenant_custom_expired'
                """
            ).fetchone()[0]
            == 0
        )
        audit_schema = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = 'audit_events'"
        ).fetchone()[0]
        assert "'read'" in audit_schema
        assert (
            connection.execute(
                "select operation_type from audit_events where id = 'audit_legacy'"
            ).fetchone()[0]
            == "delete"
        )
