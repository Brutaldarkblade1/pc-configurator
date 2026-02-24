# schemas.py
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

class ProductOut(BaseModel):
    id: int
    name: str
    category: str
    brand: Optional[str] = None
    price: Optional[int] = None
    old_price: Optional[int] = None      # ← přidáno
    source: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    items: List[ProductOut]
    total: int
    limit: int
    offset: int


class UserBuildCreate(BaseModel):
    name: str
    description: Optional[str] = None
    build_data: List[Dict[str, Any]]
    is_favorite: bool = False


class UserBuildUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    build_data: Optional[List[Dict[str, Any]]] = None
    is_favorite: Optional[bool] = None


class UserBuildOut(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str] = None
    build_data: List[Dict[str, Any]]
    total_price: Optional[int] = None
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserBuildListResponse(BaseModel):
    items: List[UserBuildOut]
    total: int
    max_allowed: int
