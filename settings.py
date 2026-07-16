import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = "smart_timetable_scedular_seccret_chavi"  # In a real-world scenario, this should be a secure, random key and not hardcoded. and make sure to keep it secret and not expose it in your codebase. Consider using environment variables or a secrets manager for production environments.

# Explicit CORS origin configuration for secure deployment
default_allowed_origins = "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5500,http://localhost:5500"
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", default_allowed_origins)
ALLOWED_ORIGINS = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

# Fail fast if critical secrets are missing
if not DATABASE_URL:
    raise ValueError("❌ CRITICAL: DATABASE_URL environment variable is not set in .env file.")
if not ALLOWED_ORIGINS:
    raise ValueError("❌ CRITICAL: ALLOWED_ORIGINS must be set to at least one explicit origin.")