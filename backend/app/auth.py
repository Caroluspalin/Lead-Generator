# FILE: backend/app/auth.py
"""Supabase JWT -autentikaatio FastAPI Depends -funktiona.

Tukee kahta algoritmia:
- ES256/RS256 (uudet Supabase-projektit): verifioi julkisilla avaimilla JWKS-endpointista
- HS256 (legacy): verifioi SUPABASE_JWT_SECRET-salaisuudella
"""
import logging
import os
import ssl
from typing import Optional

import certifi
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"

_bearer_scheme = HTTPBearer(auto_error=False)

# JWKS-client alustetaan lazyna — PyJWKClient cachettaa avaimet automaattisesti
_jwks_client: Optional[PyJWKClient] = None

def _get_jwks_client() -> Optional[PyJWKClient]:
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        # macOS-venvissä Pythonilla ei ole CA-bundlea — kaytetaan certifin bundlea
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, ssl_context=ssl_context)
    return _jwks_client


class AuthUser(BaseModel):
    """Suppea kuvaus kirjautuneesta kayttajasta (JWT-payloadista)."""
    id: str
    email: Optional[str] = None
    role: Optional[str] = None


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthUser:
    """FastAPI-dependency: vaatii validin Supabase-JWT:n Authorization-headerissa."""
    if AUTH_DISABLED:
        return AuthUser(id="dev-user", email="dev@local", role="authenticated")

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Tunnista algoritmi tokenin headerista
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "")
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT headerin luku epaonnistui: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        if alg in ("ES256", "RS256", "ES384", "RS384"):
            # Asymmetrinen avain — JWKS
            jwks_client = _get_jwks_client()
            if not jwks_client:
                logger.error("SUPABASE_URL puuttuu — JWKS-verifiointi ei onnistu")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Auth not configured (SUPABASE_URL missing)",
                )
            signing_key = jwks_client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[alg],
                audience=SUPABASE_JWT_AUDIENCE,
            )
        elif alg == "HS256":
            # Legacy symmetrinen secret
            if not SUPABASE_JWT_SECRET:
                logger.error("SUPABASE_JWT_SECRET puuttuu — HS256-verifiointi ei onnistu")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Auth not configured (SUPABASE_JWT_SECRET missing)",
                )
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience=SUPABASE_JWT_AUDIENCE,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported JWT algorithm: {alg}",
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
