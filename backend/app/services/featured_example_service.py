from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.featured_examples import (
    CreateFeaturedCategoryRequest,
    CreateFeaturedExampleRequest,
    FeaturedOrderRequest,
    ReviewFeaturedExampleRequest,
    UpdateFeaturedCategoryRequest,
    UpdateFeaturedExampleRequest,
)
from app.services.audit_service import AuditService, changes
from app.services.featured_example_repository import FeaturedExampleRepository


class FeaturedExampleService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.repo = FeaturedExampleRepository(connection)

    @contextmanager
    def _edit(self) -> Iterator[None]:
        try:
            self.repo.begin_edit()
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _audit(
        self,
        principal: Principal,
        request_id: str,
        action: str,
        resource_id: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
        fields: set[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        resource_type, operation = action.split(".")
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.FEATURED_EXAMPLE,
            action=action,
            operation_type=(
                AuditOperationType(operation)
                if operation in {"create", "delete"}
                else AuditOperationType.UPDATE
            ),
            resource=AuditResource(type=resource_type, id=resource_id),
            changes=changes(before or {}, after or {}, fields or set()),
            metadata=metadata,
        )

    def _category(self, category_id: str) -> dict:
        row = self.repo.category(category_id)
        if row is None:
            raise ApiError(404, "FEATURED_CATEGORY_NOT_FOUND", "Featured category not found")
        return row

    def _example(self, example_id: str) -> dict:
        row = self.repo.example(example_id)
        if row is None:
            raise ApiError(404, "FEATURED_EXAMPLE_NOT_FOUND", "Featured example not found")
        return row

    def list_categories(self) -> dict:
        return {"items": [_category_response(row) for row in self.repo.categories()]}

    def create_category(
        self,
        principal: Principal,
        payload: CreateFeaturedCategoryRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            category_id = f"featured_category_{uuid4().hex}"
            self.repo.create_category(category_id, payload.name, payload.tone, _iso(_now()))
            self._audit(
                principal,
                request_id,
                "featured_category.create",
                category_id,
                metadata={"tone": payload.tone},
            )
            result = _category_response(self._category(category_id))
        return result

    def update_category(
        self,
        principal: Principal,
        category_id: str,
        payload: UpdateFeaturedCategoryRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            existing = self._category(category_id)
            before = _category_response(existing)
            values = {**before, **payload.model_dump(exclude_unset=True)}
            if values == before:
                return before
            self.repo.update_category(
                category_id, values["name"], values["tone"], _updated_at(_now(), existing)
            )
            after = _category_response(self._category(category_id))
            self._audit(
                principal,
                request_id,
                "featured_category.update",
                category_id,
                before=before,
                after=after,
                fields={"name", "tone"},
            )
        return after

    def delete_category(
        self,
        principal: Principal,
        category_id: str,
        *,
        request_id: str,
    ) -> None:
        with self._edit():
            self._category(category_id)
            if self.repo.examples(category_id):
                raise ApiError(
                    409,
                    "FEATURED_CATEGORY_NOT_EMPTY",
                    "Move or delete this category's examples first",
                )
            self.repo.delete_category(category_id)
            self._audit(principal, request_id, "featured_category.delete", category_id)

    def order_categories(
        self,
        principal: Principal,
        payload: FeaturedOrderRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            rows = self.repo.categories()
            _validate_order(payload.ids, rows)
            by_id = {row["id"]: row for row in rows}
            now = _now()
            changed = False
            for position, category_id in enumerate(payload.ids):
                row = by_id[category_id]
                if row["sort_order"] != position:
                    self.repo.order_category(category_id, position, _updated_at(now, row))
                    changed = True
            if changed:
                self._audit(
                    principal,
                    request_id,
                    "featured_category.reorder",
                    "featured_categories",
                    metadata={"ids": payload.ids},
                )
            result = self.list_categories()
        return result

    def get_example(self, example_id: str) -> dict:
        return _example_response(self._example(example_id), _now())

    def list_examples(
        self,
        *,
        category_id: str | None = None,
        status: str | None = None,
        review_state: str | None = None,
        keyword: str | None = None,
    ) -> dict:
        now = _now()
        items = [_example_response(row, now) for row in self.repo.examples(category_id)]
        counts = dict.fromkeys(
            (
                "total",
                "live",
                "pending",
                "reviewing",
                "rejected",
                "unlisted",
                "expiring",
                "expired",
            ),
            0,
        )
        counts["total"] = len(items)
        for item in items:
            counts[item["status"]] += 1
            if item["reviewState"] in {"expiring", "expired"}:
                counts[item["reviewState"]] += 1
        needle = keyword.strip().casefold() if keyword else ""
        return {
            "items": [
                item
                for item in items
                if (status is None or item["status"] == status)
                and (review_state is None or item["reviewState"] == review_state)
                and (not needle or needle in item["question"].casefold())
            ],
            "counts": counts,
        }

    def create_example(
        self,
        principal: Principal,
        payload: CreateFeaturedExampleRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            self._category(payload.categoryId)
            example_id = f"featured_example_{uuid4().hex}"
            now = _now()
            self.repo.create_example(
                example_id,
                payload.categoryId,
                payload.question,
                payload.reviewCycleDays,
                principal.user_id,
                _iso(now),
            )
            self._audit(
                principal,
                request_id,
                "featured_example.create",
                example_id,
                metadata={
                    "categoryId": payload.categoryId,
                    "reviewCycleDays": payload.reviewCycleDays,
                },
            )
            result = _example_response(self._example(example_id), now)
        return result

    def update_example(
        self,
        principal: Principal,
        example_id: str,
        payload: UpdateFeaturedExampleRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            now = _now()
            row = self._example(example_id)
            before = _example_response(row, now)
            values = {**before, **payload.model_dump(exclude_unset=True)}
            if values == before:
                return before
            position = row["sort_order"]
            if values["categoryId"] != before["categoryId"]:
                self._category(values["categoryId"])
                position = self.repo.next_example_order(values["categoryId"])
            self.repo.update_example(
                example_id,
                values["categoryId"],
                values["question"],
                values["reviewCycleDays"],
                position,
                principal.user_id,
                _updated_at(now, row),
            )
            after = _example_response(self._example(example_id), now)
            self._audit(
                principal,
                request_id,
                "featured_example.update",
                example_id,
                before=before,
                after=after,
                fields={"categoryId", "reviewCycleDays", "status"},
                metadata={"questionChanged": before["question"] != after["question"]},
            )
        return after

    def delete_example(
        self,
        principal: Principal,
        example_id: str,
        *,
        request_id: str,
    ) -> None:
        with self._edit():
            row = self._example(example_id)
            self.repo.delete_example(example_id)
            self._audit(
                principal,
                request_id,
                "featured_example.delete",
                example_id,
                metadata={"categoryId": row["category_id"], "status": row["status"]},
            )

    def order_examples(
        self,
        principal: Principal,
        category_id: str,
        payload: FeaturedOrderRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            self._category(category_id)
            rows = self.repo.examples(category_id)
            _validate_order(payload.ids, rows)
            by_id = {row["id"]: row for row in rows}
            now = _now()
            changed = False
            for position, example_id in enumerate(payload.ids):
                row = by_id[example_id]
                if row["sort_order"] != position:
                    self.repo.order_example(
                        example_id, position, principal.user_id, _updated_at(now, row)
                    )
                    changed = True
            if changed:
                self._audit(
                    principal,
                    request_id,
                    "featured_example.reorder",
                    category_id,
                    metadata={"categoryId": category_id, "ids": payload.ids},
                )
            result = {
                "items": [_example_response(row, now) for row in self.repo.examples(category_id)]
            }
        return result

    def review_example(
        self,
        principal: Principal,
        example_id: str,
        payload: ReviewFeaturedExampleRequest,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            now = _now()
            row = self._example(example_id)
            if _datetime(row["updated_at"]) != payload.expectedUpdatedAt:
                raise _changed()
            before = _example_response(row, now)
            allowed = (
                {"pending", "rejected", "unlisted", "reviewing"}
                if payload.decision == "approve"
                else {"pending", "reviewing"}
            )
            if before["status"] not in allowed:
                raise ApiError(
                    409,
                    "FEATURED_INVALID_TRANSITION",
                    "Example cannot be reviewed in its current state",
                )
            approved = payload.decision == "approve"
            cycle = row["review_cycle_days"]
            expires_at = _iso(now + timedelta(days=cycle)) if approved and cycle else None
            if not self.repo.review(
                example_id,
                expected_updated_at=_iso(payload.expectedUpdatedAt),
                status="live" if approved else "rejected",
                actor_id=principal.user_id,
                reviewed_at=_iso(now),
                updated_at=_updated_at(now, row),
                expires_at=expires_at,
                reason=None if approved else payload.reason,
            ):
                raise _changed()
            after = _example_response(self._example(example_id), now)
            self._audit(
                principal,
                request_id,
                "featured_example.review",
                example_id,
                before=before,
                after=after,
                fields={"status"},
                metadata={"decision": payload.decision, "reviewCycleDays": cycle},
            )
        return after

    def unlist_example(
        self,
        principal: Principal,
        example_id: str,
        *,
        request_id: str,
    ) -> dict:
        with self._edit():
            now = _now()
            row = self._example(example_id)
            if row["status"] != "live":
                raise ApiError(
                    409, "FEATURED_INVALID_TRANSITION", "Only live examples can be unlisted"
                )
            before = _example_response(row, now)
            self.repo.unlist(example_id, principal.user_id, _updated_at(now, row))
            after = _example_response(self._example(example_id), now)
            self._audit(
                principal,
                request_id,
                "featured_example.unlist",
                example_id,
                before=before,
                after=after,
                fields={"status"},
            )
        return after

    def list_market(self, *, category_id: str | None = None) -> dict:
        now = _now()
        return {
            "items": [
                {
                    "id": row["id"],
                    "question": row["question"],
                    "categoryId": row["category_id"],
                    "categoryName": row["category_name"],
                    "categoryTone": row["category_tone"],
                    "sortOrder": row["sort_order"],
                    "clickCount": row["click_count"],
                }
                for row in self.repo.examples(category_id)
                if row["status"] == "live"
                and (row["expires_at"] is None or _datetime(row["expires_at"]) > now)
            ]
        }

    def use_example(self, example_id: str) -> dict:
        try:
            row = self.repo.use(example_id, _iso(_now()))
            if row is None:
                self._example(example_id)
                raise ApiError(
                    409,
                    "FEATURED_EXAMPLE_UNAVAILABLE",
                    "Featured example is not currently available",
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {"id": row["id"], "question": row["question"], "clickCount": row["click_count"]}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime(value: datetime | str) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return result.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    # Fixed UTC representation makes SQLite comparisons agree with PostgreSQL timestamptz.
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _updated_at(now: datetime, row: dict) -> str:
    return _iso(max(now, _datetime(row["updated_at"]) + timedelta(microseconds=1)))


def _changed() -> ApiError:
    return ApiError(409, "FEATURED_EXAMPLE_CHANGED", "Example changed. Reload it before reviewing")


def _validate_order(ids: list[str], rows: list[dict]) -> None:
    if len(ids) != len(set(ids)) or set(ids) != {row["id"] for row in rows}:
        raise ApiError(
            409,
            "FEATURED_ORDER_INVALID",
            "Order must contain every ID in the collection exactly once",
        )


def _category_response(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "short": row["name"][:2],
        "tone": row["tone"],
        "sortOrder": row["sort_order"],
        "createdAt": _iso(_datetime(row["created_at"])),
        "updatedAt": _iso(_datetime(row["updated_at"])),
    }


def _example_response(row: dict, now: datetime) -> dict:
    expiry = _datetime(row["expires_at"]) if row["expires_at"] is not None else None
    review_state = (
        "none"
        if expiry is None
        else "expired"
        if expiry <= now
        else "expiring"
        if expiry <= now + timedelta(days=7)
        else "normal"
    )
    return {
        "id": row["id"],
        "categoryId": row["category_id"],
        "question": row["question"],
        "sortOrder": row["sort_order"],
        "status": "reviewing"
        if row["status"] == "live" and review_state == "expired"
        else row["status"],
        "reviewCycleDays": row["review_cycle_days"],
        "reviewState": review_state,
        "reviewedAt": _iso(_datetime(row["reviewed_at"]))
        if row["reviewed_at"] is not None
        else None,
        "expiresAt": _iso(expiry) if expiry is not None else None,
        "rejectReason": row["reject_reason"],
        "clickCount": row["click_count"],
        "createdBy": row["created_by"],
        "authorName": row["author_name"],
        "updatedBy": row["updated_by"],
        "reviewedBy": row["reviewed_by"],
        "createdAt": _iso(_datetime(row["created_at"])),
        "updatedAt": _iso(_datetime(row["updated_at"])),
    }
