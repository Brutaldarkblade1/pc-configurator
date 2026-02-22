from fastapi import APIRouter, Depends, HTTPException, status, Response, Body
from fastapi.responses import RedirectResponse
from datetime import datetime, timedelta, timezone
import os
import secrets
from urllib.parse import quote
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import get_db
from models import User
from schemas_auth import RegisterIn, RegisterOut, LoginIn, TokenOut, ResendVerificationIn
from pydantic import EmailStr
from auth_utils import hash_password, verify_password
from jwt_utils import create_access_token, ACCESS_TOKEN_MINUTES
from deps_auth import get_current_user
from email_utils import send_verification_email

auth_router = APIRouter(prefix="/auth", tags=["auth"])

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path)


@auth_router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    username = data.username.strip() if data.username else None
    if username == "":
        username = None
    if username and len(username) > 20:
        raise HTTPException(status_code=422, detail="Uživatelské jméno může mít max 20 znaků.")

    if not any(ch.isdigit() for ch in data.password):
        raise HTTPException(status_code=422, detail="Heslo musí obsahovat alespoň 1 číslo.")

    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="Email už je zaregistrovaný")

    if username and db.query(User).filter(func.lower(User.username) == username.lower()).first():
        raise HTTPException(status_code=400, detail="Username už je obsazený")

    verification_token = secrets.token_urlsafe(32)
    verification_expires_at = datetime.utcnow() + timedelta(minutes=15)

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(data.password),
        is_verified=False,
        verification_token=verification_token,
        verification_expires_at=verification_expires_at,
    )

    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email nebo username už existuje")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    db.refresh(user)

    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    verify_url = f"{base_url}/auth/verify?token={verification_token}"
    try:
        send_verification_email(user.email, verify_url)
    except Exception as exc:
        # Nenechávej v DB účet, který neprošel onboardingem kvůli chybě SMTP.
        try:
            db.delete(user)
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise HTTPException(status_code=500, detail=f"Nepodařilo se odeslat ověřovací email: {exc}")

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "is_verified": user.is_verified,
    }


@auth_router.post("/login", response_model=TokenOut)
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Špatný email nebo heslo")

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Špatný email nebo heslo")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Účet není ověřený. Zkontroluj email.")

    token = create_access_token({"sub": user.email, "user_id": user.id})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
    return {"access_token": token, "token_type": "bearer"}


@auth_router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "is_verified": current_user.is_verified,
        "created_at": current_user.created_at,
    }


@auth_router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verification_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Neplatný ověřovací token.")

    if not user.verification_expires_at:
        raise HTTPException(status_code=400, detail="Ověřovací token vypršel.")

    expires_at = user.verification_expires_at
    now = datetime.now(timezone.utc) if expires_at.tzinfo else datetime.utcnow()
    if expires_at < now:
        raise HTTPException(status_code=400, detail="Ověřovací token vypršel.")

    user.is_verified = True
    user.verification_token = None
    user.verification_expires_at = None
    db.add(user)
    db.commit()
    db.refresh(user)
    frontend_base = os.getenv("APP_FRONTEND_URL", "http://127.0.0.1:5500/backend").rstrip("/")
    display_name = user.username or user.email or "uživateli"
    redirect_url = f"{frontend_base}/products.html?welcome={quote(display_name, safe='')}"
    token = create_access_token({"sub": user.email, "user_id": user.id})
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
    return response


@auth_router.post("/resend-verification")
def resend_verification(
    payload: ResendVerificationIn | None = Body(default=None),
    email: EmailStr | None = None,
    db: Session = Depends(get_db),
):
    target_email = (payload.email if payload else email)
    if not target_email:
        raise HTTPException(status_code=422, detail="Chybí email.")

    user = db.query(User).filter(func.lower(User.email) == target_email.strip().lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="Uživatel nenalezen")
    if user.is_verified:
        return {"ok": True}

    verification_token = secrets.token_urlsafe(32)
    user.verification_token = verification_token
    user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
    db.add(user)
    db.commit()
    db.refresh(user)

    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    verify_url = f"{base_url}/auth/verify?token={verification_token}"
    try:
        send_verification_email(user.email, verify_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Nepodařilo se odeslat ověřovací email: {exc}")

    return {"ok": True}


@auth_router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"ok": True}
