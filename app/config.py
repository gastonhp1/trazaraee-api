import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./trazaraee.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
