import base64
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet

from app.config import get_settings

_hasher = PasswordHasher()  # argon2id by default


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(hours=s.jwt_expiry_hours)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def decode_token(token: str) -> str | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        return None


def fernet() -> Fernet:
    """Fernet key derived from SECRET_KEY: encrypts temporary AWS credentials in Redis."""
    digest = hashlib.sha256(("awscreds:" + get_settings().secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
