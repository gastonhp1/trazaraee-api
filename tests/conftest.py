import os
import tempfile

# La configuración se lee al importar la app: hay que fijarla antes.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ADMIN_KEY"] = "admin-test"
os.environ["PUBLIC_BASE_URL"] = "https://trazas.test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/stations", json={"name": "Banco de pruebas"}, headers={"X-Admin-Key": "admin-test"})
    assert r.status_code == 201
    return {"X-Station-Key": r.json()["key"]}


def make_lot(client, auth, **over):
    body = {"generator_name": "Empresa Ejemplo SA", "weight_kg": 100, **over}
    r = client.post("/lots", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def make_asset(client, auth, lot, **over):
    body = {"lot_public_id": lot["public_id"], "kind": "computadora", "label": "PC Dell", **over}
    r = client.post("/assets", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def post_event(client, auth, asset, type, payload=None, **extra):
    return client.post(
        f"/assets/{asset['public_id']}/events",
        json={"type": type, "payload": payload or {}, **extra},
        headers=auth,
    )
