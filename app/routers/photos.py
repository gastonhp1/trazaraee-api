"""Fotos de lotes y equipos.

Decisiones de diseño:
  * La foto se guarda en disco y su SHA-256 entra en la cadena de hashes del sujeto (evento
    'foto'). Una foto reemplazada después no coincide con el hash registrado.
  * Las fotos son PRIVADAS: sólo las ve personal autenticado. Nunca aparecen en la vista
    pública, porque pueden mostrar números de serie, logos o etiquetas que delaten al generador.
  * Se pueden eliminar (por ejemplo, si salió una persona o una pantalla con datos): se borra la
    imagen pero el historial conserva que existió (evento 'foto_eliminada' con el mismo hash).
"""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, storage
from ..db import get_db
from ..ids import new_public_id, valid_public_id
from ..models import Asset, Lot, Photo, Station
from ..schemas import PhotoOut
from ..security import require_station
from ..services import get_asset, get_lot, record_event

router = APIRouter(tags=["fotos"])


def photo_out(p: Photo) -> PhotoOut:
    return PhotoOut(
        public_id=p.public_id,
        content_type=p.content_type,
        size_bytes=p.size_bytes,
        sha256=p.sha256,
        caption=p.caption,
        created_at=p.created_at,
    )


def _subject(db: Session, kind: str, public_id: str):
    if kind == "assets":
        return "asset", get_asset(db, public_id)
    return "lot", get_lot(db, public_id)


def _store(
    db: Session,
    station: Station,
    kind: str,
    public_id: str,
    data: bytes,
    photo_id: str,
    caption: str | None,
) -> PhotoOut:
    subject_type, subject = _subject(db, kind, public_id)

    # Idempotente: la cola offline puede reenviar la misma foto.
    existing = db.scalar(select(Photo).where(Photo.public_id == photo_id))
    if existing:
        if existing.subject_type != subject_type or existing.subject_id != subject.id:
            raise HTTPException(409, "Ese photo_id ya se usó en otro sujeto")
        return photo_out(existing)

    sniffed = storage.sniff(data)
    if sniffed is None:
        raise HTTPException(422, "El archivo no es una imagen JPEG, PNG o WebP")
    content_type, _ext = sniffed

    count = db.scalar(
        select(func.count())
        .select_from(Photo)
        .where(Photo.subject_type == subject_type, Photo.subject_id == subject.id, Photo.deleted_at.is_(None))
    )
    if count >= config.MAX_PHOTOS_PER_SUBJECT:
        raise HTTPException(409, f"Se alcanzó el máximo de {config.MAX_PHOTOS_PER_SUBJECT} fotos para este registro")

    sha = hashlib.sha256(data).hexdigest()
    photo = Photo(
        public_id=photo_id,
        subject_type=subject_type,
        subject_id=subject.id,
        sha256=sha,
        content_type=content_type,
        size_bytes=len(data),
        caption=caption.strip() if caption and caption.strip() else None,
        station_id=station.id,
    )
    db.add(photo)
    db.flush()

    payload = {"photo": photo_id, "sha256": sha}
    if photo.caption:
        payload["caption"] = photo.caption
    record_event(
        db,
        subject_type=subject_type,
        subject=subject,
        type="foto",
        station=station,
        payload=payload,
        client_id=f"photo:{photo_id}",
    )

    # Primero el archivo y después el commit; si el commit falla, se limpia el archivo.
    key = storage.key_for(photo_id, content_type)
    storage.save(key, data)
    try:
        db.commit()
    except Exception:
        storage.delete(key)
        raise
    return photo_out(photo)


async def _upload(
    kind: str,
    public_id: str,
    request: Request,
    photo_id: str | None,
    caption: str | None,
    db: Session,
    station: Station,
) -> PhotoOut:
    if photo_id is None:
        photo_id = new_public_id()
    elif not valid_public_id(photo_id):
        raise HTTPException(422, "photo_id inválido (10-26 caracteres base32 en minúscula)")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > config.MAX_PHOTO_BYTES:
        raise HTTPException(413, f"La foto supera el máximo de {config.MAX_PHOTO_BYTES // 1024} KB")
    data = await request.body()
    if len(data) > config.MAX_PHOTO_BYTES:
        raise HTTPException(413, f"La foto supera el máximo de {config.MAX_PHOTO_BYTES // 1024} KB")
    if not data:
        raise HTTPException(422, "No se recibió ninguna imagen")

    return await run_in_threadpool(_store, db, station, kind, public_id, data, photo_id, caption)


@router.post("/assets/{public_id}/photos", response_model=PhotoOut, status_code=201)
async def upload_asset_photo(
    public_id: str,
    request: Request,
    photo_id: str | None = Query(None),
    caption: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
    station: Station = Depends(require_station),
):
    """Cuerpo = bytes de la imagen (image/jpeg, image/png o image/webp)."""
    return await _upload("assets", public_id, request, photo_id, caption, db, station)


@router.post("/lots/{public_id}/photos", response_model=PhotoOut, status_code=201)
async def upload_lot_photo(
    public_id: str,
    request: Request,
    photo_id: str | None = Query(None),
    caption: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
    station: Station = Depends(require_station),
):
    return await _upload("lots", public_id, request, photo_id, caption, db, station)


def _list(db: Session, kind: str, public_id: str) -> list[PhotoOut]:
    subject_type, subject = _subject(db, kind, public_id)
    rows = db.scalars(
        select(Photo)
        .where(Photo.subject_type == subject_type, Photo.subject_id == subject.id, Photo.deleted_at.is_(None))
        .order_by(Photo.id)
    )
    return [photo_out(p) for p in rows]


@router.get("/assets/{public_id}/photos", response_model=list[PhotoOut])
def list_asset_photos(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    return _list(db, "assets", public_id)


@router.get("/lots/{public_id}/photos", response_model=list[PhotoOut])
def list_lot_photos(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    return _list(db, "lots", public_id)


def _get_photo(db: Session, public_id: str) -> Photo:
    photo = db.scalar(select(Photo).where(Photo.public_id == public_id))
    if photo is None:
        raise HTTPException(404, "Foto no encontrada")
    return photo


@router.get("/photos/{public_id}")
def get_photo(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    photo = _get_photo(db, public_id)
    if photo.deleted_at is not None:
        raise HTTPException(410, "La foto fue eliminada")
    try:
        data = storage.read(storage.key_for(photo.public_id, photo.content_type))
    except FileNotFoundError:
        raise HTTPException(404, "El archivo de la foto no está disponible")
    return Response(
        content=data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/photos/{public_id}", status_code=204)
def delete_photo(public_id: str, db: Session = Depends(get_db), station: Station = Depends(require_station)):
    photo = _get_photo(db, public_id)
    if photo.deleted_at is None:
        subject = db.get(Asset if photo.subject_type == "asset" else Lot, photo.subject_id)
        record_event(
            db,
            subject_type=photo.subject_type,
            subject=subject,
            type="foto_eliminada",
            station=station,
            payload={"photo": photo.public_id, "sha256": photo.sha256},
        )
        photo.deleted_at = datetime.now(timezone.utc)
        db.commit()
        storage.delete(storage.key_for(photo.public_id, photo.content_type))
    return Response(status_code=204)
