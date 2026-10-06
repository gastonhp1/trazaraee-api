"""Máquina de estados de un activo.

    ingresado ──prueba──► funciona ──refuncionalizacion──► refuncionalizado
                    │         │  │                              │  │
                    │         │  └──instalacion──► instalado    │  │
                    │         ├──venta──────────► vendido ◄─────┘  │
                    │         ├──donacion───────► donado ◄─────────┘
                    └──────► falla ──scrap──► scrap
                              │
              funciona/falla ─┴──desarme──► desarmado (los componentes nacen como activos nuevos)

Reglas transversales:
  * Si el activo tiene almacenamiento (has_storage), no puede refuncionalizarse, venderse,
    donarse ni instalarse sin un borrado de datos exitoso registrado.
  * 'borrado' y 'nota' no cambian el estado.
"""

from dataclasses import dataclass

STATUSES = {
    "ingresado",
    "funciona",
    "falla",
    "refuncionalizado",
    "vendido",
    "donado",
    "scrap",
    "desarmado",
    "instalado",
}
TERMINAL = {"vendido", "donado", "scrap", "desarmado", "instalado"}
# Estados en los que la masa del activo sigue físicamente en planta.
STOCK = {"ingresado", "funciona", "falla", "refuncionalizado"}
# Estados en los que la masa salió como reutilización.
REUSE = {"vendido", "donado", "instalado"}

GENERIC_EVENT_TYPES = {"prueba", "borrado", "refuncionalizacion", "venta", "donacion", "scrap", "nota"}

KINDS = {"computadora", "notebook", "disco", "ram", "cpu", "placa", "monitor", "impresora", "otro"}
STORAGE_KINDS = {"disco"}


class RuleError(Exception):
    status_code = 409
    code = "regla"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PayloadError(RuleError):
    status_code = 422
    code = "payload"


@dataclass
class Outcome:
    status: str
    wiped: bool | None = None  # None = sin cambios


def _require_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PayloadError(f"Falta '{key}' en el evento")
    return value.strip()


def _need_wipe(asset) -> None:
    if asset.has_storage and not asset.wiped:
        raise RuleError("El equipo tiene almacenamiento y todavía no tiene un borrado de datos exitoso registrado")


def _from(asset, allowed: set[str], event_type: str) -> None:
    if asset.status not in allowed:
        raise RuleError(
            f"No se puede registrar '{event_type}' sobre un activo en estado '{asset.status}'"
        )


def apply(asset, event_type: str, payload: dict) -> Outcome:
    """Valida el evento contra el estado actual y devuelve el estado resultante."""
    if asset.status in TERMINAL and event_type != "nota":
        raise RuleError(f"El activo está en estado final '{asset.status}'")

    if event_type == "nota":
        return Outcome(asset.status)

    if event_type == "prueba":
        _from(asset, {"ingresado", "funciona", "falla"}, event_type)
        result = payload.get("result")
        if result not in ("ok", "falla"):
            raise PayloadError("'result' debe ser 'ok' o 'falla'")
        return Outcome("funciona" if result == "ok" else "falla")

    if event_type == "borrado":
        if not asset.has_storage:
            raise RuleError("El activo no tiene almacenamiento")
        _require_str(payload, "method")
        result = payload.get("result")
        if result not in ("ok", "falla"):
            raise PayloadError("'result' debe ser 'ok' o 'falla'")
        return Outcome(asset.status, wiped=True if result == "ok" else None)

    if event_type == "refuncionalizacion":
        _from(asset, {"funciona"}, event_type)
        _need_wipe(asset)
        return Outcome("refuncionalizado")

    if event_type in ("venta", "donacion"):
        _from(asset, {"funciona", "refuncionalizado"}, event_type)
        _require_str(payload, "destinatario")
        _need_wipe(asset)
        return Outcome("vendido" if event_type == "venta" else "donado")

    if event_type == "scrap":
        _from(asset, {"falla"}, event_type)
        return Outcome("scrap")

    if event_type == "desarme":
        _from(asset, {"funciona", "falla"}, event_type)
        return Outcome("desarmado")

    if event_type == "instalacion":
        _from(asset, {"funciona"}, event_type)
        _need_wipe(asset)
        return Outcome("instalado")

    raise PayloadError(f"Tipo de evento desconocido: {event_type}")
