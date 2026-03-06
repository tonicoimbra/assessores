"""Web authentication utilities via JWT."""

from __future__ import annotations

import datetime
import os
import secrets
from typing import Any, Dict, Optional

import jwt

from src.config import WEB_AUTH_TOKEN

# If no JWT_SECRET_KEY is provided, generate a random one for the lifecycle of the app
# In production with multiple workers, a fixed JWT_SECRET_KEY in .env is mandatory
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"


def generate_jwt_token(expires_hours: int = 12) -> str:
    """Generate a JWT session token valid for the given hours."""
    now = datetime.datetime.now(datetime.timezone.utc)
    expiration = now + datetime.timedelta(hours=expires_hours)
    
    payload = {
        "sub": "assessor",  # subject
        "iat": now,        # issued at
        "exp": expiration  # expiration time
    }
    
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a JWT token and return its decoded payload.
    
    Returns None if the token is invalid or expired.
    """
    if not token:
        return None
        
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def verify_login_password(password: str) -> bool:
    """Check if the provided password matches the WEB_AUTH_TOKEN."""
    if not WEB_AUTH_TOKEN:
        # Defaults to False if auth is enabled but no token is configured
        return False
        
    # Use secrets.compare_digest to prevent timing attacks
    return secrets.compare_digest(password, WEB_AUTH_TOKEN)
