# schemas.py
from datetime import datetime
from pydantic import BaseModel


class ProductOut(BaseModel):
    id: int
    name: str
    category: str
    brand: str | None = None
    price: int | None = None
    source: str | None = None
    url: str | None = None
    description: str | None = None
    old_price: int | None = None
    updated_at: datetime | None = None

    class Config:
        orm_mode = True
