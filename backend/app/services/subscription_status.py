"""Subscription status helpers for user and tenant-management views."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import get_args

from app.domain.plans import SubscriptionDisplayStatus, SubscriptionStatus
from app.domain.tenants import TenantSubscriptionManagementStatus


SUBSCRIPTION_DISPLAY_STATUSES: tuple[SubscriptionDisplayStatus, ...] = get_args(
    SubscriptionDisplayStatus
)
TENANT_SUBSCRIPTION_MANAGEMENT_STATUSES: tuple[TenantSubscriptionManagementStatus, ...] = (
    get_args(TenantSubscriptionManagementStatus)
)
EXPIRING_SOON_DAYS = 14


def normalize_subscription_status_filter(value: str) -> str:
    """Normalize the legacy three-state users-list filter."""
    normalized = value.casefold()
    if normalized == "expiringsoon":
        return "expiring_soon"
    return normalized


def tenant_subscription_management_status(
    raw_status: SubscriptionStatus,
    current_period_end: str | None,
    *,
    now: datetime | None = None,
) -> TenantSubscriptionManagementStatus:
    """Resolve the six-state tenant-management lifecycle status.

    A persisted terminal state wins first. For otherwise usable states, an ended period is expired.
    Trial and payment-delinquency states remain visible while the period is still open. Only an
    active subscription can become expiring-soon. `cancel_at_period_end` is intentionally absent:
    it controls renewal, not the status before the period actually ends.
    """
    if raw_status == "cancelled":
        return "cancelled"
    if raw_status == "expired":
        return "expired"

    reference = _utc(now or datetime.now(timezone.utc))
    period_end = _parse_datetime(current_period_end) if current_period_end is not None else None
    if period_end is not None and period_end <= reference:
        return "expired"
    if raw_status == "trialing":
        return "trialing"
    if raw_status == "past_due":
        return "past_due"
    if period_end is not None and period_end <= reference + timedelta(days=EXPIRING_SOON_DAYS):
        return "expiring_soon"
    return "active"


def subscription_days_until_end(
    current_period_end: str | None,
    *,
    now: datetime | None = None,
) -> int | None:
    if current_period_end is None:
        return None
    reference = _utc(now or datetime.now(timezone.utc))
    return (_parse_datetime(current_period_end) - reference).days


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return _utc(datetime.fromisoformat(normalized))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
