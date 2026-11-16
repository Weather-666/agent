from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_principal
from app.core.config import Settings
from app.core.security import hash_password
from app.db import migrate_database, open_database_connection
from app.domain.auth import Principal
from app.main import create_app
from app.services.audit_service import AuditService

PREFIX = "/api/v1"


@dataclass
class FeaturedApi:
    client: TestClient
    settings: Settings
    headers: dict[str, dict[str, str]]

    def request(self, method: str, path: str, *, role="admin", body=None, params=None):
        return self.client.request(
            method, PREFIX + path, headers=self.headers[role], json=body, params=params
        )

    def category(self, name="Advertising", *, role="admin") -> dict:
        response = self.request(
            "POST", "/featured-categories", role=role, body={"name": name, "tone": "blue"}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def example(self, category: dict, question="Explain ACOS.", *, cycle=None) -> dict:
        response = self.request(
            "POST", "/featured-examples", role="expert",
            body={"categoryId": category["id"], "question": question, "reviewCycleDays": cycle},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def approve(self, example: dict) -> dict:
        response = self.request(
            "POST", f"/featured-examples/{example['id']}/review",
            body={"decision": "approve", "expectedUpdatedAt": example["updatedAt"]},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def detail(self, example: dict) -> dict:
        response = self.request("GET", f"/featured-examples/{example['id']}")
        assert response.status_code == 200, response.text
        return response.json()

    def use(self, example: dict):
        return self.request(
            "POST", f"/featured-market/examples/{example['id']}/use", role="member"
        )

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with open_database_connection(self.settings) as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]


@pytest.fixture
def featured(tmp_path: Path) -> Iterator[FeaturedApi]:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'featured.sqlite3'}",
        database_schema_dir=str(Path(__file__).resolve().parents[1] / "infra" / "sql"),
        jwt_secret="featured-test-secret-with-at-least-32-bytes",
    )
    with TestClient(create_app(settings)) as client:
        password_hash = hash_password("featured-test-password")
        with open_database_connection(settings) as connection:
            for role in ("admin", "expert", "operator", "member"):
                connection.execute(
                    "insert into users (id, email, password_hash, name, status) "
                    "values (?, ?, ?, ?, 'active')",
                    (f"user_{role}", f"{role}@example.com", password_hash, f"Real {role}"),
                )
                connection.execute(
                    "insert into tenant_members (id, tenant_id, user_id, role) "
                    "values (?, 'tenant_default', ?, 'member')",
                    (f"member_{role}", f"user_{role}"),
                )
                if role != "member":
                    connection.execute(
                        "insert into platform_user_roles (id, user_id, role, assigned_by) "
                        "values (?, ?, ?, ?)",
                        (f"role_{role}", f"user_{role}", role, "user_admin"),
                    )
            connection.commit()
        headers = {}
        for role in ("admin", "expert", "operator", "member"):
            response = client.post(
                f"{PREFIX}/auth/login",
                json={"email": f"{role}@example.com", "password": "featured-test-password"},
            )
            assert response.status_code == 200, response.text
            headers[role] = {
                "Authorization": f"Bearer {response.json()['accessToken']}",
                "x-tenant-id": "tenant_default",
            }
        yield FeaturedApi(client, settings, headers)


def _error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


def _expiry(featured: FeaturedApi, example: dict, expiry: datetime) -> None:
    with open_database_connection(featured.settings) as connection:
        connection.execute(
            "update featured_examples set expires_at = ? where id = ?",
            (expiry.isoformat(timespec="microseconds"), example["id"]),
        )
        connection.commit()


def test_persistence_author_attribution_and_category_delete_guard(featured: FeaturedApi):
    before = datetime.now(UTC)
    category = featured.category("  Advertising  ", role="expert")
    assert category["name"] == "Advertising"
    assert category["tone"] == "blue"
    assert category["short"]
    assert category["sortOrder"] == 0
    example = featured.example(category, "  Explain ACOS.  ")
    assert example["question"] == "Explain ACOS."
    assert example["status"] == "pending"
    assert example["clickCount"] == 0
    assert example["createdBy"] == example["updatedBy"] == "user_expert"
    assert example["authorName"] == "Real expert"
    assert example["reviewedBy"] is None
    assert example["reviewedAt"] is None
    assert example["expiresAt"] is None
    assert example["reviewState"] == "none"
    assert before <= datetime.fromisoformat(example["createdAt"]) <= datetime.now(UTC)
    assert featured.detail(example) == example
    category_path = f"/featured-categories/{category['id']}"
    _error(featured.request("DELETE", category_path), 409, "FEATURED_CATEGORY_NOT_EMPTY")
    response = featured.request(
        "PATCH", category_path, role="expert", body={"name": "  Sales  ", "tone": "green"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Sales"
    assert response.json()["tone"] == "green"
    example_path = f"/featured-examples/{example['id']}"
    assert featured.request("DELETE", example_path, role="expert").status_code == 204
    assert featured.request("DELETE", category_path, role="expert").status_code == 204
    _error(featured.request("GET", example_path), 404, "FEATURED_EXAMPLE_NOT_FOUND")


@pytest.mark.parametrize(
    ("role", "read", "write", "publish"),
    [("admin", True, True, True), ("expert", True, True, False),
     ("operator", True, False, False), ("member", False, False, False)],
)
def test_platform_permissions_on_each_route(
    featured: FeaturedApi, role: str, read: bool, write: bool, publish: bool
):
    category = featured.category()
    example = featured.example(category)
    category_path = f"/featured-categories/{category['id']}"
    example_path = f"/featured-examples/{example['id']}"
    for path in ("/featured-categories", "/featured-examples", example_path):
        response = featured.request("GET", path, role=role)
        assert response.status_code == (200 if read else 403), response.text
        assert featured.client.get(PREFIX + path).status_code == 401
    if not write:
        for method, path, body in (
            ("POST", "/featured-categories", {"name": "New", "tone": "blue"}),
            ("PATCH", category_path, {"name": "Changed"}),
            ("DELETE", category_path, None),
            ("PUT", "/featured-categories/order", {"ids": [category["id"]]}),
            ("POST", "/featured-examples", {"categoryId": category["id"], "question": "New"}),
            ("PATCH", example_path, {"question": "Changed"}),
            ("DELETE", example_path, None),
            ("PUT", category_path + "/examples/order", {"ids": [example["id"]]}),
        ):
            response = featured.request(method, path, role=role, body=body)
            assert response.status_code == 403, response.text
    else:
        response = featured.request(
            "PATCH", example_path, role=role, body={"question": "Updated with write permission."}
        )
        assert response.status_code == 200, response.text
        example = response.json()
    response = featured.request(
        "POST", example_path + "/review", role=role,
        body={"decision": "approve", "expectedUpdatedAt": example["updatedAt"]},
    )
    assert response.status_code == (200 if publish else 403), response.text
    if not publish:
        assert featured.request("POST", example_path + "/unlist", role=role).status_code == 403


def test_market_requires_exact_chat_permission_and_matching_tenant(featured: FeaturedApi):
    example = featured.approve(featured.example(featured.category()))
    routes = (
        ("GET", "/featured-market/examples"),
        ("POST", f"/featured-market/examples/{example['id']}/use"),
    )
    for method, path in routes:
        assert featured.client.request(method, PREFIX + path).status_code == 401
        headers = dict(featured.headers["member"])
        headers.pop("x-tenant-id")
        assert featured.client.request(method, PREFIX + path, headers=headers).status_code == 401
        headers["x-tenant-id"] = "another_tenant"
        assert featured.client.request(method, PREFIX + path, headers=headers).status_code == 403
    featured.client.app.dependency_overrides[require_principal] = lambda: Principal(
        user_id="user_member", email="member@example.com", active_tenant_id="tenant_default",
        tenant_permissions=["chat:*"],
    )
    try:
        for method, path in routes:
            assert featured.request(method, path, role="member").status_code == 403
    finally:
        featured.client.app.dependency_overrides.pop(require_principal)
    assert featured.detail(example)["clickCount"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"question": None}, {"question": "   "}, {"question": "x" * 4001},
        {"categoryId": None}, {"reviewCycleDays": 7}, {"reviewCycleDays": True},
        {"status": "live"}, {"clickCount": 100}, {"createdBy": "user_admin"},
        {"reviewedAt": "2026-09-08T00:00:00Z"}, {"expiresAt": None},
    ],
)
def test_patch_rejects_invalid_or_server_owned_fields(featured: FeaturedApi, body: dict):
    example = featured.example(featured.category())
    response = featured.request(
        "PATCH", f"/featured-examples/{example['id']}", role="expert", body=body
    )
    assert response.status_code == 422, response.text
    assert featured.detail(example) == example


def test_create_validation_and_missing_references(featured: FeaturedApi):
    for body in (
        {"name": " ", "tone": "blue"}, {"name": "x" * 61, "tone": "blue"},
        {"name": "Valid", "tone": "red"}, {"name": "Valid", "tone": "blue", "sortOrder": 9},
    ):
        response = featured.request("POST", "/featured-categories", role="expert", body=body)
        assert response.status_code == 422, response.text
    _error(
        featured.request(
            "POST", "/featured-examples", role="expert",
            body={"categoryId": "missing", "question": "Valid question"},
        ), 404, "FEATURED_CATEGORY_NOT_FOUND",
    )
    category = featured.category()
    for fields in (
        {"question": "   "}, {"question": "Valid", "status": "live"},
        {"question": "Valid", "reviewCycleDays": 15},
    ):
        response = featured.request(
            "POST", "/featured-examples", role="expert",
            body={"categoryId": category["id"], **fields},
        )
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("cycle", [None, 30, 60, 90])
def test_utc_expiry_and_repeated_valid_live_review(featured: FeaturedApi, cycle: int | None):
    example = featured.example(featured.category(), cycle=cycle)
    timestamp = datetime.fromisoformat(example["updatedAt"]).astimezone(timezone(timedelta(hours=8)))
    response = featured.request(
        "POST", f"/featured-examples/{example['id']}/review",
        body={"decision": "approve", "expectedUpdatedAt": timestamp.isoformat()},
    )
    assert response.status_code == 200, response.text
    example = response.json()
    reviewed = datetime.fromisoformat(example["reviewedAt"])
    assert reviewed.utcoffset() == timedelta(0)
    assert example["status"] == "live"
    assert example["reviewedBy"] == example["updatedBy"] == "user_admin"
    if cycle is None:
        assert example["expiresAt"] is None
        assert example["reviewState"] == "none"
    else:
        expiry = datetime.fromisoformat(example["expiresAt"])
        assert expiry.utcoffset() == timedelta(0)
        assert expiry - reviewed == timedelta(days=cycle)
        assert example["reviewState"] == "normal"
    for decision in ("approve", "reject"):
        _error(
            featured.request(
                "POST", f"/featured-examples/{example['id']}/review",
                body={"decision": decision, "reason": "Needs review",
                      "expectedUpdatedAt": example["updatedAt"]},
            ), 409, "FEATURED_INVALID_TRANSITION",
        )
    assert featured.detail(example) == example


def test_stale_review_reject_unlist_and_reapprove(featured: FeaturedApi):
    example = featured.example(featured.category())
    path = f"/featured-examples/{example['id']}"
    response = featured.request(
        "PATCH", path, role="expert", body={"question": "New content requiring current approval."}
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    _error(
        featured.request(
            "POST", path + "/review",
            body={"decision": "approve", "expectedUpdatedAt": example["updatedAt"]},
        ), 409, "FEATURED_EXAMPLE_CHANGED",
    )
    for invalid in (
        {"decision": "approve"},
        {"decision": "approve", "expectedUpdatedAt": "not-a-date"},
        {"decision": "approve", "expectedUpdatedAt": "2026-09-08T08:00:00"},
        {"decision": "reject", "expectedUpdatedAt": changed["updatedAt"], "reason": "  "},
    ):
        assert featured.request("POST", path + "/review", body=invalid).status_code == 422
    response = featured.request(
        "POST", path + "/review",
        body={"decision": "reject", "reason": "  Please clarify.  ",
              "expectedUpdatedAt": changed["updatedAt"]},
    )
    assert response.status_code == 200, response.text
    rejected = response.json()
    assert rejected["status"] == "rejected"
    assert rejected["rejectReason"] == "Please clarify."
    assert rejected["reviewedBy"] == "user_admin"
    assert datetime.fromisoformat(rejected["reviewedAt"]).utcoffset() == timedelta(0)
    assert featured.approve(rejected)["rejectReason"] is None
    response = featured.request("POST", path + "/unlist")
    assert response.status_code == 200, response.text
    unlisted = response.json()
    assert unlisted["status"] == "unlisted"
    _error(featured.request("POST", path + "/unlist"), 409, "FEATURED_INVALID_TRANSITION")
    assert featured.approve(unlisted)["status"] == "live"


@pytest.mark.parametrize("field", ["question", "categoryId", "reviewCycleDays"])
def test_actual_content_change_withdraws_approval_while_noop_preserves_it(
    featured: FeaturedApi, field: str
):
    first = featured.category()
    second = featured.category("Other")
    example = featured.approve(featured.example(first, cycle=30))
    path = f"/featured-examples/{example['id']}"
    response = featured.request(
        "PATCH", path, role="expert",
        body={"categoryId": first["id"], "question": f"  {example['question']}  ",
              "reviewCycleDays": 30},
    )
    assert response.status_code == 200, response.text
    assert response.json() == example
    changes = {"question": "Different question", "categoryId": second["id"], "reviewCycleDays": None}
    response = featured.request("PATCH", path, role="expert", body={field: changes[field]})
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed[field] == changes[field]
    assert changed["status"] == "pending"
    for key in ("reviewedAt", "reviewedBy", "expiresAt", "rejectReason"):
        assert changed[key] is None
    assert changed["updatedBy"] == "user_expert"
    assert changed["updatedAt"] != example["updatedAt"]
    assert featured.request("GET", "/featured-market/examples", role="member").json()["items"] == []


def test_order_requires_complete_sets_and_preserves_review(featured: FeaturedApi):
    first = featured.category("First")
    second = featured.category("Second")
    one = featured.approve(featured.example(first, "First example"))
    two = featured.approve(featured.example(first, "Second example"))
    three = featured.approve(featured.example(second, "Third example"))
    category_order = "/featured-categories/order"
    example_order = f"/featured-categories/{first['id']}/examples/order"
    for path, ids in (
        (category_order, [first["id"]]), (category_order, [first["id"], first["id"]]),
        (category_order, [first["id"], "missing"]), (example_order, [one["id"]]),
        (example_order, [one["id"], one["id"]]), (example_order, [one["id"], three["id"]]),
    ):
        _error(
            featured.request("PUT", path, role="expert", body={"ids": ids}),
            409, "FEATURED_ORDER_INVALID",
        )
    assert featured.detail(one) == one
    assert featured.detail(two) == two
    for path, ids in (
        (category_order, [second["id"], first["id"]]), (example_order, [two["id"], one["id"]]),
    ):
        response = featured.request("PUT", path, role="expert", body={"ids": ids})
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == ids
    response = featured.request("GET", "/featured-market/examples", role="member")
    assert [item["id"] for item in response.json()["items"]] == [three["id"], two["id"], one["id"]]
    for original in (one, two):
        actual = featured.detail(original)
        for key in ("status", "reviewedAt", "expiresAt"):
            assert actual[key] == original[key]
    response = featured.request(
        "GET", "/featured-market/examples", role="member", params={"categoryId": second["id"]}
    )
    assert [item["id"] for item in response.json()["items"]] == [three["id"]]


def test_expiry_boundaries_filters_counts_and_read_only_derivation(
    featured: FeaturedApi, monkeypatch: pytest.MonkeyPatch
):
    now = datetime(2026, 9, 8, 8, tzinfo=UTC)
    monkeypatch.setattr("app.services.featured_example_service._now", lambda: now)
    category = featured.category()
    other = featured.category("Other")
    normal = featured.approve(featured.example(category, "Normal", cycle=30))
    expiring = featured.approve(featured.example(category, "Expiring", cycle=30))
    expired = featured.approve(featured.example(category, "Expired", cycle=30))
    permanent = featured.approve(featured.example(category, "Permanent"))
    pending = featured.example(category, "Pending")
    featured.approve(featured.example(other, "Other category"))
    _expiry(featured, normal, now + timedelta(days=7, microseconds=1))
    _expiry(featured, expiring, now + timedelta(days=7))
    _expiry(featured, expired, now)
    before = featured.rows("select * from featured_examples order by id")
    counts = {
        "total": 5, "live": 3, "pending": 1, "reviewing": 1,
        "rejected": 0, "unlisted": 0, "expiring": 1, "expired": 1,
    }
    for filters, ids in (
        ({}, {normal["id"], expiring["id"], expired["id"], permanent["id"], pending["id"]}),
        ({"status": "reviewing"}, {expired["id"]}),
        ({"status": "live"}, {normal["id"], expiring["id"], permanent["id"]}),
        ({"reviewState": "expiring"}, {expiring["id"]}),
        ({"reviewState": "expired"}, {expired["id"]}),
        ({"keyword": "Permanent"}, {permanent["id"]}), ({"keyword": "absent"}, set()),
    ):
        response = featured.request(
            "GET", "/featured-examples", role="operator",
            params={"categoryId": category["id"], **filters},
        )
        assert response.status_code == 200, response.text
        assert response.json()["counts"] == counts
        assert {item["id"] for item in response.json()["items"]} == ids
    assert featured.detail(expired)["status"] == "reviewing"
    assert featured.detail(expired)["reviewState"] == "expired"
    response = featured.request(
        "GET", "/featured-market/examples", role="member", params={"categoryId": category["id"]}
    )
    assert {item["id"] for item in response.json()["items"]} == {
        normal["id"], expiring["id"], permanent["id"]
    }
    assert featured.rows("select * from featured_examples order by id") == before
    _error(featured.use(expired), 409, "FEATURED_EXAMPLE_UNAVAILABLE")
    assert featured.rows("select * from featured_examples order by id") == before
    renewed = featured.approve(featured.detail(expired))
    assert renewed["status"] == "live"
    assert datetime.fromisoformat(renewed["expiresAt"]) == now + timedelta(days=30)


def test_market_use_current_question_counter_and_unavailable_states(featured: FeaturedApi):
    category = featured.category()
    example = featured.example(category, "Original")
    _error(featured.use(example), 409, "FEATURED_EXAMPLE_UNAVAILABLE")
    path = f"/featured-examples/{example['id']}"
    response = featured.request(
        "PATCH", path, role="expert", body={"question": "Currently approved question"}
    )
    assert response.status_code == 200, response.text
    example = featured.approve(response.json())
    audit_count = len(featured.rows("select id from audit_events"))
    market = featured.request("GET", "/featured-market/examples", role="member")
    assert market.status_code == 200, market.text
    item = market.json()["items"][0]
    assert set(item) == {
        "id", "question", "categoryId", "categoryName", "categoryTone", "sortOrder", "clickCount"
    }
    assert item["categoryName"] == category["name"]
    assert item["clickCount"] == 0
    for count in (1, 2):
        response = featured.use(example)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "id": example["id"], "question": "Currently approved question", "clickCount": count
        }
    used = featured.detail(example)
    assert used["clickCount"] == 2
    assert used["updatedAt"] == example["updatedAt"]
    assert used["updatedBy"] == example["updatedBy"]
    assert len(featured.rows("select id from audit_events")) == audit_count
    assert featured.request("POST", path + "/unlist").status_code == 200
    _error(featured.use(example), 409, "FEATURED_EXAMPLE_UNAVAILABLE")
    assert featured.detail(example)["clickCount"] == 2
    assert featured.request("DELETE", path, role="expert").status_code == 204
    _error(featured.use(example), 404, "FEATURED_EXAMPLE_NOT_FOUND")


def test_concurrent_use_counts_each_accepted_request_once(featured: FeaturedApi):
    example = featured.approve(featured.example(featured.category()))
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: featured.use(example), range(24)))
    assert all(response.status_code == 200 for response in responses), [
        (response.status_code, response.text) for response in responses
    ]
    bodies = [response.json() for response in responses]
    assert sorted(body["clickCount"] for body in bodies) == list(range(1, 25))
    assert {body["question"] for body in bodies} == {example["question"]}
    final = featured.detail(example)
    assert final["clickCount"] == 24
    assert final["updatedAt"] == example["updatedAt"]


def test_management_audit_failure_rolls_back_business_write(
    featured: FeaturedApi, monkeypatch: pytest.MonkeyPatch
):
    category = featured.category()
    example = featured.example(category)
    query = "select * from audit_events where resource_id = ? order by occurred_at"
    created = featured.rows(query, (example["id"],))
    assert len(created) == 1
    assert created[0]["actor_user_id"] == "user_expert"
    assert created[0]["actor_name"] == "Real expert"
    assert created[0]["request_id"]
    assert "question" not in json.loads(created[0]["metadata"])

    def fail_record(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(AuditService, "record", fail_record)
    with pytest.raises(RuntimeError, match="audit write failed"):
        featured.request(
            "PATCH", f"/featured-examples/{example['id']}", role="expert",
            body={"question": "Must roll back"},
        )
    assert featured.detail(example) == example
    with pytest.raises(RuntimeError, match="audit write failed"):
        featured.request(
            "POST", "/featured-categories", role="expert",
            body={"name": "Must roll back", "tone": "blue"},
        )
    assert [row["id"] for row in featured.rows("select id from featured_example_categories")] == [
        category["id"]
    ]
    assert featured.rows(query, (example["id"],)) == created


def test_repeated_migrations_preserve_featured_data_and_foreign_keys(featured: FeaturedApi):
    category = featured.category()
    example = featured.approve(featured.example(category, cycle=60))
    assert featured.use(example).status_code == 200
    before = featured.rows("select * from featured_examples")
    categories = featured.rows("select * from featured_example_categories")
    migrate_database(featured.settings)
    migrate_database(featured.settings)
    assert featured.rows("select * from featured_examples") == before
    assert featured.rows("select * from featured_example_categories") == categories
    with open_database_connection(featured.settings) as connection:
        assert connection.execute("pragma foreign_keys").fetchone()[0] == 1
        assert connection.execute("pragma foreign_key_check").fetchall() == []



def test_concurrent_review_approves_one_current_revision(featured: FeaturedApi):
    example = featured.example(featured.category(), cycle=30)

    def approve(_: int):
        return featured.request(
            "POST", f"/featured-examples/{example['id']}/review",
            body={"decision": "approve", "expectedUpdatedAt": example["updatedAt"]},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(approve, range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["code"] == "FEATURED_EXAMPLE_CHANGED"
    approved = next(response.json() for response in responses if response.status_code == 200)
    assert featured.detail(example) == approved
    assert len(featured.rows(
        "select id from audit_events where resource_id = ? and action = ?",
        (example["id"], "featured_example.review"),
    )) == 1


@pytest.mark.parametrize("action", ["reject", "unlist"])
def test_expired_live_can_be_rejected_or_unlisted(
    featured: FeaturedApi, monkeypatch: pytest.MonkeyPatch, action: str
):
    now = datetime(2026, 9, 8, 8, tzinfo=UTC)
    monkeypatch.setattr("app.services.featured_example_service._now", lambda: now)
    example = featured.approve(featured.example(featured.category(), cycle=30))
    _expiry(featured, example, now)
    path = f"/featured-examples/{example['id']}"
    if action == "reject":
        response = featured.request(
            "POST", path + "/review",
            body={"decision": "reject", "expectedUpdatedAt": example["updatedAt"],
                  "reason": "Outdated information"},
        )
        expected_status = "rejected"
    else:
        response = featured.request("POST", path + "/unlist")
        expected_status = "unlisted"
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status
    _error(featured.use(example), 409, "FEATURED_EXAMPLE_UNAVAILABLE")
    assert featured.detail(example)["clickCount"] == 0
    assert featured.request("GET", "/featured-market/examples", role="member").json()["items"] == []
