"""
auth.py
-------
JWT authentication endpoints for RE_CL API.

Endpoints:
  POST /auth/register  — create account, returns token
  POST /auth/login     — verify credentials, returns token
  GET  /auth/me        — return current user info (requires Bearer token)
"""

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.api.db import get_engine

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 24 h

# ── Crypto helpers ────────────────────────────────────────────────────────────

_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    engine: Engine = Depends(get_engine),
) -> dict:
    """Decode JWT and fetch the matching user row from the DB."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int | None = payload.get("sub")
        if user_id is None:
            raise credentials_exc
        user_id = int(user_id)
    except (JWTError, ValueError):
        raise credentials_exc

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, email FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()

    if row is None:
        raise credentials_exc

    return {"id": row[0], "email": row[1]}


# ── Pydantic models ───────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMe(BaseModel):
    id: int
    email: str


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, engine: Engine = Depends(get_engine)):
    """Create a new user account and return a JWT."""
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": body.email},
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        row = conn.execute(
            text(
                "INSERT INTO users (email, password_hash) "
                "VALUES (:email, :pw_hash) RETURNING id"
            ),
            {"email": body.email, "pw_hash": hash_password(body.password)},
        ).fetchone()
        user_id = row[0]

    token = create_access_token({"sub": str(user_id)})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(body: UserLogin, engine: Engine = Depends(get_engine)):
    """Verify credentials and return a JWT."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, password_hash FROM users WHERE email = :email"),
            {"email": body.email},
        ).fetchone()

    if row is None or not verify_password(body.password, row[1]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": str(row[0])})
    return Token(access_token=token)


@router.post("/refresh", response_model=Token)
def refresh_token(current_user: dict = Depends(get_current_user)):
    """Issue a fresh JWT for an already-authenticated user."""
    new_token = create_access_token({"sub": str(current_user["id"])})
    return Token(access_token=new_token)


@router.get("/me", response_model=UserMe)
def me(current_user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return UserMe(id=current_user["id"], email=current_user["email"])
