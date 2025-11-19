from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class ProductOut(BaseModel):
    id: int
    name: str
    category: str
    brand: Optional[str] = None
    price: Optional[int] = None
    source: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    old_price: Optional[int] = None
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True  # důležité pro převod z SQLAlchemy modelu


class ProductListResponse(BaseModel):
    items: List[ProductOut]
    total: int
    limit: int
    offset: int
