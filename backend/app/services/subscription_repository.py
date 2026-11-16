from __future__ import annotations

from typing import Any

from app.db import DatabaseConnection
from app.domain.plans import TenantSubscription
from app.services._sql import execute, fetch_one


class SubscriptionRepository:
    """Raw SQL data access for subscriptions."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def get_current(self, tenant_id: str) -> TenantSubscription | None:
        row = fetch_one(
            self.connection,
            """
            select id, tenant_id, plan_id, status, billing_period, current_period_start,
                   current_period_end, cancel_at_period_end, created_at, updated_at
            from subscriptions
            where tenant_id = ?
              and status in ('active', 'trialing', 'past_due')
              and (current_period_end is null or current_period_end > CURRENT_TIMESTAMP)
            order by current_period_start desc, created_at desc
            limit 1
            """,
            (tenant_id,),
        )
        return _map_subscription(row) if row else None

    def get_latest_for_management(self, tenant_id: str) -> TenantSubscription | None:
        """Return the newest real subscription without changing tenant state."""
        row = fetch_one(
            self.connection,
            """
            select id, tenant_id, plan_id, status, billing_period, current_period_start,
                   current_period_end, cancel_at_period_end, created_at, updated_at
            from subscriptions
            where tenant_id = ?
            order by current_period_start desc, created_at desc, id desc
            limit 1
            """,
            (tenant_id,),
        )
        return _map_subscription(row) if row else None

    def insert_subscription(
        self,
        *,
        subscription_id: str,
        tenant_id: str,
        plan_id: str,
        status: str,
        billing_period: str,
        current_period_start: str,
        current_period_end: str | None,
    ) -> None:
        execute(
            self.connection,
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period,
              current_period_start, current_period_end
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subscription_id,
                tenant_id,
                plan_id,
                status,
                billing_period,
                current_period_start,
                current_period_end,
            ),
        )

    def record_team_library_entitlements_for_plan(self, plan_id: str, quota: int) -> None:
        """Persist a monotonic acquisition fact for every currently usable subscriber."""
        execute(
            self.connection,
            """
            insert into team_library_entitlement_history (tenant_id, max_quota_bytes)
            select distinct tenant_id, ?
            from subscriptions
            where plan_id = ?
              and status in ('active', 'trialing', 'past_due')
              and (current_period_end is null or current_period_end > CURRENT_TIMESTAMP)
            on conflict (tenant_id) do update
            set max_quota_bytes = case
                  when excluded.max_quota_bytes
                       > team_library_entitlement_history.max_quota_bytes
                    then excluded.max_quota_bytes
                  else team_library_entitlement_history.max_quota_bytes
                end,
                updated_at = CURRENT_TIMESTAMP
            """,
            (quota, plan_id),
        )


def _map_subscription(row: dict[str, Any]) -> TenantSubscription:
    return TenantSubscription(
        id=str(row["id"]),
        tenantId=str(row["tenant_id"]),
        planId=str(row["plan_id"]),
        status=str(row["status"]),
        billingPeriod=str(row["billing_period"]),
        currentPeriodStart=str(row["current_period_start"]),
        currentPeriodEnd=(
            str(row["current_period_end"]) if row["current_period_end"] is not None else None
        ),
        cancelAtPeriodEnd=bool(row["cancel_at_period_end"]),
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )
