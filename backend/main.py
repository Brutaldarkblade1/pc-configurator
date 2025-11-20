from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import get_db
from models import Product
from schemas import ProductOut, ProductListResponse


app = FastAPI(title="PC Configurator API")

# CORS pro frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Obrázky (backend/img)
app.mount("/img", StaticFiles(directory="img"), name="img")


@app.get("/health")
def health():
    return {"ok": True}


# ======================
#   PRODUCTS
# ======================

@app.get("/products", response_model=ProductListResponse)
def list_products(
    category: Optional[str] = None,
    limit: int = 15,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    query = db.query(Product)

    if category:
        query = query.filter(Product.category == category)

    total = query.count()

    items = (
        query
        .order_by(Product.id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nenalezen")

    return product
