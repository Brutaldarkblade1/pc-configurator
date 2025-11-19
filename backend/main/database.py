# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "postgresql://postgres:autodoprava@localhost:5432/pc_configurator"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# dependency pro FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
