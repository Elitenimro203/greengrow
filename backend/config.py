"""
GreenGrow — Configuration centralisée
======================================
Toute la configuration (base de données, seuils par défaut, CORS...) est lue
ICI, une seule fois, depuis les variables d'environnement ou le fichier .env.

Pourquoi un seul endroit ?
Avant, chaque fichier faisait son propre os.getenv(...) avec sa propre valeur
par défaut : la base s'appelait ".greengrow_dev.db" dans le code et
"greengrow_dev.db" dans .env.example. Avec une classe Settings, il n'y a plus
qu'une seule source de vérité, et pydantic vérifie les types au démarrage
(un seuil "abc" fait planter tout de suite, pas trois semaines plus tard).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "GreenGrow"
    app_env: str = "development"

    # SQLite en développement, PostgreSQL en production (même code, autre URL).
    database_url: str = "sqlite:///./greengrow_dev.db"

    # Origines autorisées à appeler l'API depuis un navigateur, séparées par
    # des virgules. En production : uniquement le domaine du dashboard.
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Seuils par défaut d'un nouveau bac (profil tomate). Chaque bac garde
    # ensuite SES seuils en base : ce sont des données, pas du code.
    moisture_threshold_low: float = 45.0
    moisture_threshold_high: float = 80.0
    temp_max_celsius: float = 35.0

    # --- Connexion des utilisateurs ---
    # Durée de vie d'une connexion. Passé ce délai, il faut se reconnecter.
    session_hours: int = 168  # 7 jours
    # Anti-devinette : au-delà de ce nombre de mots de passe faux dans la
    # fenêtre, les tentatives sont refusées (par compte, et par adresse IP).
    login_max_failures: int = 5
    login_max_failures_per_ip: int = 20
    login_window_minutes: int = 15

    # --- Commandes envoyées aux bacs ---
    # Une commande non exécutée après ce délai est ignorée par le bac.
    command_lifetime_seconds: int = 30
    # Nombre maximum de commandes par bac et par minute.
    command_max_per_minute: int = 6

    # --- Alertes Telegram (facultatif) ---
    # Jeton du bot (donné par @BotFather) et identifiant de la conversation
    # où envoyer les alertes. Vides = pas de notification.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- MQTT ---
    # false = l'API fonctionne sans broker (tests, premiers pas).
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 8883
    # Certificat de l'autorité (CA) qui a signé celui du broker. Le backend
    # refuse de se connecter à un broker qui ne présente pas un certificat
    # signé par cette CA.
    mqtt_ca_file: str = "certs/ca.crt"
    # Compte administrateur du broker : sert UNIQUEMENT à créer les comptes.
    mqtt_admin_user: str = "admin"
    mqtt_admin_password: str = ""
    # Compte du backend : lit les mesures, enverra les commandes. Rien d'autre.
    mqtt_backend_user: str = "greengrow-backend"
    mqtt_backend_password: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Retourne toujours le même objet Settings (lu une seule fois)."""
    return Settings()
