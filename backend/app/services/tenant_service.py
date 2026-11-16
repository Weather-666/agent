from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, get_args
from uuid import uuid4

from app.core.errors import ApiError
from app.core.config import Settings
from app.db import DatabaseConnection
from app.domain.audit import (
    AuditCategory,
    AuditOperationType,
    AuditResource,
    AuditTenant,
)
from app.domain.auth import Principal, TenantRole
from app.domain.plans import BillingPeriod, CurrentSubscriptionResponse, Plan
from app.domain.tenants import (
    AddTenantMemberRequest,
    CreateTenantRequest,
    FilterOption,
    Tenant,
    TenantFilterOptionsResponse,
    TenantMember,
    TenantMonthlyCreditsSummary,
    TenantOrderSummary,
    TenantPlanSummary,
    TenantSubscriptionSummary,
    TenantType,
    UpdateTenantMemberRequest,
    UpdateTenantSubscriptionRequest,
    UpdateTenantRequest,
)
from app.services._sql import (
    execute,
    fetch_all,
    fetch_one,
    is_unique_violation,
    rowcount,
)
from app.services.plan_repository import PlanRepository
from app.services.plan_pricing import select_price_snapshot
from app.services.subscription_service import SubscriptionService
from app.services.subscription_repository import SubscriptionRepository
from app.services.subscription_status import (
    TENANT_SUBSCRIPTION_MANAGEMENT_STATUSES,
    subscription_days_until_end,
    tenant_subscription_management_status,
)
from app.services.audit_service import AuditService, changes
from app.services.credit_service import CreditService

_BILLING_PERIOD_LABELS: dict[BillingPeriod, str] = {
    "free": "Free",
    "monthly": "Monthly",
    "yearly": "Yearly",
    "sales": "Sales",
}


class TenantService:
    def __init__(self, connection: DatabaseConnection, settings: Settings | None = None) -> None:
        self.connection = connection
        self.settings = settings or Settings(_env_file=None)
        self.plan_repo = PlanRepository(connection)
        self.subscription_repo = SubscriptionRepository(connection)
        self.subscription_service = SubscriptionService(connection)
        self.credit_service = CreditService(connection, self.settings)

    def list(
        self,
        *,
        search: str | None = None,
        tenant_type: str | None = None,
        subscription_type: BillingPeriod | None = None,
        subscription_status: str | None = None,
        sort: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Tenant], int]:
        rows = fetch_all(
            self.connection,
            """
            select
              t.id,
              t.type,
              t.name,
              t.slug,
              t.owner_user_id,
              owner.name as owner_user_name,
              owner.email as owner_user_email,
              t.status,
              t.created_at,
              t.updated_at,
              count(tm.id) as member_count
            from tenants t
            left join users owner on owner.id = t.owner_user_id
            left join tenant_members tm on tm.tenant_id = t.id
            group by
              t.id, t.type, t.name, t.slug, t.owner_user_id, owner.name, owner.email,
              t.status, t.created_at, t.updated_at
            order by t.created_at desc, t.id asc
            """,
        )
        items = [self._hydrate_tenant(_map_tenant(row), include_members=False) for row in rows]
        items = _filter_tenants(
            items,
            search=search,
            tenant_type=tenant_type,
            subscription_type=subscription_type,
            subscription_status=subscription_status,
        )
        items = _sort_tenants(items, sort)
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def filter_options(self) -> TenantFilterOptionsResponse:
        """Options backing the tenant-list filter dropdowns.

        All three filters use fixed stable vocabularies. Subscription type means billing period,
        so each option value can be passed directly as `subscriptionType`.
        """
        return TenantFilterOptionsResponse(
            tenantTypes=list(get_args(TenantType)),
            subscriptionStatuses=list(TENANT_SUBSCRIPTION_MANAGEMENT_STATUSES),
            subscriptionTypes=[
                FilterOption(value=period, label=_BILLING_PERIOD_LABELS[period])
                for period in get_args(BillingPeriod)
            ],
        )

    def get(self, tenant_id: str) -> Tenant:
        row = self._tenant_row(tenant_id)
        if not row:
            raise ApiError(404, "TENANT_NOT_FOUND", "Tenant not found")
        tenant = _map_tenant(row)
        return self._hydrate_tenant(tenant, include_members=tenant.type == "team")

    def create(
        self,
        principal: Principal,
        request: CreateTenantRequest,
        *,
        request_id: str,
    ) -> Tenant:
        owner = self._require_user(request.ownerUserId)
        tenant_id = f"tenant_{uuid4().hex}"
        slug = request.slug or _tenant_slug(request.name)
        audit = AuditService(self.connection)
        audit_context = audit.context(principal, request_id)
        try:
            execute(
                self.connection,
                """
                insert into tenants (id, type, name, slug, owner_user_id, status)
                values (?, 'team', ?, ?, ?, 'active')
                """,
                (tenant_id, request.name, slug, owner["id"]),
            )
            self._upsert_member(tenant_id, str(owner["id"]), TenantRole.ADMIN)
            self.subscription_service.ensure_default_subscription(tenant_id)
            audit.record(
                audit_context,
                category=AuditCategory.TENANT,
                action="tenant.create",
                operation_type=AuditOperationType.CREATE,
                tenant=AuditTenant(id=tenant_id, name=request.name),
                resource=AuditResource(type="tenant", id=tenant_id, name=request.name),
                metadata={
                    "type": "team",
                    "slug": slug,
                    "ownerUserId": str(owner["id"]),
                },
            )
            self.connection.commit()
        except Exception as exc:
            if is_unique_violation(exc):
                raise ApiError(409, "TENANT_SLUG_EXISTS", "Tenant slug already exists") from exc
            raise
        return self.get(tenant_id)

    def update(
        self,
        principal: Principal,
        tenant_id: str,
        request: UpdateTenantRequest,
        *,
        request_id: str,
    ) -> Tenant:
        current = self.get(tenant_id)
        next_name = request.name if request.name is not None else current.name
        next_slug = request.slug if request.slug is not None else current.slug
        next_owner_id = (
            request.ownerUserId if request.ownerUserId is not None else current.ownerUserId
        )

        if next_owner_id is not None:
            self._require_user(next_owner_id)
        event_changes = changes(
            {
                "name": current.name,
                "slug": current.slug,
                "ownerUserId": current.ownerUserId,
            },
            {"name": next_name, "slug": next_slug, "ownerUserId": next_owner_id},
            {"name", "slug", "ownerUserId"},
        )
        audit = AuditService(self.connection)
        audit_context = audit.context(principal, request_id)

        try:
            execute(
                self.connection,
                """
                update tenants
                set name = ?, slug = ?, owner_user_id = ?, updated_at = CURRENT_TIMESTAMP
                where id = ?
                """,
                (next_name, next_slug, next_owner_id, tenant_id),
            )
            if next_owner_id is not None and next_owner_id != current.ownerUserId:
                self._upsert_member(tenant_id, next_owner_id, TenantRole.ADMIN)
            if event_changes:
                audit.record(
                    audit_context,
                    category=AuditCategory.TENANT,
                    action="tenant.update",
                    operation_type=AuditOperationType.UPDATE,
                    tenant=AuditTenant(id=tenant_id, name=next_name),
                    resource=AuditResource(type="tenant", id=tenant_id, name=next_name),
                    changes=event_changes,
                )
            self.connection.commit()
        except Exception as exc:
            if is_unique_violation(exc):
                raise ApiError(409, "TENANT_SLUG_EXISTS", "Tenant slug already exists") from exc
            raise
        return self.get(tenant_id)

    def update_status(
        self,
        principal: Principal,
        tenant_id: str,
        status: str,
        *,
        request_id: str,
    ) -> Tenant:
        current = self.get(tenant_id)
        event_changes = changes({"status": current.status}, {"status": status}, {"status"})
        execute(
            self.connection,
            """
            update tenants
            set status = ?, updated_at = CURRENT_TIMESTAMP
            where id = ?
            """,
            (status, tenant_id),
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.TENANT,
                action="tenant.status_change",
                operation_type=AuditOperationType.UPDATE,
                tenant=AuditTenant(id=tenant_id, name=current.name),
                resource=AuditResource(type="tenant", id=tenant_id, name=current.name),
                changes=event_changes,
            )
        self.connection.commit()
        return self.get(tenant_id)

    def update_subscription(
        self,
        principal: Principal,
        tenant_id: str,
        request: UpdateTenantSubscriptionRequest,
        *,
        request_id: str,
    ) -> Tenant:
        current = self.get(tenant_id)
        plan = self.plan_repo.get(request.planId)
        if not plan:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        if plan.entitlements is None:
            raise ApiError(
                409,
                "PLAN_CREDIT_ENTITLEMENT_REQUIRED",
                "Plan requires valid credit entitlements",
            )
        billing_period = request.billingPeriod
        _require_enabled_price(plan, billing_period)
        now = _now_iso()
        current_period_start = request.currentPeriodStart or now
        subscription_id = f"tenant_subscription_{uuid4().hex}"
        execute(
            self.connection,
            """
            update subscriptions
            set status = 'cancelled',
                current_period_end = coalesce(current_period_end, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            where tenant_id = ?
              and status in ('active', 'trialing', 'past_due')
            """,
            (tenant_id,),
        )
        execute(
            self.connection,
            """
            insert into subscriptions (
              id, tenant_id, plan_id, status, billing_period,
              current_period_start, current_period_end, cancel_at_period_end
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subscription_id,
                tenant_id,
                plan.id,
                request.status,
                billing_period,
                current_period_start,
                request.currentPeriodEnd,
                request.cancelAtPeriodEnd,
            ),
        )
        if plan.entitlements.teamLibraryEnabled:
            self.subscription_repo.record_team_library_entitlements_for_plan(
                plan.id, plan.entitlements.teamLibraryQuotaBytes
            )
        self.credit_service.apply_current_plan_limit(tenant_id)
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.TENANT,
            action="tenant.subscription_change",
            operation_type=AuditOperationType.UPDATE,
            tenant=AuditTenant(id=tenant_id, name=current.name),
            resource=AuditResource(type="tenant", id=tenant_id, name=current.name),
            changes=changes(
                {"subscription": _subscription_audit_summary(current)},
                {
                    "subscription": {
                        "planId": plan.id,
                        "planCode": plan.code,
                        "planName": plan.name,
                        "billingPeriod": billing_period,
                        "status": request.status,
                        "currentPeriodStart": current_period_start,
                        "currentPeriodEnd": request.currentPeriodEnd,
                        "cancelAtPeriodEnd": request.cancelAtPeriodEnd,
                    }
                },
                {"subscription"},
            ),
        )
        self.connection.commit()
        return self.get(tenant_id)

    def upgrade_current_subscription(
        self,
        principal: Principal,
        tenant_id: str,
        target_plan_id: str,
        *,
        request_id: str,
    ) -> CurrentSubscriptionResponse:
        current = self.subscription_service.current_subscription(tenant_id)
        if target_plan_id == current.plan.id:
            return current

        target = self.plan_repo.get(target_plan_id)
        if target is None or target.status != "active":
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        if target.level <= current.plan.level:
            raise ApiError(
                409,
                "PLAN_NOT_UPGRADE",
                "Self-service subscription changes must upgrade the current plan",
            )

        price = next((item for item in target.prices if item.isEnabled), None)
        if price is None or price.billingPeriod == "sales":
            raise ApiError(
                409,
                "PLAN_SELF_SERVICE_UNAVAILABLE",
                "The selected plan is not available for self-service subscription",
            )

        self.update_subscription(
            principal,
            tenant_id,
            UpdateTenantSubscriptionRequest(
                planId=target.id,
                billingPeriod=price.billingPeriod,
            ),
            request_id=request_id,
        )
        return self.subscription_service.current_subscription(tenant_id)

    def list_members(self, tenant_id: str) -> list[TenantMember]:
        self._require_team_tenant(tenant_id)
        return self._list_members_raw(tenant_id)

    def _list_members_raw(self, tenant_id: str) -> list[TenantMember]:
        rows = fetch_all(
            self.connection,
            """
            select
              u.id as user_id,
              u.email,
              u.name,
              u.status,
              tm.role,
              tm.created_at as joined_at
            from tenant_members tm
            inner join users u on u.id = tm.user_id
            where tm.tenant_id = ?
            order by tm.created_at desc, u.id asc
            """,
            (tenant_id,),
        )
        return [_map_member(row) for row in rows]

    def add_member(
        self,
        principal: Principal,
        tenant_id: str,
        request: AddTenantMemberRequest,
        *,
        request_id: str,
    ) -> TenantMember:
        self._lock_membership_write(tenant_id, request.userId)
        tenant = self._require_team_tenant(tenant_id)
        user = self._require_user(request.userId)
        if str(user.get("status")) != "active":
            raise ApiError(409, "TENANT_MEMBER_USER_DISABLED", "Only active users can join a team")
        current = self._member_or_none(tenant_id, request.userId)
        if tenant_id != "tenant_default":
            seat_limit = self._require_team_management_entitlement(tenant_id)
            self._require_single_team_membership(tenant_id, request.userId)
            if current is None and self._count_tenant_members(tenant_id) >= seat_limit:
                raise ApiError(
                    409,
                    "TENANT_SEAT_LIMIT_EXCEEDED",
                    "Tenant seat limit has been reached",
                    {"seatLimit": seat_limit},
                )
        self._upsert_member(tenant_id, request.userId, request.role)
        updated = self._require_member(tenant_id, request.userId)
        audit = AuditService(self.connection)
        audit_context = audit.context(principal, request_id)
        if current is None:
            audit.record(
                audit_context,
                category=AuditCategory.TENANT_MEMBER,
                action="tenant_member.add",
                operation_type=AuditOperationType.CREATE,
                tenant=AuditTenant(id=tenant.id, name=tenant.name),
                resource=AuditResource(type="user", id=updated.userId, name=updated.name),
                metadata={
                    "userId": updated.userId,
                    "email": updated.email,
                    "role": updated.role.value,
                },
            )
        elif current.role != updated.role:
            audit.record(
                audit_context,
                category=AuditCategory.TENANT_MEMBER,
                action="tenant_member.role_change",
                operation_type=AuditOperationType.UPDATE,
                tenant=AuditTenant(id=tenant.id, name=tenant.name),
                resource=AuditResource(type="user", id=updated.userId, name=updated.name),
                changes=changes(
                    {"role": current.role.value},
                    {"role": updated.role.value},
                    {"role"},
                ),
                metadata={"userId": updated.userId, "email": updated.email},
            )
        self.connection.commit()
        return updated

    def update_member(
        self,
        principal: Principal,
        tenant_id: str,
        user_id: str,
        request: UpdateTenantMemberRequest,
        *,
        request_id: str,
    ) -> TenantMember:
        tenant = self._require_team_tenant(tenant_id)
        current = self._require_member(tenant_id, user_id)
        if (
            current.role == TenantRole.ADMIN
            and request.role != TenantRole.ADMIN
            and self._count_tenant_admins(tenant_id) <= 1
        ):
            raise ApiError(409, "TENANT_LAST_ADMIN", "Cannot demote the last tenant admin")
        self._upsert_member(tenant_id, user_id, request.role)
        updated = self._require_member(tenant_id, user_id)
        if current.role != updated.role:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.TENANT_MEMBER,
                action="tenant_member.role_change",
                operation_type=AuditOperationType.UPDATE,
                tenant=AuditTenant(id=tenant.id, name=tenant.name),
                resource=AuditResource(type="user", id=updated.userId, name=updated.name),
                changes=changes(
                    {"role": current.role.value},
                    {"role": updated.role.value},
                    {"role"},
                ),
                metadata={"userId": updated.userId, "email": updated.email},
            )
        self.connection.commit()
        return updated

    def remove_member(
        self,
        principal: Principal,
        tenant_id: str,
        user_id: str,
        *,
        request_id: str,
    ) -> None:
        tenant = self._require_team_tenant(tenant_id)
        current = self._require_member(tenant_id, user_id)
        if current.role == TenantRole.ADMIN and self._count_tenant_admins(tenant_id) <= 1:
            raise ApiError(409, "TENANT_LAST_ADMIN", "Cannot remove the last tenant admin")
        cursor = execute(
            self.connection,
            "delete from tenant_members where tenant_id = ? and user_id = ?",
            (tenant_id, user_id),
        )
        if rowcount(cursor) <= 0:
            raise ApiError(404, "MEMBER_NOT_FOUND", "User is not a member of this tenant")
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.TENANT_MEMBER,
            action="tenant_member.remove",
            operation_type=AuditOperationType.DELETE,
            tenant=AuditTenant(id=tenant.id, name=tenant.name),
            resource=AuditResource(type="user", id=current.userId, name=current.name),
            metadata={
                "userId": current.userId,
                "email": current.email,
                "role": current.role.value,
            },
        )
        self.connection.commit()

    def _tenant_row(self, tenant_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select
              t.id,
              t.type,
              t.name,
              t.slug,
              t.owner_user_id,
              owner.name as owner_user_name,
              owner.email as owner_user_email,
              t.status,
              t.created_at,
              t.updated_at,
              count(tm.id) as member_count
            from tenants t
            left join users owner on owner.id = t.owner_user_id
            left join tenant_members tm on tm.tenant_id = t.id
            where t.id = ?
            group by
              t.id, t.type, t.name, t.slug, t.owner_user_id, owner.name, owner.email,
              t.status, t.created_at, t.updated_at
            limit 1
            """,
            (tenant_id,),
        )

    def _require_user(self, user_id: str) -> dict[str, Any]:
        row = fetch_one(
            self.connection,
            "select id, status from users where id = ? limit 1",
            (user_id,),
        )
        if not row:
            raise ApiError(404, "USER_NOT_FOUND", "User not found")
        return row

    def _require_member(self, tenant_id: str, user_id: str) -> TenantMember:
        member = self._member_or_none(tenant_id, user_id)
        if not member:
            raise ApiError(404, "MEMBER_NOT_FOUND", "User is not a member of this tenant")
        return member

    def _member_or_none(self, tenant_id: str, user_id: str) -> TenantMember | None:
        row = fetch_one(
            self.connection,
            """
            select
              u.id as user_id,
              u.email,
              u.name,
              u.status,
              tm.role,
              tm.created_at as joined_at
            from tenant_members tm
            inner join users u on u.id = tm.user_id
            where tm.tenant_id = ? and tm.user_id = ?
            limit 1
            """,
            (tenant_id, user_id),
        )
        return _map_member(row) if row else None

    def _upsert_member(self, tenant_id: str, user_id: str, role: TenantRole) -> None:
        execute(
            self.connection,
            """
            insert into tenant_members (id, tenant_id, user_id, role)
            values (?, ?, ?, ?)
            on conflict (tenant_id, user_id) do update
            set role = excluded.role,
                updated_at = CURRENT_TIMESTAMP
            """,
            (f"member_{uuid4().hex}", tenant_id, user_id, role.value),
        )

    def _count_tenant_admins(self, tenant_id: str) -> int:
        row = fetch_one(
            self.connection,
            "select count(*) as count from tenant_members where tenant_id = ? and role = ?",
            (tenant_id, TenantRole.ADMIN.value),
        )
        return int(row["count"]) if row else 0

    def _count_tenant_members(self, tenant_id: str) -> int:
        row = fetch_one(
            self.connection,
            "select count(*) as count from tenant_members where tenant_id = ?",
            (tenant_id,),
        )
        return int(row["count"]) if row else 0

    def _lock_membership_write(self, tenant_id: str, user_id: str) -> None:
        if isinstance(self.connection, sqlite3.Connection):
            if not self.connection.in_transaction:
                self.connection.execute("begin immediate")
            return
        fetch_one(self.connection, "select id from tenants where id = ? for update", (tenant_id,))
        fetch_one(self.connection, "select id from users where id = ? for update", (user_id,))

    def _require_team_management_entitlement(self, tenant_id: str) -> int:
        subscription = self.subscription_repo.get_current(tenant_id)
        if subscription is None:
            raise ApiError(
                403,
                "TENANT_TEAM_MANAGEMENT_NOT_ENTITLED",
                "An active team-management plan is required",
            )
        plan = self.plan_repo.get(subscription.planId)
        entitlements = plan.entitlements if plan is not None else None
        if entitlements is None or not bool(entitlements.features.get("teamManagement", False)):
            raise ApiError(
                403,
                "TENANT_TEAM_MANAGEMENT_NOT_ENTITLED",
                "An active team-management plan is required",
            )
        return entitlements.seatLimit

    def _require_single_team_membership(self, tenant_id: str, user_id: str) -> None:
        row = fetch_one(
            self.connection,
            """
            select t.id
            from tenant_members tm
            inner join tenants t on t.id = tm.tenant_id
            where tm.user_id = ? and tm.tenant_id <> ?
              and t.type = 'team' and t.status = 'active' and t.id <> 'tenant_default'
            limit 1
            """,
            (user_id, tenant_id),
        )
        if row is not None:
            raise ApiError(
                409,
                "TENANT_USER_ALREADY_IN_TEAM",
                "User already belongs to another active team tenant",
            )

    def _require_team_tenant(self, tenant_id: str) -> Tenant:
        row = self._tenant_row(tenant_id)
        if not row:
            raise ApiError(404, "TENANT_NOT_FOUND", "Tenant not found")
        tenant = _map_tenant(row)
        if tenant.type != "team":
            raise ApiError(
                409,
                "TENANT_MEMBERS_UNSUPPORTED",
                "Member management is only available for team tenants",
            )
        return tenant

    def _hydrate_tenant(self, tenant: Tenant, *, include_members: bool) -> Tenant:
        subscription, plan, monthly_credits = self._tenant_subscription_context(tenant.id)
        tenant.currentSubscription = subscription
        tenant.currentPlan = plan
        tenant.monthlyCredits = monthly_credits
        tenant.orderSummary = TenantOrderSummary()
        tenant.members = self._list_members_raw(tenant.id) if include_members else []
        return tenant

    def _tenant_subscription_context(
        self, tenant_id: str
    ) -> tuple[
        TenantSubscriptionSummary | None,
        TenantPlanSummary | None,
        TenantMonthlyCreditsSummary,
    ]:
        subscription = self.subscription_repo.get_latest_for_management(tenant_id)
        if subscription is None:
            return None, None, TenantMonthlyCreditsSummary()
        plan_config = self.plan_repo.get(subscription.planId)
        if plan_config is None:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        price_snapshot = select_price_snapshot(plan_config, subscription.billingPeriod)
        entitlements = _entitlements_dict(plan_config)
        now = datetime.now(timezone.utc)
        status = tenant_subscription_management_status(
            subscription.status,
            subscription.currentPeriodEnd,
            now=now,
        )
        summary = TenantSubscriptionSummary(
            subscriptionId=subscription.id,
            planId=subscription.planId,
            planCode=plan_config.code,
            planName=plan_config.name,
            billingPeriod=subscription.billingPeriod,
            status=status,
            rawStatus=subscription.status,
            currentPeriodStart=subscription.currentPeriodStart,
            currentPeriodEnd=subscription.currentPeriodEnd,
            daysUntilExpiry=subscription_days_until_end(
                subscription.currentPeriodEnd,
                now=now,
            ),
            cancelAtPeriodEnd=subscription.cancelAtPeriodEnd,
            autoRenew=not subscription.cancelAtPeriodEnd and subscription.billingPeriod != "free",
            priceLabel=_price_label(price_snapshot),
        )
        plan = TenantPlanSummary(
            id=subscription.planId,
            code=plan_config.code,
            name=plan_config.name,
            typeLabel=plan_config.typeLabel,
            billingPeriod=subscription.billingPeriod,
            priceLabel=summary.priceLabel,
            priceSnapshot=price_snapshot,
            entitlementsSnapshot=entitlements,
        )
        active_subscription = self.subscription_repo.get_current(tenant_id)
        if active_subscription is None:
            monthly_credits = TenantMonthlyCreditsSummary()
        else:
            credit_summary = self.credit_service.get_current_summary(tenant_id)
            monthly_credits = TenantMonthlyCreditsSummary(
                monthlyCreditLimit=credit_summary.monthlyCreditLimit,
                estimatedUsedCredits=credit_summary.estimatedUsedCredits,
                deductedCredits=credit_summary.deductedCredits,
                remainingCredits=credit_summary.remainingCredits,
                enforcementEnabled=credit_summary.enforcementEnabled,
            )
        return summary, plan, monthly_credits


def _map_tenant(row: dict[str, Any]) -> Tenant:
    return Tenant(
        id=str(row["id"]),
        type=str(row["type"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        ownerUserId=str(row["owner_user_id"]) if row["owner_user_id"] is not None else None,
        ownerUserName=(
            str(row["owner_user_name"]) if row.get("owner_user_name") is not None else None
        ),
        ownerUserEmail=(
            str(row["owner_user_email"]) if row.get("owner_user_email") is not None else None
        ),
        status=str(row["status"]),
        memberCount=int(row["member_count"]),
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )


def _map_member(row: dict[str, Any]) -> TenantMember:
    return TenantMember(
        userId=str(row["user_id"]),
        email=str(row["email"]),
        name=str(row["name"]),
        status=str(row["status"]),
        role=TenantRole(str(row["role"])),
        joinedAt=str(row["joined_at"]),
    )


def _tenant_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug or 'tenant'}-{uuid4().hex[:8]}"


def _filter_tenants(
    items: list[Tenant],
    *,
    search: str | None,
    tenant_type: str | None,
    subscription_type: BillingPeriod | None,
    subscription_status: str | None,
) -> list[Tenant]:
    if search:
        needle = search.casefold()
        items = [
            item
            for item in items
            if needle in item.name.casefold()
            or needle in item.slug.casefold()
            or (item.ownerUserName is not None and needle in item.ownerUserName.casefold())
            or (item.ownerUserEmail is not None and needle in item.ownerUserEmail.casefold())
            or (
                item.currentPlan is not None
                and (
                    needle in item.currentPlan.name.casefold()
                    or needle in item.currentPlan.code.casefold()
                )
            )
        ]
    if tenant_type:
        items = [item for item in items if item.type == tenant_type]
    if subscription_type:
        items = [
            item
            for item in items
            if item.currentSubscription is not None
            and item.currentSubscription.billingPeriod == subscription_type
        ]
    if subscription_status:
        items = [
            item
            for item in items
            if item.currentSubscription is not None
            and item.currentSubscription.status == subscription_status
        ]
    return items


def _sort_tenants(items: list[Tenant], sort: str | None) -> list[Tenant]:
    if sort == "expiresAt":
        return sorted(
            items,
            key=lambda item: (
                item.currentSubscription is None
                or item.currentSubscription.currentPeriodEnd is None,
                item.currentSubscription.currentPeriodEnd if item.currentSubscription else "",
            ),
        )
    if sort == "monthlyCredits":
        return sorted(
            items, key=lambda item: item.monthlyCredits.estimatedUsedCredits, reverse=True
        )
    if sort == "subscriptionStart":
        return sorted(
            items,
            key=lambda item: (
                item.currentSubscription.currentPeriodStart
                if item.currentSubscription is not None
                else ""
            ),
            reverse=True,
        )
    if sort == "name":
        return sorted(items, key=lambda item: (item.name.casefold(), item.id))
    return items


def _require_enabled_price(plan: Plan, billing_period: str) -> None:
    if any(price.billingPeriod == billing_period and price.isEnabled for price in plan.prices):
        return
    raise ApiError(
        400,
        "PLAN_PRICE_NOT_AVAILABLE",
        "The selected plan does not have an enabled price for this billing period",
    )


def _price_label(price_snapshot: dict[str, Any]) -> str | None:
    if price_snapshot.get("configured") is False:
        return "Price not configured"
    billing_period = str(price_snapshot.get("billingPeriod") or "")
    amount = int(price_snapshot.get("amountCents") or 0)
    currency = str(price_snapshot.get("currency") or "CNY")
    if billing_period == "free":
        return "Free"
    if billing_period == "sales":
        return "Contact sales"
    symbol = "¥" if currency == "CNY" else f"{currency} "
    suffix = {"monthly": " / month", "yearly": " / year"}.get(billing_period, "")
    return f"{symbol}{amount / 100:g}{suffix}"


def _entitlements_dict(plan: Plan) -> dict[str, Any]:
    entitlements = plan.entitlements
    return {
        "monthlyCreditLimit": entitlements.monthlyCreditLimit if entitlements else 0,
        "allExperts": entitlements.allExperts if entitlements else False,
        "seatLimit": entitlements.seatLimit if entitlements else 1,
        "singleTurnTokenLimit": entitlements.singleTurnTokenLimit if entitlements else None,
        "modelTiers": entitlements.modelTiers if entitlements else [],
        "features": entitlements.features if entitlements else {},
        "expertIds": plan.expertIds,
    }


def _subscription_audit_summary(tenant: Tenant) -> dict[str, Any] | None:
    subscription = tenant.currentSubscription
    if subscription is None:
        return None
    return {
        "planId": subscription.planId,
        "planCode": subscription.planCode,
        "planName": subscription.planName,
        "billingPeriod": subscription.billingPeriod,
        "status": subscription.rawStatus,
        "currentPeriodStart": subscription.currentPeriodStart,
        "currentPeriodEnd": subscription.currentPeriodEnd,
        "cancelAtPeriodEnd": subscription.cancelAtPeriodEnd,
    }


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
