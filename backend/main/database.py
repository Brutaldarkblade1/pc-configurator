# database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# načteme .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL není nastavené v .env souboru")

# vytvoření SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# factory na DB session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# základ pro modely
Base = declarative_base()


# dependency pro FastAPI – dostaneš db session do endpointů
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
