# schemas.py
from typing import Optional, List, Dict, Any
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
        orm_mode = True


class ProductListResponse(BaseModel):
    items: List[ProductOut]
    total: int
    limit: int
    offset: int
