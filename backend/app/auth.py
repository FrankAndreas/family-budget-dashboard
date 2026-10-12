import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from . import schemas, database, models

logger = logging.getLogger(__name__)

# Signs the login tokens. Without SECRET_KEY a random key is used, which is safe but logs everyone
# out whenever the backend restarts; set it (e.g. in .env) to keep sessions across restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
if not os.getenv("SECRET_KEY"):
    logger.warning("SECRET_KEY is not set; using a random key, so logins won't survive a restart")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 3000

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def verify_pin(plain_pin, hashed_pin):
    return pwd_context.verify(plain_pin, hashed_pin)


def get_pin_hash(pin):
    return pwd_context.hash(pin)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user_from_token(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # The subject is the user id, so renaming a user keeps their session valid
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = schemas.TokenData(user_id=user_id)
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == token_data.user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user
