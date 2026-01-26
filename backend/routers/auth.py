from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import get_db
from models import User
from schemas_auth import RegisterIn, RegisterOut, LoginIn, TokenOut
from auth_utils import hash_password, verify_password
from jwt_utils import create_access_token
from deps_auth import get_current_user

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email už je zaregistrovaný")

    if data.username and db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username už je obsazený")

    user = User(
        email=data.email,
        username=data.username,
        password_hash=hash_password(data.password),
        is_verified=False,
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

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "is_verified": user.is_verified,
    }


@auth_router.post("/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Špatný email nebo heslo")

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Špatný email nebo heslo")

    token = create_access_token({"sub": user.email, "user_id": user.id})
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
