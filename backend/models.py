from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from datetime import datetime

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


class CPU(Base):
    __tablename__ = "cpu"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    socket = Column(String(50), nullable=False)
    tdp = Column(Integer)
    igpu = Column(Boolean, default=False)


class GPU(Base):
    __tablename__ = "gpu"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    vram_gb = Column(Integer)
    tdp = Column(Integer)
    length_mm = Column(Integer)


class Motherboard(Base):
    __tablename__ = "motherboard"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    socket = Column(String(50), nullable=False)
    ram_type = Column(String(50), nullable=False)
    form_factor = Column(String(50))


class PCCase(Base):
    __tablename__ = "pc_case"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    form_factor_support = Column(String(100))
    gpu_max_length_mm = Column(Integer)
    cooler_max_height_mm = Column(Integer)
    psu_form_factor = Column(String(50))


class PSU(Base):
    __tablename__ = "psu"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    wattage = Column(Integer, nullable=False)
    efficiency = Column(String(50))
    modular = Column(Boolean, default=False)


class RAM(Base):
    __tablename__ = "ram"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    type = Column(String(50), nullable=False)
    speed_mhz = Column(Integer)
    capacity_gb = Column(Integer)
    sticks = Column(Integer)


class Storage(Base):
    __tablename__ = "storage"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    type = Column(String(50), nullable=False)
    capacity_gb = Column(Integer)
    interface = Column(String(50))


class Cooler(Base):
    __tablename__ = "cooler"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True, index=True)
    type = Column(String(50), nullable=False)
    tdp_support = Column(Integer)
    socket_support = Column(String(255))
    height_mm = Column(Integer)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(50), unique=True, nullable=True, index=True)
    password_hash = Column(Text, nullable=False)

    is_verified = Column(Boolean, nullable=False, default=False)
    verification_token = Column(Text, unique=True, nullable=True, index=True)
    verification_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
