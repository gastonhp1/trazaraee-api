import hashlib
import hmac

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import Station


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not config.ADMIN_KEY:
        raise HTTPException(503, "ADMIN_KEY no está configurada en el servidor")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, config.ADMIN_KEY):
        raise HTTPException(401, "Clave de administración inválida")


def require_station(
    x_station_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Station:
    if not x_station_key:
        raise HTTPException(401, "Falta la clave de la estación (X-Station-Key)")
    station = db.scalar(select(Station).where(Station.key_hash == hash_key(x_station_key)))
    if station is None or not station.active:
        raise HTTPException(401, "Clave de estación inválida")
    return station
