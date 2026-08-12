"""Configuration provider-agnostique via .env (spec MISSION §6.4)."""
from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Chemin ABSOLU du .env, dans le paquet surebet/ (git-ignore), pour qu'il soit
# lu quel que soit le dossier de lancement (le lanceur demarre depuis la racine
# du depot). On accepte aussi un .env a la racine du projet en second recours.
_PACKAGE_ENV = Path(__file__).resolve().parent / ".env"
_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, _PACKAGE_ENV),  # le dernier a la priorite
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    database_url: str = "sqlite+aiosqlite:///./surebet.db"

    # IA (provider-agnostique ; Anthropic par defaut)
    llm_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    llm_hourly_call_budget: int = 200
    ai_normalizer_confidence_threshold: float = 0.9

    # Notifier
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # Seuils d'alerte (spec MISSION §8)
    # 3 % : en dessous, la fenetre se referme souvent avant d'avoir place les
    # deux mises, et le gain ne couvre pas le temps passe. MIN_ROI_ALERT_PCT
    # dans .env a la priorite sur cette valeur.
    min_roi_alert_pct: float = 3.0
    min_score_alert: int = 70

    # N'alerter que sur les occasions dont une jambe vient de ce bookmaker.
    # Vide = aucune restriction, comportement d'origine.
    #
    # Sert a repartir la couverture entre deux machines. Depuis aout 2026,
    # l'API de Paryaj Lakay refuse l'adresse du VPS (403) alors qu'elle repond
    # depuis une connexion haitienne : le VPS couvre les trois autres
    # bookmakers, une machine en Haiti couvre Lakay avec
    # ALERT_ONLY_BOOKMAKER="Paryaj Lakay". Le recouvrement est nul par
    # construction — le VPS ne peut pas detecter une occasion contenant Lakay,
    # puisqu'il n'obtient aucune de ses cotes.
    alert_only_bookmaker: str | None = None

    default_bankroll: float = 50_000.0

    # Scraping (spec MISSION §3)
    scrape_interval_prematch_s: int = 30
    scrape_interval_live_s: int = 10
    odds_max_age_s: int = 60
    scraper_unavailable_alert_after_s: int = 300

    # Collector (sessions navigateur persistantes)
    #
    # Note du 12 aout 2026 : le commentaire qui accusait Cloudflare de bloquer
    # le mode headless est FAUX. Paryaj Lakay repond « Server: IIS/10.0 », sans
    # aucun en-tete Cloudflare, et l'echec constate sur le VPS venait du filtre
    # d'adresse IP de son fournisseur de plateforme — pas du mode d'affichage.
    # Le mode invisible convient donc, y compris en production.
    browser_headless: bool = True
    browser_profile_dir: str = "./.browser-profiles"
    evaluation_interval_s: int = 10

    # Normalizer
    fuzzy_team_threshold: int = 85

    # Dashboard
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8000

    # Bookmakers cibles (spec MISSION §1)
    xbet_base_url: str = "https://ht.1xbet.com"
    paryajlakay_base_url: str = "https://www.paryajlakay.com"
    paryajpam_base_url: str = "https://www.paryajpam.com"
    golcash_base_url: str = "https://www.golcashhaiti.com"

    @field_validator("browser_profile_dir", "database_url", mode="after")
    @classmethod
    def _nettoyer(cls, v: str) -> str:
        """Retire espaces et guillemets parasites autour d'un chemin.

        Cas reel du 12 aout 2026 : un lanceur .bat ecrivant
        « set VAR=valeur & commande » place l'espace precedant le & DANS la
        valeur. Le dossier de profil devenait « …/football » avec une espace
        finale, et Windows refuse de creer un tel dossier — Paryaj Lakay
        echouait au demarrage de sa session, avec une trace illisible.

        Ces valeurs viennent d'une variable d'environnement, saisie a la main
        ou posee par un script : les nettoyer ici protege tous les appelants
        plutot qu'un seul.
        """
        return v.strip().strip('"').strip("'").strip() if isinstance(v, str) else v


settings = Settings()
