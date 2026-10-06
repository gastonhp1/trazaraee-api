from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Fecha/hora siempre con zona UTC al leer.

    SQLite descarta la zona horaria al guardar y devuelve datetimes "naive"; el cliente los
    interpretaría como hora local (en Argentina, 3 horas corridas). Con Postgres es un no-op.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Station(Base):
    """Puesto de trabajo (mesa de desarme, banco de pruebas, balanza...).

    Las acciones se atribuyen a estaciones, no a personas: la cooperativa trabaja
    en equipo y el sistema no debe convertirse en una herramienta de control individual.
    """

    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(26), unique=True, index=True)
    generator_name: Mapped[str] = mapped_column(String(200))
    # Por defecto el generador NO es visible en la vista pública del QR.
    generator_public: Mapped[bool] = mapped_column(Boolean, default=False)
    weight_kg: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Asset(Base):
    """Un equipo o componente individual con QR propio."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(26), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(200))
    serial: Mapped[str | None] = mapped_column(String(120), nullable=True)  # privado
    has_storage: Mapped[bool] = mapped_column(Boolean, default=False)
    wiped: Mapped[bool] = mapped_column(Boolean, default=False)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ingresado", index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), index=True)
    # Genealogía: de qué equipo se extrajo este componente...
    source_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    # ...y en qué equipo terminó instalado.
    installed_in_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Fraction(Base):
    """Salida de scrap por fracción de material (plástico, hierro, placas...)."""

    __tablename__ = "fractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id"), index=True)
    material: Mapped[str] = mapped_column(String(30))
    weight_kg: Mapped[float] = mapped_column(Float)
    destination: Mapped[str] = mapped_column(String(200))
    destination_kind: Mapped[str] = mapped_column(String(30))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    client_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Event(Base):
    """Evento append-only con hash encadenado, por sujeto (lote o activo)."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_subject", "subject_type", "subject_id"),
        # Dos eventos no pueden colgar del mismo hash previo: evita bifurcar la cadena
        # cuando dos estaciones escriben a la vez sobre el mismo sujeto.
        UniqueConstraint("subject_type", "subject_id", "prev_hash", name="uq_events_chain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(10))  # "lot" | "asset"
    subject_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(30))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Se guarda como texto ISO porque entra tal cual en el hash.
    created_at: Mapped[str] = mapped_column(String(40))
    # ID generado por el cliente: hace idempotentes los reintentos de la cola offline.
    client_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
