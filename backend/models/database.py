"""
GreenGrow — Connexion à la base de données
===========================================
Ce fichier ne contient que la "plomberie" : le moteur, la fabrique de
sessions et la classe de base des tables. Les tables elles-mêmes sont dans
entities.py.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import get_settings

settings = get_settings()

# check_same_thread ne concerne que SQLite. On ne le passe donc que pour
# SQLite, sinon PostgreSQL refuserait cet argument inconnu.
connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Classe mère de toutes les tables."""


def get_db():
    """
    Fournit une session de base à une route, puis la ferme proprement,
    même si la route plante (c'est le rôle du finally).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
