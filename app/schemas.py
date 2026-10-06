from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .ids import valid_public_id

Kind = Literal["computadora", "notebook", "disco", "ram", "cpu", "placa", "monitor", "impresora", "otro"]
Material = Literal[
    "plastico", "hierro", "aluminio", "cobre", "placas", "cables", "vidrio", "baterias", "toner", "otros"
]
GenericEventType = Literal["prueba", "borrado", "refuncionalizacion", "venta", "donacion", "scrap", "nota"]


class _PublicIdMixin(BaseModel):
    public_id: str | None = None

    @field_validator("public_id")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        if v is not None and not valid_public_id(v):
            raise ValueError("public_id inválido (10-26 caracteres base32 en minúscula)")
        return v


# ---- estaciones ----
class StationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class StationCreated(BaseModel):
    id: int
    name: str
    key: str  # se muestra una sola vez


class StationOut(BaseModel):
    id: int
    name: str


# ---- lotes ----
class LotCreate(_PublicIdMixin):
    generator_name: str = Field(min_length=1, max_length=200)
    generator_public: bool = False
    weight_kg: float = Field(gt=0)
    notes: str | None = Field(default=None, max_length=2000)
    client_id: str | None = Field(default=None, max_length=64)


class LotOut(BaseModel):
    public_id: str
    generator_name: str
    generator_public: bool
    weight_kg: float
    notes: str | None
    received_at: datetime


class FractionCreate(BaseModel):
    material: Material
    weight_kg: float = Field(gt=0)
    destination: str = Field(min_length=1, max_length=200)
    destination_kind: Literal["recicladora", "disposicion_final"]
    client_id: str | None = Field(default=None, max_length=64)


class FractionOut(BaseModel):
    material: str
    weight_kg: float
    destination: str
    destination_kind: str
    created_at: datetime


class BalanceOut(BaseModel):
    entered_kg: float
    stock_kg: float
    reuse_kg: float
    fractions_kg: float
    unaccounted_kg: float
    tolerance_kg: float
    balanced: bool
    assets_without_weight: int


# ---- activos ----
class AssetCreate(_PublicIdMixin):
    lot_public_id: str
    kind: Kind
    label: str = Field(min_length=1, max_length=200)
    serial: str | None = Field(default=None, max_length=120)
    has_storage: bool = False
    weight_kg: float | None = Field(default=None, ge=0)
    client_id: str | None = Field(default=None, max_length=64)


class AssetOut(BaseModel):
    public_id: str
    kind: str
    label: str
    serial: str | None
    has_storage: bool
    wiped: bool
    weight_kg: float | None
    status: str
    lot_public_id: str
    source_asset_public_id: str | None
    installed_in_public_id: str | None
    created_at: datetime


class EventCreate(BaseModel):
    type: GenericEventType
    payload: dict = Field(default_factory=dict)
    client_id: str | None = Field(default=None, max_length=64)


class EventOut(BaseModel):
    id: int
    type: str
    station: str
    payload: dict
    created_at: str
    hash: str


class ComponentIn(_PublicIdMixin):
    # public_id opcional: la PWA lo genera para poder imprimir la etiqueta sin conexión.
    kind: Kind
    label: str = Field(min_length=1, max_length=200)
    serial: str | None = Field(default=None, max_length=120)
    has_storage: bool = False
    weight_kg: float | None = Field(default=None, ge=0)


class DisassembleRequest(BaseModel):
    components: list[ComponentIn] = Field(min_length=1, max_length=50)
    client_id: str | None = Field(default=None, max_length=64)


class InstallRequest(BaseModel):
    component_public_id: str
    client_id: str | None = Field(default=None, max_length=64)


class AssetRef(BaseModel):
    public_id: str
    kind: str
    label: str
    status: str


class GenealogyOut(BaseModel):
    asset: AssetRef
    ancestors: list[AssetRef]  # de dónde salió (el más cercano primero)
    harvested_components: list[AssetRef]  # componentes extraídos al desarmarlo
    installed_components: list[AssetRef]  # componentes instalados en este equipo
    installed_in: AssetRef | None


class VerifyOut(BaseModel):
    ok: bool
    events: int
    broken_at_event_id: int | None
    head: str | None = None


# ---- vista pública (la que abre quien escanea el QR) ----
class PublicTimelineItem(BaseModel):
    type: str
    at: str


class PublicAssetOut(BaseModel):
    public_id: str
    kind: str
    label: str
    status: str
    origin: str
    received_at: datetime
    data_wipe_certified: bool
    chain_verified: bool
    timeline: list[PublicTimelineItem]


class PublicLotOut(BaseModel):
    public_id: str
    origin: str
    received_at: datetime
    entered_kg: float
    reuse_kg: float
    recycled_kg: float
    final_disposal_kg: float
    chain_verified: bool
