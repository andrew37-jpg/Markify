from pathlib import Path
from pydantic import AliasChoices, AliasGenerator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = 'Markify'
    version: str = '0.10.2'
    database_url: str = 'sqlite:///./data/markify.db'
    timezone: str = 'Europe/Moscow'
    default_warning_minutes: int = 30
    default_critical_minutes: int = 10
    label_width_mm: int = 58
    label_height_mm: int = 40
    auto_refresh_seconds: int = 10
    session_secret: str = 'change-this-session-secret-before-production'
    session_https_only: bool = False
    session_max_age_seconds: int = 60 * 60 * 12
    bootstrap_org_name: str = 'Markify Demo Restaurant'
    bootstrap_location_name: str = 'Основная кухня'
    bootstrap_admin_name: str = 'Администратор'
    bootstrap_admin_email: str = 'admin@markify.local'
    bootstrap_admin_password: str = 'ChangeMe-Please-2026!'
    agent_poll_seconds: int = 2
    debug: bool = False
    environment: str = 'development'
    print_lease_seconds: int = Field(default=120, ge=60, le=3600)
    agent_online_seconds: int = Field(default=30, ge=5, le=300)
    min_password_length: int = 12

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / '.env', extra='ignore',
        populate_by_name=True,
        alias_generator=AliasGenerator(validation_alias=lambda name: AliasChoices('MARKIFY_' + name.upper(), name.upper())),
    )


settings = Settings()
