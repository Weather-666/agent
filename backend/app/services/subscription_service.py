from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.plans import CurrentSubscriptionResponse, TenantSubscription
from app.services.plan_repository import PlanRepository
from app.services.subscription_repository import SubscriptionRepository


class SubscriptionService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.repo = SubscriptionRepository(connection)
        self.plan_repo = PlanRepository(connection)

    def current_subscription(self, tenant_id: str | None) -> CurrentSubscriptionResponse:
        if not tenant_id:
            raise ApiError(400, "TENANT_REQUIRED", "Active tenant is required")

        subscription = self.ensure_default_subscription(tenant_id)

        plan = self.plan_repo.get(subscription.planId)
        if not plan:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")

        self.connection.commit()
        return CurrentSubscriptionResponse(subscription=subscription, plan=plan)

    def ensure_default_subscription(self, tenant_id: str) -> TenantSubscription:
        """Return the current subscription, creating the default one when needed.

        The caller owns the transaction. User-side current-subscription reads call this directly;
        tenant creation flows call it before committing their new tenant.
        """
        subscription = self.repo.get_current(tenant_id)
        if subscription is not None:
            return subscription

        plan = self.plan_repo.get_by_code("free")
        if not plan:
            raise ApiError(500, "FREE_PLAN_MISSING", "Free plan is not configured")

        now = _now_iso()
        subscription_id = f"tenant_subscription_{uuid4().hex}"
        self.repo.insert_subscription(
            subscription_id=subscription_id,
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="active",
            billing_period="free",
            current_period_start=now,
            current_period_end=None,
        )
        subscription = self.repo.get_current(tenant_id)
        if subscription is None:
            raise ApiError(500, "SUBSCRIPTION_CREATE_FAILED", "Subscription create failed")
        return subscription


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
