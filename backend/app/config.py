"""Configuration de l'application (pydantic-settings).

Le profil de ménage unique de la v1 est identifié ici : aucune
authentification, un seul profil chargé depuis la configuration (docs/spec.md).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: `config/` du dépôt, vu depuis `backend/app/config.py`. Sert de défaut de
#: développement : le serveur se lance depuis `backend/`, donc un chemin
#: relatif comme « config » y viserait `backend/config`, qui n'existe pas.
_REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MENU_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://menu:menu@localhost:5432/menu_optimizer"
    #: Identifiant du profil de ménage unique de la v1.
    household_profile_id: str = "default"
    #: Répertoire des jeux de données seed (fichiers JSON versionnés).
    seed_dir: str = "seed/main"
    #: Répertoire des fichiers de curation et de règles (JSON versionnés).
    #: La route des devis y lit les règles d'approvisionnement. Le chemin était
    #: auparavant calculé en dur en remontant les dossiers parents du fichier
    #: source, sans réglage possible : dans l'image cela visait `/config`, qui
    #: n'y existait pas, et la route répondait 500 au premier appel. Le défaut
    #: ci-dessous couvre le développement depuis le dépôt; l'image reçoit
    #: `MENU_CONFIG_DIR` et un montage (voir `docker-compose.yml`).
    config_dir: str = str(_REPO_CONFIG_DIR)


settings = Settings()
