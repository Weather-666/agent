from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import (
    get_auth_service,
    get_password_reset_service,
    get_profile_service,
    get_profile_storage_service,
    get_request_id,
    require_principal,
)
from app.domain.auth import (
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirmRequest,
    PasswordResetMessageResponse,
    PasswordResetRequest,
    Principal,
    RefreshRequest,
)
from app.domain.profile import CurrentUserProfile, UpdateCurrentUserProfileRequest
from app.services.auth_service import AuthService
from app.services.password_reset_service import PasswordResetService
from app.services.profile_service import ProfileService

router = APIRouter()


@router.post("/login")
async def login(
    body: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
    request_id: str = Depends(get_request_id),
) -> dict:
    return auth.login(body.email, body.password, body.tenantId, request_id=request_id)


@router.get("/me", response_model=CurrentUserProfile)
async def get_current_profile(
    principal: Principal = Depends(require_principal),
    profile: ProfileService = Depends(get_profile_service),
) -> CurrentUserProfile:
    return profile.get_profile(principal.user_id)


@router.patch("/me", response_model=CurrentUserProfile)
async def update_current_profile(
    body: UpdateCurrentUserProfileRequest,
    principal: Principal = Depends(require_principal),
    profile: ProfileService = Depends(get_profile_service),
) -> CurrentUserProfile:
    return profile.update_profile(principal.user_id, body)


@router.put("/me/avatar", response_model=CurrentUserProfile)
async def upload_current_avatar(
    principal: Principal = Depends(require_principal),
    profile: ProfileService = Depends(get_profile_storage_service),
    file: UploadFile = File(...),
) -> CurrentUserProfile:
    filename = file.filename or ""
    content_type = file.content_type
    try:
        data = await file.read(profile.avatar_max_upload_bytes + 1)
    finally:
        await file.close()
    return profile.upload_avatar(
        principal.user_id,
        filename=filename,
        content_type=content_type,
        data=data,
    )


@router.delete("/me/avatar", response_model=CurrentUserProfile)
async def delete_current_avatar(
    principal: Principal = Depends(require_principal),
    profile: ProfileService = Depends(get_profile_storage_service),
) -> CurrentUserProfile:
    return profile.delete_avatar(principal.user_id)


@router.post("/refresh")
async def refresh(body: RefreshRequest, auth: AuthService = Depends(get_auth_service)) -> dict:
    return auth.refresh(body.refreshToken, body.tenantId)


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    auth.logout(body.refreshToken)
    return None


@router.post(
    "/password-reset/request",
    response_model=PasswordResetMessageResponse,
    status_code=202,
)
def request_password_reset(
    body: PasswordResetRequest,
    service: PasswordResetService = Depends(get_password_reset_service),
) -> PasswordResetMessageResponse:
    return PasswordResetMessageResponse(
        message=service.request_code(str(body.email), body.locale)
    )


@router.post(
    "/password-reset/confirm",
    response_model=PasswordResetMessageResponse,
)
def confirm_password_reset(
    body: PasswordResetConfirmRequest,
    service: PasswordResetService = Depends(get_password_reset_service),
) -> PasswordResetMessageResponse:
    return PasswordResetMessageResponse(
        message=service.confirm(str(body.email), body.code, body.newPassword)
    )
