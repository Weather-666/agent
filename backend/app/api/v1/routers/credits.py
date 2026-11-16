from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import (
    get_database,
    get_request_id,
    require_platform_permission,
    require_tenant_principal,
)
from app.core.config import Settings, get_settings
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.credits import (
    AdminCreditSummary,
    CreditAdjustmentRequest,
    CreditLedgerEntry,
    CreditLedgerListResponse,
    CreditSummary,
)
from app.services.credit_service import CreditService


router = APIRouter()
tenant_router = APIRouter()


@router.get("/current", response_model=CreditSummary)
async def get_current_credits(
    principal: Principal = Depends(require_tenant_principal),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> CreditSummary:
    return CreditService(connection, settings).get_current_summary(
        str(principal.active_tenant_id), user_id=principal.user_id
    )


@tenant_router.get(
    "/{tenant_id}/credits/current",
    response_model=AdminCreditSummary,
    responses={400: {"description": "CREDIT_USER_SCOPE_UNSUPPORTED"}},
)
async def get_tenant_current_credits(
    tenant_id: str,
    user_id: str | None = Query(default=None, alias="userId"),
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AdminCreditSummary:
    return CreditService(connection, settings).get_current_summary(
        tenant_id, admin=True, user_id=user_id
    )


@tenant_router.get(
    "/{tenant_id}/credits/ledger",
    response_model=CreditLedgerListResponse,
    responses={400: {"description": "CREDIT_USER_SCOPE_UNSUPPORTED"}},
)
async def list_tenant_credit_ledger(
    tenant_id: str,
    user_id: str | None = Query(default=None, alias="userId"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> CreditLedgerListResponse:
    items, total = CreditService(connection, settings).list_ledger(
        tenant_id, page=page, page_size=page_size, user_id=user_id
    )
    return CreditLedgerListResponse(items=items, total=total, page=page, pageSize=page_size)


@tenant_router.post(
    "/{tenant_id}/credits/adjustments",
    response_model=CreditLedgerEntry,
    responses={
        400: {
            "description": "CREDIT_USER_REQUIRED or CREDIT_USER_SCOPE_UNSUPPORTED"
        },
        409: {
            "description": (
                "CREDIT_ADJUSTMENT_EXCEEDS_BALANCE or IDEMPOTENCY_KEY_REUSED"
            )
        }
    },
)
async def adjust_tenant_credits(
    tenant_id: str,
    body: CreditAdjustmentRequest,
    user_id: str | None = Query(default=None, alias="userId"),
    idempotency_key: str = Header(alias="Idempotency-Key"),
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    request_id: str = Depends(get_request_id),
) -> CreditLedgerEntry:
    return CreditService(connection, settings).adjust_current_period(
        principal,
        tenant_id,
        amount=body.amount,
        reason=body.reason,
        idempotency_key=idempotency_key,
        request_id=request_id,
        user_id=user_id,
    )
