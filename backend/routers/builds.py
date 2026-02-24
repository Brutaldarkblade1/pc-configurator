from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from deps_auth import get_current_user
from models import User, UserBuild
from schemas import UserBuildCreate, UserBuildListResponse, UserBuildOut, UserBuildUpdate


MAX_BUILDS_PER_USER = 5

builds_router = APIRouter(prefix="/builds", tags=["builds"])


def _get_payload_data(payload: Any) -> Dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)


def _normalize_name(value: str) -> str:
    name = (value or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Nazev sestavy nesmi byt prazdny.")
    if len(name) > 120:
        raise HTTPException(status_code=422, detail="Nazev sestavy muze mit max 120 znaku.")
    return name


def _normalize_description(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        raw = value.strip().replace(" ", "")
        if not raw:
            return None
        try:
            return int(float(raw.replace(",", ".")))
        except ValueError:
            return None
    return None


def _normalize_build_data(raw_items: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=422, detail="build_data musi byt pole.")

    normalized: List[Dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="build_data musi obsahovat jen objektove polozky.")

        entry = dict(item)
        qty = _coerce_int(entry.get("qty"))
        entry["qty"] = max(1, qty if qty is not None else 1)
        normalized.append(entry)

    return normalized


def _compute_total_price(build_data: List[Dict[str, Any]]) -> int:
    total = 0

    for item in build_data:
        qty = max(1, _coerce_int(item.get("qty")) or 1)
        price = _coerce_int(item.get("price"))
        old_price = _coerce_int(item.get("old_price"))

        base_price: Optional[int] = None
        if price == 1:
            base_price = old_price
        elif price is not None:
            base_price = price
        elif old_price is not None:
            base_price = old_price

        if base_price is None or base_price < 0:
            continue

        total += base_price * qty

    return total


def _get_user_build_or_404(db: Session, build_id: int, user_id: int) -> UserBuild:
    row = (
        db.query(UserBuild)
        .filter(UserBuild.id == build_id, UserBuild.user_id == user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Sestava nebyla nalezena.")
    return row


@builds_router.get("", response_model=UserBuildListResponse)
def list_user_builds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = (
        db.query(UserBuild)
        .filter(UserBuild.user_id == current_user.id)
        .order_by(UserBuild.updated_at.desc(), UserBuild.id.desc())
        .all()
    )
    return {
        "items": items,
        "total": len(items),
        "max_allowed": MAX_BUILDS_PER_USER,
    }


@builds_router.get("/{build_id}", response_model=UserBuildOut)
def get_user_build(
    build_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_user_build_or_404(db, build_id, current_user.id)


@builds_router.post("", response_model=UserBuildOut)
def create_user_build(
    payload: UserBuildCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = db.query(UserBuild).filter(UserBuild.user_id == current_user.id).count()
    if count >= MAX_BUILDS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Muzete ulozit maximalne {MAX_BUILDS_PER_USER} sestav.",
        )

    build_data = _normalize_build_data(payload.build_data)
    now = datetime.utcnow()

    row = UserBuild(
        user_id=current_user.id,
        name=_normalize_name(payload.name),
        description=_normalize_description(payload.description),
        build_data=build_data,
        total_price=_compute_total_price(build_data),
        is_favorite=bool(payload.is_favorite),
        created_at=now,
        updated_at=now,
    )

    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Sestava s timto nazvem uz existuje.",
        )

    db.refresh(row)
    return row


@builds_router.put("/{build_id}", response_model=UserBuildOut)
def update_user_build(
    build_id: int,
    payload: UserBuildUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _get_user_build_or_404(db, build_id, current_user.id)
    updates = _get_payload_data(payload)

    if "name" in updates:
        row.name = _normalize_name(updates["name"])
    if "description" in updates:
        row.description = _normalize_description(updates["description"])
    if "build_data" in updates:
        row.build_data = _normalize_build_data(updates["build_data"])
        row.total_price = _compute_total_price(row.build_data)
    if "is_favorite" in updates:
        row.is_favorite = bool(updates["is_favorite"])

    row.updated_at = datetime.utcnow()
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Sestava s timto nazvem uz existuje.",
        )

    db.refresh(row)
    return row


@builds_router.delete("/{build_id}")
def delete_user_build(
    build_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _get_user_build_or_404(db, build_id, current_user.id)
    db.delete(row)
    db.commit()
    return {"ok": True}
