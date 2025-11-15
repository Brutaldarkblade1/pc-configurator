from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import get_db
from models import Product
from schemas import ProductOut, ProductListResponse

from pydantic import BaseModel


app = FastAPI(title="PC Configurator API")

# CORS: povolíme volání z frontendů (později použijeme Vite/Live Server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500", "http://localhost:5500",  # Live Server
        "http://127.0.0.1:5173", "http://localhost:5173",  # Vite/React
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


# ==============================
#   PRODUCTS – napojeno na DB
# ==============================

@app.get("/products", response_model=ProductListResponse)
def list_products(
    category: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    Vrátí seznam produktů z DB.
    - /products
    - /products?category=cpu
    - /products?category=gpu&limit=5&offset=10
    """
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100  # basic ochrana

    query = db.query(Product)

    if category:
        query = query.filter(Product.category == category)

    total = query.count()
    items = query.order_by(Product.id).offset(offset).limit(limit).all()

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
    """
    Detail produktu podle ID.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nenalezen")
    return product


# =====================================
#   PŮVODNÍ VALIDATOR BUILDŮ (DUMMY)
#   – zatím necháme zvlášť, klidně i
#     s testovacími daty v Pythonu
# =====================================

# Dočasná testovací data pro validator (není navázané na DB)
TEST_PRODUCTS = [
    {"id": 1, "name": "AMD Ryzen 5 7600", "category": "cpu", "specs": {"socket": "AM5"}},
    {"id": 2, "name": "MSI B650 Tomahawk", "category": "mb",  "specs": {"socket": "AM5", "ram_type": "DDR5"}},
    {"id": 3, "name": "Kingston 16GB DDR5-6000", "category": "ram", "specs": {"type": "DDR5"}},
    {"id": 4, "name": "Intel Core i5-12400F", "category": "cpu", "specs": {"socket": "LGA1700"}},
    {"id": 5, "name": "ASUS TUF B660-PLUS", "category": "mb",  "specs": {"socket": "LGA1700", "ram_type": "DDR4"}},
    {"id": 6, "name": "Patriot 16GB DDR4-3200", "category": "ram", "specs": {"type": "DDR4"}},
]


class Build(BaseModel):
    cpu_id: Optional[int] = None
    mb_id: Optional[int] = None
    ram_id: Optional[int] = None


@app.post("/build/validate")
def validate_build(build: Build):
    """
    Zkontroluje kompatibilitu: CPU↔MB socket, MB↔RAM typ.
    Zatím nad testovacími daty, ne nad DB.
    """
    findings = []

    by_id = {p["id"]: p for p in TEST_PRODUCTS}
    cpu = by_id.get(build.cpu_id)
    mb = by_id.get(build.mb_id)
    ram = by_id.get(build.ram_id)

    if cpu and mb:
        if cpu["specs"].get("socket") != mb["specs"].get("socket"):
            findings.append({"severity": "error", "msg": "CPU a základní deska mají jiný socket."})

    if mb and ram:
        if ram["specs"].get("type") != mb["specs"].get("ram_type"):
            findings.append({"severity": "error", "msg": "RAM typ neodpovídá desce (DDR4/DDR5)."})

    return {"findings": findings}