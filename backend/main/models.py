# models.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    brand = Column(String(100))
    price = Column(Integer)
    source = Column(String(100))
    url = Column(String(500), unique=True)
    description = Column(Text)
    old_price = Column(Integer)
    updated_at = Column(DateTime(timezone=True))
    image_url = Column(String(500))  # klidně tu může zůstat, jen ji nepošleme ven
