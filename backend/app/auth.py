# FILE: backend/app/auth.py
"""Supabase JWT -autentikaatio FastAPI Depends -funktiona.

Lukee Authorization: Bearer <token> -headerin, verifioi tokenin
Supabasen JWT-salaisuudella ja palauttaa dekoodatun payloadin.
"""
import logging
import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
# Supabase asettaa aud-claimiksi "authenticated" kaikille kirjautuneille kayttajille
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
# Dev-kytkin: ohittaa auth:n kokonaan paikallisessa kehityksessa
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"

_bearer_scheme = HTTPBearer(auto_error=False)


class AuthUser(BaseModel):
    """Suppea kuvaus kirjautuneesta kayttajasta (JWT-payloadista)."""
    id: str
    email: Optional[str] = None
    role: Optional[str] = None


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthUser:
    """FastAPI-dependency: vaatii validin Supabase-JWT:n Authorization-headerissa.

    Dev-tilassa (AUTH_DISABLED=true) palauttaa dummy-kayttajan ilman verifiointia.
    """
    if AUTH_DISABLED:
        return AuthUser(id="dev-user", email="dev@local", role="authenticated")

    if not SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET puuttuu — auth ei voi toimia")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth not configured on server",
        )

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=SUPABASE_JWT_AUDIENCE,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT verifiointi epaonnistui: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    return AuthUser(
        id=user_id,
        email=payload.get("email"),
        role=payload.get("role"),
    )
