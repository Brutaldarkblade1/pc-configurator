# main.py
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Product
from schemas import ProductOut

app = FastAPI()

# vytvoření tabulek (pokud nejsou)
Base.metadata.create_all(bind=engine)

# CORS – aby frontend na http://localhost:5173 (Vite) nebo 3000 (CRA) měl přístup
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/products", response_model=list[ProductOut])
def get_products(db: Session = Depends(get_db)):
    products = (
        db.query(Product)
        .order_by(Product.id)
        .limit(100)
        .all()
    )
    return products
