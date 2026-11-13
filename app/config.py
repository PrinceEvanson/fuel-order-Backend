import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    ENV = _get("ENV", "dev")
    JWT_SECRET = _get("JWT_SECRET")
    JWT_EXPIRE_MINUTES = int(_get("JWT_EXPIRE_MINUTES", "480"))
    DATABASE_URL = _get("DATABASE_URL", "sqlite:///./fuel.db")
    ALLOWED_ORIGINS = [o.strip() for o in _get(
        "ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    FRONTEND_URL = _get("FRONTEND_URL", "http://localhost:5173")

    ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    MAX_UPLOAD_MB = int(_get("MAX_UPLOAD_MB", "4"))

    SAGE_CLIENT_ID = _get("SAGE_CLIENT_ID")
    SAGE_CLIENT_SECRET = _get("SAGE_CLIENT_SECRET")
    SAGE_REDIRECT_URI = _get(
        "SAGE_REDIRECT_URI", "http://localhost:8000/api/sage/callback")
    SAGE_WEB_QUOTE_URL = _get("SAGE_WEB_QUOTE_URL",
                              "https://accounting.sage.com/sales_quotes/{id}")
    SAGE_SALES_LEDGER_ACCOUNT_ID = _get("SAGE_SALES_LEDGER_ACCOUNT_ID")
    SAGE_TAX_RATE_ID = _get("SAGE_TAX_RATE_ID")

    def __init__(self) -> None:
        if not self.JWT_SECRET:
            if self.ENV == "dev":
                self.JWT_SECRET = "dev-only-secret-do-not-use-in-production"
            else:
                raise RuntimeError("JWT_SECRET must be set outside dev")


settings = Settings()
