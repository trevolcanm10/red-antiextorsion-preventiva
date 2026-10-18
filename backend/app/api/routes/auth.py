from fastapi import APIRouter

from app.api.dependencies import AuthConfig, CurrentUser, Database, unauthorized
from app.core.security import create_access_token
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse
from app.services.auth import authenticate_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Database, settings: AuthConfig) -> TokenResponse:
    user = authenticate_user(db, payload.email, payload.password.get_secret_value())
    if user is None:
        raise unauthorized()
    return TokenResponse(
        access_token=create_access_token(user.id, user.organization_id, settings),
        expires_in=settings.JWT_ACCESS_TOKEN_MINUTES * 60,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(user)
