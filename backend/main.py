from typing import Optional
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import get_db
from models import Product
from schemas import ProductOut, ProductListResponse

# ⬇️ tady importujeme tvůj scraper jako modul
import update_all_prices as up


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
#   PRODUCTS – SEZNAM
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


# ======================
#   PRODUCTS – DETAIL
# ======================

@app.get("/products/{product_id}", response_model=ProductOut)
def get_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nenalezen")

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

    # referer použijeme jen když známe doménu
    referer = f"https://{dom}/" if dom else None

    html, status = up.get_html(url, referer=referer, pause=1.5)

    # 404 => skončil
    if status == 404:
        return 1

    # máme HTML a je tam "Prodej skončil" => 1
    if html and up.is_discontinued(html):
        return 1

    # nemáme HTML => fail, nebudeme nic měnit
    if not html:
        return None

    # pokus si vytáhnout cenu
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
    """
    Když otevřeš detail produktu na frontendu:
      - frontend zavolá POST /products/{id}/refresh-price
      - tady se stáhne stránka (Alza/CZC/…)
      - najde se nová cena
      - uloží se do DB (price + případně old_price + updated_at)
      - vrátí se aktuální produkt
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nenalezen")

    # Bez URL nemáme co refreshovat => jen vrátíme produkt
    if not product.url or not product.url.strip():
        return product

    try:
        new_price = compute_new_price_for_product(product)
    except Exception as e:
        # Když se scraper rozsype, nechceme 502, jen zalogovat a vrátit stará data
        print(f"[REFRESH ERROR] id={product.id} url={product.url} -> {e}")
        return product

    # Nepodařilo se cenu zjistit -> necháme starou cenu, vrátíme 200
    if new_price is None:
        return product

    # Když se cena změnila, přepíšeme old_price
    if product.price is not None and product.price != new_price:
        # necháme si starou cenu jako last known
        product.old_price = product.price

    product.price = new_price
    product.updated_at = datetime.now(timezone.utc)

    db.add(product)
    db.commit()
    db.refresh(product)

    return product
