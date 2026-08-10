"""Configuration de l'application (pydantic-settings).

Le profil de ménage unique de la v1 est identifié ici : aucune
authentification, un seul profil chargé depuis la configuration (docs/spec.md).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MENU_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://menu:menu@localhost:5432/menu_optimizer"
    #: Identifiant du profil de ménage unique de la v1.
    household_profile_id: str = "default"
    #: Répertoire des jeux de données seed (fichiers JSON versionnés).
    seed_dir: str = "seed/main"


settings = Settings()
