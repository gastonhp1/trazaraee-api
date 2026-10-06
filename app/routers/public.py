"""Vista pública: lo que ve cualquiera que escanea el QR, sin autenticarse.

Principios de privacidad:
  * No se expone el serial, ni los destinatarios, ni quién (qué estación) hizo cada paso.
  * El generador del lote sólo se muestra si la cooperativa lo marcó como público.
  * La línea de tiempo muestra tipos de evento y fechas, nada del payload.
"""

import io

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..models import Asset, Fraction, Lot
from ..rules import REUSE
from ..schemas import PublicAssetOut, PublicLotOut, PublicTimelineItem
from ..security import require_station
from ..services import events_for, get_asset, get_lot, verify_chain

router = APIRouter(tags=["público"])

_HIDDEN_ORIGIN = "Generador reservado"


def _origin(lot: Lot) -> str:
    return lot.generator_name if lot.generator_public else _HIDDEN_ORIGIN


@router.get("/public/a/{public_id}", response_model=PublicAssetOut)
def public_asset(public_id: str, db: Session = Depends(get_db)):
    asset = get_asset(db, public_id)
    lot = db.get(Lot, asset.lot_id)
    events = events_for(db, "asset", asset.id)
    # Notas y fotos son internas: nunca se muestran en la vista pública.
    visible = [e for e in events if e.type not in ("nota", "foto", "foto_eliminada")]
    return PublicAssetOut(
        public_id=asset.public_id,
        kind=asset.kind,
        label=asset.label,
        status=asset.status,
        origin=_origin(lot),
        received_at=lot.received_at,
        data_wipe_certified=asset.wiped,
        chain_verified=verify_chain(db, "asset", asset)["ok"],
        timeline=[PublicTimelineItem(type=e.type, at=e.created_at) for e in visible],
    )


@router.get("/public/l/{public_id}", response_model=PublicLotOut)
def public_lot(public_id: str, db: Session = Depends(get_db)):
    lot = get_lot(db, public_id)
    reuse = float(
        db.scalar(
            select(func.coalesce(func.sum(Asset.weight_kg), 0.0)).where(
                Asset.lot_id == lot.id, Asset.status.in_(REUSE)
            )
        )
        or 0.0
    )

    def _fraction_kg(kind: str) -> float:
        return float(
            db.scalar(
                select(func.coalesce(func.sum(Fraction.weight_kg), 0.0)).where(
                    Fraction.lot_id == lot.id, Fraction.destination_kind == kind
                )
            )
            or 0.0
        )

    return PublicLotOut(
        public_id=lot.public_id,
        origin=_origin(lot),
        received_at=lot.received_at,
        entered_kg=lot.weight_kg,
        reuse_kg=round(reuse, 3),
        recycled_kg=round(_fraction_kg("recicladora"), 3),
        final_disposal_kg=round(_fraction_kg("disposicion_final"), 3),
        chain_verified=verify_chain(db, "lot", lot)["ok"],
    )


@router.get("/labels/{kind}/{public_id}.{fmt}")
def label(
    kind: str,
    public_id: str,
    fmt: str,
    scale: int = 8,
    db: Session = Depends(get_db),
    _=Depends(require_station),
):
    """QR listo para imprimir. kind = 'a' (activo) o 'l' (lote); fmt = 'svg' o 'png'."""
    import segno

    if kind not in ("a", "l") or fmt not in ("svg", "png"):
        raise HTTPException(404, "Etiqueta no encontrada")
    get_asset(db, public_id) if kind == "a" else get_lot(db, public_id)
    qr = segno.make(f"{config.PUBLIC_BASE_URL}/{kind}/{public_id}", error="q")
    buf = io.BytesIO()
    qr.save(buf, kind=fmt, scale=max(2, min(scale, 20)), border=2)
    media = "image/svg+xml" if fmt == "svg" else "image/png"
    return Response(content=buf.getvalue(), media_type=media)
