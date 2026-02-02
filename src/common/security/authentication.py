from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import secrets
import hashlib
import base64

from jose import jwt, JWTError, ExpiredSignatureError
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from src.common.config.settings import get_settings
from src.common.config.constants import JWT_ALGORITHM, JWT_EXPIRATION_HOURS


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenData(BaseModel):
    user_id: str
    username: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    scopes: List[str] = Field(default_factory=list)
    is_service_account: bool = Field(default=False)


class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    iat: datetime
    jti: str
    type: str = Field(default="access")
    data: TokenData


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer")
    expires_in: int
    refresh_token: Optional[str] = None


def create_access_token(
    data: TokenData,
    expires_delta: Optional[timedelta] = None,
    token_type: str = "access",
) -> str:
    settings = get_settings()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    
    jti = secrets.token_urlsafe(32)
    
    payload = {
        "sub": data.user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": jti,
        "type": token_type,
        "data": data.model_dump(),
    }
    
    encoded_jwt = jwt.encode(
        payload,
        settings.get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )
    
    return encoded_jwt


def create_refresh_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    settings = get_settings()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
    
    jti = secrets.token_urlsafe(32)
    
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": jti,
        "type": "refresh",
    }
    
    encoded_jwt = jwt.encode(
        payload,
        settings.get_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )
    
    return encoded_jwt


def verify_token(token: str) -> bool:
    try:
        decode_token(token)
        return True
    except (JWTError, ExpiredSignatureError, ValueError):
        return False


def verify_jwt_token(token: str) -> Optional[TokenPayload]:
    try:
        return decode_token(token)
    except (JWTError, ExpiredSignatureError, ValueError):
        return None


def decode_token(token: str) -> TokenPayload:
    settings = get_settings()
    
    try:
        payload = jwt.decode(
            token,
            settings.get_jwt_secret(),
            algorithms=[settings.jwt_algorithm],
        )
        
        token_data = TokenData(**payload.get("data", {}))
        
        return TokenPayload(
            sub=payload["sub"],
            exp=datetime.fromisoformat(payload["exp"].isoformat()) if isinstance(payload["exp"], datetime) else datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            iat=datetime.fromisoformat(payload["iat"].isoformat()) if isinstance(payload["iat"], datetime) else datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            jti=payload["jti"],
            type=payload.get("type", "access"),
            data=token_data,
        )
    except ExpiredSignatureError:
        raise ValueError("Token has expired")
    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_api_key(prefix: str = "rk") -> tuple[str, str]:
    raw_key = secrets.token_urlsafe(32)
    
    full_key = f"{prefix}_{raw_key}"
    
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    
    return full_key, key_hash


def validate_api_key(api_key: str, stored_hash: str) -> bool:
    computed_hash = hashlib.sha256(api_key.encode()).hexdigest()
    return secrets.compare_digest(computed_hash, stored_hash)


def generate_webhook_signature(payload: bytes, secret: str) -> str:
    signature = hashlib.sha256(secret.encode() + payload).hexdigest()
    return f"sha256={signature}"


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected_signature = generate_webhook_signature(payload, secret)
    return secrets.compare_digest(signature, expected_signature)


class APIKeyManager:
    def __init__(self):
        self._key_cache: Dict[str, str] = {}
    
    def create_key(
        self,
        name: str,
        prefix: str = "rk",
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        full_key, key_hash = generate_api_key(prefix)
        
        key_id = secrets.token_urlsafe(8)
        
        return {
            "key_id": key_id,
            "name": name,
            "key": full_key,
            "key_hash": key_hash,
            "prefix": prefix,
            "created_at": datetime.now(timezone.utc),
            "expires_at": expires_at,
        }
    
    def validate(self, api_key: str, stored_hash: str) -> bool:
        return validate_api_key(api_key, stored_hash)


class TokenBlacklist:
    def __init__(self):
        self._blacklisted_tokens: Dict[str, datetime] = {}
    
    def add(self, jti: str, expires_at: datetime) -> None:
        self._blacklisted_tokens[jti] = expires_at
    
    def is_blacklisted(self, jti: str) -> bool:
        if jti in self._blacklisted_tokens:
            if self._blacklisted_tokens[jti] > datetime.now(timezone.utc):
                return True
            else:
                del self._blacklisted_tokens[jti]
        return False
    
    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired_tokens = [
            jti for jti, exp in self._blacklisted_tokens.items() if exp <= now
        ]
        for jti in expired_tokens:
            del self._blacklisted_tokens[jti]
        return len(expired_tokens)


token_blacklist = TokenBlacklist()
