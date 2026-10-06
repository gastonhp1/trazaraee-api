from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..ids import new_public_id
from ..models import Asset, Event, Fraction, Lot, Station
from ..rules import REUSE, STOCK
from ..schemas import (
    BalanceOut,
    EventOut,
    FractionCreate,
    FractionOut,
    LotCreate,
    LotOut,
    VerifyOut,
)
from ..security import require_station
from ..services import events_for, get_lot, record_event, verify_chain

router = APIRouter(prefix="/lots", tags=["lotes"])


def lot_out(lot: Lot) -> LotOut:
    return LotOut(
        public_id=lot.public_id,
        generator_name=lot.generator_name,
        generator_public=lot.generator_public,
        weight_kg=lot.weight_kg,
        notes=lot.notes,
        received_at=lot.received_at,
    )


def event_out(db: Session, ev: Event) -> EventOut:
    station = db.get(Station, ev.station_id)
    return EventOut(
        id=ev.id,
        type=ev.type,
        station=station.name if station else "?",
        payload=ev.payload,
        created_at=ev.created_at,
        hash=ev.hash,
    )


@router.post("", response_model=LotOut, status_code=201)
def create_lot(body: LotCreate, db: Session = Depends(get_db), station: Station = Depends(require_station)):
    # Idempotente: la cola offline puede reenviar el mismo alta.
    if body.public_id:
        existing = db.scalar(select(Lot).where(Lot.public_id == body.public_id))
        if existing:
            return lot_out(existing)
    lot = Lot(
        public_id=body.public_id or new_public_id(),
        generator_name=body.generator_name.strip(),
        generator_public=body.generator_public,
        weight_kg=body.weight_kg,
        notes=body.notes,
        station_id=station.id,
    )
    db.add(lot)
    db.flush()
    record_event(
        db,
        subject_type="lot",
        subject=lot,
        type="ingreso_lote",
        station=station,
        payload={"weight_kg": lot.weight_kg},
        client_id=body.client_id,
    )
    db.commit()
    return lot_out(lot)


@router.get("", response_model=list[LotOut])
def list_lots(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Station = Depends(require_station),
):
    lots = db.scalars(select(Lot).order_by(Lot.id.desc()).limit(limit))
    return [lot_out(lot) for lot in lots]


@router.get("/{public_id}", response_model=LotOut)
def read_lot(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    return lot_out(get_lot(db, public_id))


@router.get("/{public_id}/events", response_model=list[EventOut])
def lot_events(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    lot = get_lot(db, public_id)
    return [event_out(db, ev) for ev in events_for(db, "lot", lot.id)]


@router.get("/{public_id}/verify", response_model=VerifyOut)
def lot_verify(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    return verify_chain(db, "lot", get_lot(db, public_id))


@router.post("/{public_id}/fractions", response_model=FractionOut, status_code=201)
def add_fraction(
    public_id: str,
    body: FractionCreate,
    db: Session = Depends(get_db),
    station: Station = Depends(require_station),
):
    lot = get_lot(db, public_id)
    if body.client_id:
        existing = db.scalar(select(Fraction).where(Fraction.client_id == body.client_id))
        if existing:
            return FractionOut.model_validate(existing, from_attributes=True)
    fraction = Fraction(
        lot_id=lot.id,
        material=body.material,
        weight_kg=body.weight_kg,
        destination=body.destination.strip(),
        destination_kind=body.destination_kind,
        station_id=station.id,
        client_id=body.client_id,
    )
    db.add(fraction)
    db.flush()
    record_event(
        db,
        subject_type="lot",
        subject=lot,
        type="fraccion",
        station=station,
        payload={
            "material": fraction.material,
            "weight_kg": fraction.weight_kg,
            "destination": fraction.destination,
            "destination_kind": fraction.destination_kind,
        },
    )
    db.commit()
    return FractionOut.model_validate(fraction, from_attributes=True)


@router.get("/{public_id}/fractions", response_model=list[FractionOut])
def list_fractions(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    lot = get_lot(db, public_id)
    rows = db.scalars(select(Fraction).where(Fraction.lot_id == lot.id).order_by(Fraction.id))
    return [FractionOut.model_validate(r, from_attributes=True) for r in rows]


def compute_balance(db: Session, lot: Lot, tolerance_pct: float = 2.0) -> BalanceOut:
    """Balance de masas del lote.

    Regla de contabilidad: un equipo desarmado o enviado a scrap deja de contar; su masa
    debe reaparecer como componentes (en stock o reutilizados) y como fracciones.
    Lo que no aparece en ningún lado es 'unaccounted_kg'.
    """

    def _sum_weight(statuses: set[str]) -> float:
        return float(
            db.scalar(
                select(func.coalesce(func.sum(Asset.weight_kg), 0.0)).where(
                    Asset.lot_id == lot.id, Asset.status.in_(statuses)
                )
            )
            or 0.0
        )

    stock = _sum_weight(STOCK)
    reuse = _sum_weight(REUSE)
    fractions = float(
        db.scalar(select(func.coalesce(func.sum(Fraction.weight_kg), 0.0)).where(Fraction.lot_id == lot.id)) or 0.0
    )
    no_weight = int(
        db.scalar(
            select(func.count())
            .select_from(Asset)
            .where(Asset.lot_id == lot.id, Asset.weight_kg.is_(None), Asset.status.in_(STOCK | REUSE))
        )
        or 0
    )
    unaccounted = round(lot.weight_kg - stock - reuse - fractions, 3)
    tolerance = round(lot.weight_kg * tolerance_pct / 100, 3)
    return BalanceOut(
        entered_kg=lot.weight_kg,
        stock_kg=round(stock, 3),
        reuse_kg=round(reuse, 3),
        fractions_kg=round(fractions, 3),
        unaccounted_kg=unaccounted,
        tolerance_kg=tolerance,
        balanced=abs(unaccounted) <= tolerance,
        assets_without_weight=no_weight,
    )


@router.get("/{public_id}/balance", response_model=BalanceOut)
def lot_balance(
    public_id: str,
    tolerance_pct: float = Query(2.0, ge=0, le=50),
    db: Session = Depends(get_db),
    _: Station = Depends(require_station),
):
    return compute_balance(db, get_lot(db, public_id), tolerance_pct)
