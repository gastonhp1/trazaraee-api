from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .hashing import GENESIS, event_hash
from .models import Asset, Event, Lot, Station


def get_lot(db: Session, public_id: str) -> Lot:
    lot = db.scalar(select(Lot).where(Lot.public_id == public_id))
    if lot is None:
        raise HTTPException(404, "Lote no encontrado")
    return lot


def get_asset(db: Session, public_id: str) -> Asset:
    asset = db.scalar(select(Asset).where(Asset.public_id == public_id))
    if asset is None:
        raise HTTPException(404, "Activo no encontrado")
    return asset


def last_event(db: Session, subject_type: str, subject_id: int) -> Event | None:
    return db.scalar(
        select(Event)
        .where(Event.subject_type == subject_type, Event.subject_id == subject_id)
        .order_by(Event.id.desc())
        .limit(1)
    )


def find_by_client_id(db: Session, client_id: str | None) -> Event | None:
    if not client_id:
        return None
    return db.scalar(select(Event).where(Event.client_id == client_id))


def record_event(
    db: Session,
    *,
    subject_type: str,
    subject,
    type: str,
    station: Station,
    payload: dict | None = None,
    client_id: str | None = None,
) -> Event:
    """Agrega un evento a la cadena del sujeto. No hace commit."""
    payload = payload or {}
    last = last_event(db, subject_type, subject.id)
    prev = last.hash if last else GENESIS
    created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    h = event_hash(
        prev_hash=prev,
        subject_type=subject_type,
        subject_public_id=subject.public_id,
        type=type,
        station_id=station.id,
        payload=payload,
        created_at=created_at,
    )
    ev = Event(
        subject_type=subject_type,
        subject_id=subject.id,
        type=type,
        station_id=station.id,
        payload=payload,
        prev_hash=prev,
        hash=h,
        created_at=created_at,
        client_id=client_id,
    )
    db.add(ev)
    db.flush()
    return ev


def events_for(db: Session, subject_type: str, subject_id: int) -> list[Event]:
    return list(
        db.scalars(
            select(Event)
            .where(Event.subject_type == subject_type, Event.subject_id == subject_id)
            .order_by(Event.id)
        )
    )


def verify_chain(db: Session, subject_type: str, subject) -> dict:
    """Recalcula la cadena completa. Devuelve dónde se rompe, si se rompe."""
    prev = GENESIS
    events = events_for(db, subject_type, subject.id)
    for ev in events:
        expected = event_hash(
            prev_hash=prev,
            subject_type=subject_type,
            subject_public_id=subject.public_id,
            type=ev.type,
            station_id=ev.station_id,
            payload=ev.payload,
            created_at=ev.created_at,
        )
        if ev.prev_hash != prev or ev.hash != expected:
            return {"ok": False, "events": len(events), "broken_at_event_id": ev.id}
        prev = ev.hash
    return {"ok": True, "events": len(events), "broken_at_event_id": None, "head": prev}
