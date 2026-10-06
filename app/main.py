from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from . import config
from .db import Base, engine
from .routers import assets, lots, public, stations
from .rules import RuleError


@asynccontextmanager
async def lifespan(_: FastAPI):
    # MVP: crear tablas al arrancar. Siguiente paso: migraciones con Alembic.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="TrazaRAEE API",
    version="0.1.0",
    description="Trazabilidad de residuos electrónicos para cooperativas de reciclaje informático (prototipo).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RuleError)
async def rule_error_handler(_: Request, exc: RuleError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError):
    # Típicamente: dos estaciones escribieron a la vez sobre el mismo sujeto.
    # El cliente puede reintentar con el mismo client_id sin duplicar nada.
    return JSONResponse(
        status_code=409,
        content={"detail": "Conflicto de concurrencia, reintentar", "code": "conflicto_cadena"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(stations.router)
app.include_router(lots.router)
app.include_router(assets.router)
app.include_router(public.router)
