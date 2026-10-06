import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Station
from ..schemas import StationCreate, StationCreated, StationOut
from ..security import hash_key, require_admin, require_station

router = APIRouter(prefix="/stations", tags=["estaciones"])


@router.post("", response_model=StationCreated, status_code=201, dependencies=[Depends(require_admin)])
def create_station(body: StationCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    if db.scalar(select(Station).where(Station.name == name)):
        raise HTTPException(409, "Ya existe una estación con ese nombre")
    key = "tr_" + secrets.token_urlsafe(24)
    station = Station(name=name, key_hash=hash_key(key))
    db.add(station)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ya existe una estación con ese nombre")
    return StationCreated(id=station.id, name=station.name, key=key)


@router.get("/me", response_model=StationOut)
def me(station: Station = Depends(require_station)):
    return StationOut(id=station.id, name=station.name)
