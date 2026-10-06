"""Almacenamiento de fotos en disco.

Las claves salen siempre de un public_id ya validado (base32) más una extensión fija, así que
no hay forma de escapar del directorio. Para producción a escala conviene reemplazar este módulo
por un bucket (S3 o similar) manteniendo la misma interfaz de tres funciones.
"""

import os
from pathlib import Path

from . import config

EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def sniff(data: bytes) -> tuple[str, str] | None:
    """Identifica el formato por los primeros bytes, ignorando lo que declare el cliente."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def key_for(public_id: str, content_type: str) -> str:
    return f"{public_id}.{EXT_BY_TYPE[content_type]}"


def _path(key: str) -> Path:
    if "/" in key or "\\" in key or ".." in key:
        raise ValueError("clave de almacenamiento inválida")
    return Path(config.PHOTOS_DIR) / key[:2] / key


def save(key: str, data: bytes) -> None:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # escritura atómica: nunca queda una foto a medio escribir


def read(key: str) -> bytes:
    return _path(key).read_bytes()


def delete(key: str) -> None:
    _path(key).unlink(missing_ok=True)
