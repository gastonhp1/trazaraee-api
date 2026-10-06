from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import rules
from ..db import get_db
from ..ids import new_public_id
from ..models import Asset, Lot, Station
from ..schemas import (
    AssetCreate,
    AssetOut,
    AssetRef,
    DisassembleRequest,
    EventCreate,
    EventOut,
    GenealogyOut,
    InstallRequest,
    VerifyOut,
)
from ..security import require_station
from ..services import (
    events_for,
    find_by_client_id,
    get_asset,
    get_lot,
    record_event,
    verify_chain,
)
from .lots import event_out

router = APIRouter(prefix="/assets", tags=["activos"])


def _pid(db: Session, asset_id: int | None) -> str | None:
    if asset_id is None:
        return None
    other = db.get(Asset, asset_id)
    return other.public_id if other else None


def asset_out(db: Session, a: Asset) -> AssetOut:
    lot = db.get(Lot, a.lot_id)
    return AssetOut(
        public_id=a.public_id,
        kind=a.kind,
        label=a.label,
        serial=a.serial,
        has_storage=a.has_storage,
        wiped=a.wiped,
        weight_kg=a.weight_kg,
        status=a.status,
        lot_public_id=lot.public_id,
        source_asset_public_id=_pid(db, a.source_asset_id),
        installed_in_public_id=_pid(db, a.installed_in_id),
        created_at=a.created_at,
    )


def asset_ref(a: Asset) -> AssetRef:
    return AssetRef(public_id=a.public_id, kind=a.kind, label=a.label, status=a.status)


@router.post("", response_model=AssetOut, status_code=201)
def create_asset(body: AssetCreate, db: Session = Depends(get_db), station: Station = Depends(require_station)):
    if body.public_id:
        existing = db.scalar(select(Asset).where(Asset.public_id == body.public_id))
        if existing:  # reintento de la cola offline
            return asset_out(db, existing)
    lot = get_lot(db, body.lot_public_id)
    asset = Asset(
        public_id=body.public_id or new_public_id(),
        kind=body.kind,
        label=body.label.strip(),
        serial=body.serial.strip() if body.serial else None,
        has_storage=body.has_storage or body.kind in rules.STORAGE_KINDS,
        weight_kg=body.weight_kg,
        lot_id=lot.id,
    )
    db.add(asset)
    db.flush()
    record_event(
        db,
        subject_type="asset",
        subject=asset,
        type="ingreso",
        station=station,
        payload={"lot": lot.public_id, "kind": asset.kind},
        client_id=body.client_id,
    )
    db.commit()
    return asset_out(db, asset)


@router.get("", response_model=list[AssetOut])
def list_assets(
    lot: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: Station = Depends(require_station),
):
    q = select(Asset).order_by(Asset.id.desc()).limit(limit)
    if lot:
        q = q.where(Asset.lot_id == get_lot(db, lot).id)
    if status:
        q = q.where(Asset.status == status)
    return [asset_out(db, a) for a in db.scalars(q)]


@router.get("/{public_id}", response_model=AssetOut)
def read_asset(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    return asset_out(db, get_asset(db, public_id))


@router.get("/{public_id}/events", response_model=list[EventOut])
def asset_events(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    asset = get_asset(db, public_id)
    return [event_out(db, ev) for ev in events_for(db, "asset", asset.id)]


@router.get("/{public_id}/verify", response_model=VerifyOut)
def asset_verify(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    return verify_chain(db, "asset", get_asset(db, public_id))


@router.post("/{public_id}/events", response_model=EventOut, status_code=201)
def add_event(
    public_id: str,
    body: EventCreate,
    db: Session = Depends(get_db),
    station: Station = Depends(require_station),
):
    asset = get_asset(db, public_id)

    previous = find_by_client_id(db, body.client_id)
    if previous:
        if previous.subject_type != "asset" or previous.subject_id != asset.id:
            raise HTTPException(409, "client_id ya usado en otro sujeto")
        return event_out(db, previous)

    outcome = rules.apply(asset, body.type, body.payload)
    ev = record_event(
        db,
        subject_type="asset",
        subject=asset,
        type=body.type,
        station=station,
        payload=body.payload,
        client_id=body.client_id,
    )
    asset.status = outcome.status
    if outcome.wiped:
        asset.wiped = True
    db.commit()
    return event_out(db, ev)


@router.post("/{public_id}/disassemble", response_model=list[AssetOut], status_code=201)
def disassemble(
    public_id: str,
    body: DisassembleRequest,
    db: Session = Depends(get_db),
    station: Station = Depends(require_station),
):
    parent = get_asset(db, public_id)

    previous = find_by_client_id(db, body.client_id)
    if previous:
        if previous.subject_type != "asset" or previous.subject_id != parent.id:
            raise HTTPException(409, "client_id ya usado en otro sujeto")
        kids = db.scalars(select(Asset).where(Asset.source_asset_id == parent.id).order_by(Asset.id))
        return [asset_out(db, k) for k in kids]

    outcome = rules.apply(parent, "desarme", {})

    children: list[Asset] = []
    for comp in body.components:
        child = Asset(
            public_id=comp.public_id or new_public_id(),
            kind=comp.kind,
            label=comp.label.strip(),
            serial=comp.serial.strip() if comp.serial else None,
            has_storage=comp.has_storage or comp.kind in rules.STORAGE_KINDS,
            weight_kg=comp.weight_kg,
            lot_id=parent.lot_id,
            source_asset_id=parent.id,
        )
        db.add(child)
        children.append(child)
    db.flush()

    for child in children:
        record_event(
            db,
            subject_type="asset",
            subject=child,
            type="ingreso",
            station=station,
            payload={"origen_desarme": parent.public_id, "kind": child.kind},
        )
    record_event(
        db,
        subject_type="asset",
        subject=parent,
        type="desarme",
        station=station,
        payload={"componentes": [c.public_id for c in children]},
        client_id=body.client_id,
    )
    parent.status = outcome.status
    db.commit()
    return [asset_out(db, c) for c in children]


@router.post("/{public_id}/install", response_model=AssetOut)
def install_component(
    public_id: str,
    body: InstallRequest,
    db: Session = Depends(get_db),
    station: Station = Depends(require_station),
):
    """Instala un componente (que debe estar probado y, si corresponde, borrado) en este equipo."""
    target = get_asset(db, public_id)
    component = get_asset(db, body.component_public_id)

    previous = find_by_client_id(db, body.client_id)
    if previous:
        if previous.subject_type != "asset" or previous.subject_id != component.id:
            raise HTTPException(409, "client_id ya usado en otro sujeto")
        return asset_out(db, target)

    if target.id == component.id:
        raise HTTPException(422, "Un activo no puede instalarse en sí mismo")
    if target.status not in {"funciona", "refuncionalizado"}:
        raise rules.RuleError(
            f"El equipo destino está en estado '{target.status}'; debe estar 'funciona' o 'refuncionalizado'"
        )

    outcome = rules.apply(component, "instalacion", {})
    record_event(
        db,
        subject_type="asset",
        subject=component,
        type="instalacion",
        station=station,
        payload={"instalado_en": target.public_id},
        client_id=body.client_id,
    )
    record_event(
        db,
        subject_type="asset",
        subject=target,
        type="componente_instalado",
        station=station,
        payload={"componente": component.public_id, "kind": component.kind},
    )
    component.status = outcome.status
    component.installed_in_id = target.id
    db.commit()
    return asset_out(db, target)


@router.get("/{public_id}/genealogy", response_model=GenealogyOut)
def genealogy(public_id: str, db: Session = Depends(get_db), _: Station = Depends(require_station)):
    asset = get_asset(db, public_id)

    ancestors: list[AssetRef] = []
    seen = {asset.id}
    cursor = asset
    while cursor.source_asset_id and cursor.source_asset_id not in seen:
        cursor = db.get(Asset, cursor.source_asset_id)
        seen.add(cursor.id)
        ancestors.append(asset_ref(cursor))

    harvested = db.scalars(select(Asset).where(Asset.source_asset_id == asset.id).order_by(Asset.id))
    installed = db.scalars(select(Asset).where(Asset.installed_in_id == asset.id).order_by(Asset.id))
    host = db.get(Asset, asset.installed_in_id) if asset.installed_in_id else None
    return GenealogyOut(
        asset=asset_ref(asset),
        ancestors=ancestors,
        harvested_components=[asset_ref(a) for a in harvested],
        installed_components=[asset_ref(a) for a in installed],
        installed_in=asset_ref(host) if host else None,
    )
