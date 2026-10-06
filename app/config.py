import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./trazaraee.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5173").rstrip("/")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

# Fotos: carpeta de almacenamiento, tamaño máximo por foto y máximo por lote/equipo.
# Se leen siempre como config.X (no con from-import) para poder ajustarlas en tests.
PHOTOS_DIR = os.environ.get("PHOTOS_DIR", "./photos")
MAX_PHOTO_BYTES = int(os.environ.get("MAX_PHOTO_BYTES", 8 * 1024 * 1024))
MAX_PHOTOS_PER_SUBJECT = int(os.environ.get("MAX_PHOTOS_PER_SUBJECT", 30))
