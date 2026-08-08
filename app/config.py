import secrets
import sys
from typing import Optional

from pydantic import model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that must never be accepted as a real secret, even if supplied.
WEAK_SECRETS = {"", "dev-secret-change-me", "changeme", "secret", "test"}
PRODUCTION_ENVIRONMENTS = {"production", "prod", "staging"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql://gs:gsdev@localhost:5432/glowingstar"
    jwt_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    @model_validator(mode="after")
    def _resolve_jwt_secret(self):
        supplied = (self.jwt_secret or "").strip()
        in_production = self.environment.lower() in PRODUCTION_ENVIRONMENTS

        if supplied and supplied not in WEAK_SECRETS:
            return self

        if in_production:
            raise RuntimeError(
                "JWT_SECRET is missing or set to a known weak value while "
                f"ENVIRONMENT={self.environment!r}. Refusing to start. "
                "Generate one with: python -c "
                "'import secrets; print(secrets.token_urlsafe(32))'"
            )

        self.jwt_secret = secrets.token_urlsafe(32)
        print(
            "[config] No JWT_SECRET supplied - generated an ephemeral one for "
            "this process. All tokens become invalid on restart. Set JWT_SECRET "
            "in .env for a stable development session.",
            file=sys.stderr,
        )
        return self


settings = Settings()
