import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from . import schemas, database, models, i18n, messages

logger = logging.getLogger(__name__)

# Signs the login tokens. Without SECRET_KEY a random key is used, which is safe but logs everyone
# out whenever the backend restarts; set it (e.g. in .env) to keep sessions across restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
if not os.getenv("SECRET_KEY"):
    logger.warning("SECRET_KEY is not set; using a random key, so logins won't survive a restart")
ALGORITHM = "HS256"
# A PIN has only 4 digits: after this many wrong ones in a row, the username is locked for a while
MAX_WRONG_PINS = 5
LOCK_MINUTES = 15
ACCESS_TOKEN_EXPIRE_MINUTES = 3000

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


# PINs are hashed with bcrypt directly (passlib is unmaintained and breaks with bcrypt 5).
# The hash format is unchanged, so PINs hashed by passlib keep working.
def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    try:
        return bcrypt.checkpw(plain_pin.encode(), hashed_pin.encode())
    except ValueError:
        # Not a valid bcrypt hash: treat it like a wrong PIN instead of a server error
        return False


# bcrypt's default cost; the tests lower it, because hashing dominated their run time
PIN_HASH_ROUNDS = 12


def get_pin_hash(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=PIN_HASH_ROUNDS)).decode()


def now() -> datetime:
    """The current time as stored (naive UTC); tests replace it."""
    return datetime.utcnow()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user_from_token(
    token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)
) -> models.User:
    # Built before the token is checked, so in the browser's language (right for an expired login)
    credentials_exception = messages.api_error(
        status.HTTP_401_UNAUTHORIZED, "not_logged_in", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # The subject is the user id, so renaming a user keeps their session valid
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # Tokens issued before session versions existed have none: version 0
        version = payload.get("ver", 0)
        token_data = schemas.TokenData(user_id=user_id)
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == token_data.user_id).first()
    if user is None or not user.is_active or version != (user.token_version or 0):
        raise credentials_exception
    # From here on, the request speaks the person's language
    i18n.set_current(i18n.user_language(user))
    return user


async def get_optional_user(
    token: Optional[str] = Depends(optional_oauth2_scheme), db: Session = Depends(database.get_db)
) -> Optional[models.User]:
    """The logged-in person if the request has a valid login, else None (for endpoints open to everyone)."""
    if not token:
        return None
    try:
        return await get_current_user_from_token(token, db)
    except HTTPException:
        return None
