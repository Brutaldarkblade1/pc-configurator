from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import get_db
from models import Product, CPU, GPU, Motherboard, PCCase, PSU, RAM, Storage, Cooler
from schemas import ProductOut, ProductListResponse


import update_all_prices as up


app = FastAPI(title="PC Configurator API")

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

app.mount("/img", StaticFiles(directory="img"), name="img")


@app.get("/health")
def health():
    return {"ok": True}


# ======================
#   PRODUCTS – SEZNAM
# ======================

@app.get("/products", response_model=ProductListResponse)
def list_products(
    category: Optional[str] = None,
    include_spec: bool = False,
    limit: int = 15,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    if offset < 0:
        offset = 0

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

    if include_spec:
        for item in items:
            item.spec = get_spec_for_product(item, db)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ======================
#   SPECIFIKACE PODLE KATEGORIE
# ======================

def get_spec_for_product(product: Product, db: Session):
    """
    Vrati dictionary se specifikacemi z kategoriovych tabulek podle produktu.
    Pokud kategorie nema zaznam, vrati None.
    """
    cat = (product.category or "").lower()
    pid = product.id

    try:
        if cat == "cpu":
            row = db.query(CPU).filter(CPU.product_id == pid).first()
            if row:
                return {
                    "socket": row.socket,
                    "tdp": row.tdp,
                    "igpu": row.igpu,
                }

        elif cat == "gpu":
            row = db.query(GPU).filter(GPU.product_id == pid).first()
            if row:
                return {
                    "vram_gb": row.vram_gb,
                    "tdp": row.tdp,
                    "length_mm": row.length_mm,
                }

        elif cat in ("motherboard", "mb"):
            row = db.query(Motherboard).filter(Motherboard.product_id == pid).first()
            if row:
                return {
                    "socket": row.socket,
                    "ram_type": row.ram_type,
                    "form_factor": row.form_factor,
                }

        elif cat in ("case", "skrine", "pc_case"):
            row = db.query(PCCase).filter(PCCase.product_id == pid).first()
            if row:
                return {
                    "form_factor_support": row.form_factor_support,
                    "gpu_max_length_mm": row.gpu_max_length_mm,
                    "cooler_max_height_mm": row.cooler_max_height_mm,
                    "psu_form_factor": row.psu_form_factor,
                }

        elif cat in ("psu", "zdroj"):
            row = db.query(PSU).filter(PSU.product_id == pid).first()
            if row:
                return {
                    "wattage": row.wattage,
                    "efficiency": row.efficiency,
                    "modular": row.modular,
                }

        elif cat == "ram":
            row = db.query(RAM).filter(RAM.product_id == pid).first()
            if row:
                return {
                    "type": row.type,
                    "speed_mhz": row.speed_mhz,
                    "capacity_gb": row.capacity_gb,
                    "sticks": row.sticks,
                }

        elif cat in ("ssd", "hdd", "storage"):
            row = db.query(Storage).filter(Storage.product_id == pid).first()
            if row:
                return {
                    "type": row.type,
                    "capacity_gb": row.capacity_gb,
                    "interface": row.interface,
                }

        elif cat in ("cooler", "chlazeni"):
            row = db.query(Cooler).filter(Cooler.product_id == pid).first()
            if row:
                return {
                    "type": row.type,
                    "tdp_support": row.tdp_support,
                    "socket_support": row.socket_support,
                    "height_mm": row.height_mm,
                }
    except Exception as exc:
        print(f"[SPEC LOOKUP WARN] product_id={pid} category={cat} -> {exc}")

    return None





@app.get("/products/{product_id}", response_model=ProductOut)
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nenalezen")

    product.spec = get_spec_for_product(product, db)

    return product


# ======================
#   HELPER: REFRESH CENY
# ======================

def compute_new_price_for_product(product: Product) -> Optional[int]:
    """
    Vrátí novou cenu v Kč (int) nebo:
      - 1 = produkt skončil
      - None = nepodařilo se zjistit (necháme starou cenu)
    """
    if not product.url or not product.url.strip():
        return None

    url = product.url.strip()
    dom = up.domain_of(url)
    selector = up.DOMAIN_SELECTORS.get(dom)

    referer = f"https://{dom}/" if dom else None

    html, status = up.get_html(url, referer=referer, pause=1.5)

    if status == 404:
        return 1

    if html and up.is_discontinued(html):
        return 1

    if not html:
        return None

    dec = up.extract_price(html, selector)
    if dec is None:
        return None

    return up.as_kc_int(dec)


# ===============================
#   ENDPOINT: REFRESH PRICE JEDNOHO PRODUKTU
# ===============================

@app.post("/products/{product_id}/refresh-price", response_model=ProductOut)
def refresh_product_price(
    product_id: int,
    db: Session = Depends(get_db),
):
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nenalezen")

    product.spec = get_spec_for_product(product, db)

    if not product.url or not product.url.strip():
        return product

    try:
        new_price = compute_new_price_for_product(product)
    except Exception as e:
        print(f"[REFRESH ERROR] id={product.id} url={product.url} -> {e}")
        return product

    if new_price is None:
        return product

    if product.price is not None and product.price != new_price:
        product.old_price = product.price

    product.price = new_price
    product.updated_at = datetime.now(timezone.utc)

    db.add(product)
    db.commit()
    db.refresh(product)

    product.spec = get_spec_for_product(product, db)

    return product
