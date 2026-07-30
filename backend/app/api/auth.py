"""Auth routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import security
from ..models import LoginRequest, TokenResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    if not security.authenticate(body.username, body.password):
        raise HTTPException(401, "Invalid username or password")
    return TokenResponse(access_token=security.issue_token(body.username), username=body.username)
