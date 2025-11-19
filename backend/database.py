import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# Načteme .env (musí být ve stejné složce jako tento soubor nebo výš)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL není nastavené v .env souboru")

# Vytvoření SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Factory na DB session
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Základ pro modely
Base = declarative_base()


# Dependency pro FastAPI – dostaneš db session do endpointů
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
