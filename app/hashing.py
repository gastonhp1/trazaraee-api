"""Cadena de hashes por sujeto (lote o activo).

Cada evento incluye el hash del evento anterior del mismo sujeto. Si alguien edita
un evento viejo directamente en la base, la verificación detecta dónde se rompe.
Para anclar la cadena fuera del sistema (opcional, fase 2) alcanza con publicar
periódicamente el hash del último evento de cada sujeto.
"""

import hashlib
import json

GENESIS = "0" * 64


def event_hash(
    *,
    prev_hash: str,
    subject_type: str,
    subject_public_id: str,
    type: str,
    station_id: int,
    payload: dict,
    created_at: str,
) -> str:
    canonical = json.dumps(
        {
            "prev": prev_hash,
            "subject_type": subject_type,
            "subject": subject_public_id,
            "type": type,
            "station": station_id,
            "payload": payload,
            "at": created_at,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
