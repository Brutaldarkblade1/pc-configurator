from pydantic import BaseModel
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Literal

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

# dočasná testovací data (místo databáze)
PRODUCTS = [
    {"id": 1, "name": "AMD Ryzen 5 7600", "category": "cpu", "specs": {"socket": "AM5"}},
    {"id": 2, "name": "MSI B650 Tomahawk", "category": "mb",  "specs": {"socket": "AM5", "ram_type": "DDR5"}},
    {"id": 3, "name": "Kingston 16GB DDR5-6000", "category": "ram", "specs": {"type": "DDR5"}},
    {"id": 4, "name": "Intel Core i5-12400F", "category": "cpu", "specs": {"socket": "LGA1700"}},
    {"id": 5, "name": "ASUS TUF B660-PLUS", "category": "mb",  "specs": {"socket": "LGA1700", "ram_type": "DDR4"}},
    {"id": 6, "name": "Patriot 16GB DDR4-3200", "category": "ram", "specs": {"type": "DDR4"}},
]

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/products")
def list_products(category: Optional[Literal["cpu","mb","ram","gpu"]] = None):
    """
    Vrátí seznam produktů. Můžeš filtrovat podle kategorie:
    /products?category=cpu  nebo  /products?category=ram
    """
    if category:
        return [p for p in PRODUCTS if p["category"] == category]
    return PRODUCTS
    from pydantic import BaseModel
from typing import Optional

# --- datový model požadavku ---
class Build(BaseModel):
    cpu_id: Optional[int] = None
    mb_id: Optional[int] = None
    ram_id: Optional[int] = None

@app.post("/build/validate")
def validate_build(build: Build):
    """
    Zkontroluje kompatibilitu: CPU↔MB socket, MB↔RAM typ.
    Vrací seznam findings (chyb/varování).
    """
    findings = []

    # pomocné vyhledání produktů podle id
    by_id = {p["id"]: p for p in PRODUCTS}
    cpu = by_id.get(build.cpu_id)
    mb  = by_id.get(build.mb_id)
    ram = by_id.get(build.ram_id)

    # pravidlo 1: CPU socket == MB socket
    if cpu and mb:
        if cpu["specs"].get("socket") != mb["specs"].get("socket"):
            findings.append({"severity": "error", "msg": "CPU a základní deska mají jiný socket."})

    # pravidlo 2: RAM typ == MB ram_type
    if mb and ram:
        if ram["specs"].get("type") != mb["specs"].get("ram_type"):
            findings.append({"severity": "error", "msg": "RAM typ neodpovídá desce (DDR4/DDR5)."})

    return {"findings": findings}

