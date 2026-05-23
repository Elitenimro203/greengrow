from sqlalchemy import create_engine, Column, String, Float, Boolean, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///.greengrow_dev.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Bac(Base):
    __tablename__ = "bacs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    bac_id = Column(String, unique=True, index=True)
    nom = Column(String)
    localisation = Column(String)
    date_creation = Column(DateTime, default=datetime.utcnow)

class Reading(Base):
    __tablename__ = "readings"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True)
    bac_id = Column(String, index=True)
    timestamp = Column(Float)
    moisture_percent = Column(Float)
    temperature_celsius = Column(Float)
    humidity_air_percent = Column(Float)
    pump_active = Column(Boolean)
    source = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = {'extend_existing': True}

    alert_id = Column(Integer, primary_key=True, index=True)
    bac_id = Column(String, index=True)
    type = Column(String)
    message = Column(String)
    timestamp = Column(Float)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    """
    Générateur de session DB.
    Ouvre une connexion, la fournit, puis la ferme proprement.
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
    
def init_db():
    """Crée toutes les tables si elles n'existent pas encore."""
    Base.metadata.create_all(bind=engine)
