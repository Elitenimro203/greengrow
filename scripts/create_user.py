"""
GreenGrow — Crée un compte utilisateur (ou change son mot de passe)
====================================================================
Il n'existe AUCUNE page d'inscription publique : un compte ne se crée qu'ici,
depuis la machine du serveur. Celui qui peut lancer ce script a déjà accès à
la base ; il n'y a donc pas de porte en plus à surveiller.

    python scripts/create_user.py --email toi@exemple.com --nom "Ton nom" --role owner
    python scripts/create_user.py --email ami@exemple.com --nom "Un ami"        (lecture seule)
    python scripts/create_user.py --email toi@exemple.com --reset               (nouveau mot de passe)

Le mot de passe est demandé au clavier, sans s'afficher. Il n'est jamais
passé en argument : il resterait dans l'historique du terminal.
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from backend.models.database import SessionLocal  # noqa: E402
from backend.models.entities import User, UserSession  # noqa: E402
from backend.services import audit, auth, passwords  # noqa: E402


def ask_password() -> str:
    # GREENGROW_PASSWORD sert aux scripts automatiques (tests) ; à la main,
    # laisse-la vide et tape ton mot de passe.
    password = os.getenv("GREENGROW_PASSWORD")
    if password:
        return password
    password = getpass.getpass("Mot de passe : ")
    if getpass.getpass("Encore une fois : ") != password:
        sys.exit("❌ Les deux saisies sont différentes.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Crée un utilisateur GreenGrow")
    parser.add_argument("--email", required=True)
    parser.add_argument("--nom", default=None)
    parser.add_argument("--role", choices=auth.ROLES, default="viewer")
    parser.add_argument("--reset", action="store_true", help="change le mot de passe d'un compte existant")
    args = parser.parse_args()

    email = auth.normalize_email(args.email)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if args.reset:
            if user is None:
                sys.exit(f"❌ Aucun compte {email}.")
            password = ask_password()
            problem = passwords.check_strength(password)
            if problem:
                sys.exit(f"❌ {problem}")
            user.password_hash = passwords.hash_password(password)
            # Changer de mot de passe ferme toutes les sessions ouvertes : si
            # quelqu'un d'autre était connecté avec l'ancien, il est dehors.
            db.execute(delete(UserSession).where(UserSession.user_id == user.id))
            audit.record(db, "password_reset", user=user, target=user.email)
            db.commit()
            print(f"✅ Mot de passe changé pour {email} (sessions ouvertes fermées)")
            return

        if user is not None:
            sys.exit(f"❌ Le compte {email} existe déjà (--reset pour changer son mot de passe).")
        try:
            user = auth.create_user(db, email, args.nom or email.split("@")[0], ask_password(), args.role)
        except ValueError as exc:
            sys.exit(f"❌ {exc}")
        print(f"✅ Compte créé : {user.email} (rôle : {user.role})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
