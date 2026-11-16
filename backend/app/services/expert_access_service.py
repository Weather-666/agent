from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.plans import Plan
from app.services.plan_repository import PlanRepository
from app.services.subscription_service import SubscriptionService


@dataclass(frozen=True)
class ExpertAccess:
    all_experts: bool
    expert_ids: frozenset[str]

    def allows(self, expert_id: str) -> bool:
        return self.all_experts or expert_id in self.expert_ids


class ExpertAccessService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.plan_repo = PlanRepository(connection)
        self.subscription_service = SubscriptionService(connection)

    def current_access(self, tenant_id: str) -> ExpertAccess:
        subscription = self.subscription_service.ensure_default_subscription(tenant_id)
        plan = self.plan_repo.get(subscription.planId)
        if plan is None:
            raise ApiError(404, "PLAN_NOT_FOUND", "Plan not found")
        access = _access_from_plan(plan)
        self.connection.commit()
        return access

    def require_access(self, tenant_id: str, expert_id: str) -> None:
        if not self.current_access(tenant_id).allows(expert_id):
            raise ApiError(
                403,
                "EXPERT_NOT_INCLUDED_IN_PLAN",
                "Expert is not included in the current plan",
            )


def _access_from_plan(plan: Plan) -> ExpertAccess:
    if plan.entitlements is None:
        raise ApiError(
            409,
            "PLAN_CREDIT_ENTITLEMENT_REQUIRED",
            "Plan requires valid credit entitlements",
        )
    return ExpertAccess(
        all_experts=plan.entitlements.allExperts,
        expert_ids=frozenset(plan.expertIds),
    )
