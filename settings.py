import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
ENABLE_NGROK = os.getenv("ENABLE_NGROK", "false").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

# Explicit CORS origin configuration for secure deployment
default_allowed_origins = "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5500,http://localhost:5500"
allowed_origins_env = os.getenv(
    "ALLOWED_ORIGINS",
    default_allowed_origins if ENVIRONMENT != "production" else "",
)
ALLOWED_ORIGINS = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

# Fail fast if critical secrets are missing
if not DATABASE_URL:
    raise ValueError("❌ CRITICAL: DATABASE_URL environment variable is not set in .env file.")
if len(SECRET_KEY) < 32:
    raise ValueError("❌ CRITICAL: SECRET_KEY must be a random value of at least 32 characters.")
if not ADMIN_USERNAME or not ADMIN_PASSWORD_HASH:
    raise ValueError("❌ CRITICAL: ADMIN_USERNAME and ADMIN_PASSWORD_HASH must be configured.")
if not ALLOWED_ORIGINS:
    raise ValueError("❌ CRITICAL: ALLOWED_ORIGINS must be set to at least one explicit origin.")
if "*" in ALLOWED_ORIGINS:
    raise ValueError("❌ CRITICAL: wildcard CORS origins are not allowed.")
if ENVIRONMENT == "production" and ENABLE_NGROK:
    raise ValueError("❌ CRITICAL: ngrok cannot be enabled in production.")