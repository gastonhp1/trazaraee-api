from conftest import make_asset, make_lot, post_event


def test_full_flow_requires_wipe_before_donation(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot, serial="SN-123", has_storage=True, weight_kg=8)

    assert post_event(client, auth, pc, "prueba", {"result": "ok"}).status_code == 201

    # Con almacenamiento y sin borrado, la donación se rechaza.
    r = post_event(client, auth, pc, "donacion", {"destinatario": "Escuela N° 1"})
    assert r.status_code == 409
    assert r.json()["code"] == "regla"

    assert post_event(client, auth, pc, "borrado", {"method": "nwipe", "result": "ok"}).status_code == 201
    assert post_event(client, auth, pc, "donacion", {"destinatario": "Escuela N° 1"}).status_code == 201

    got = client.get(f"/assets/{pc['public_id']}", headers=auth).json()
    assert got["status"] == "donado"
    assert got["wiped"] is True

    # Estado final: no admite más eventos operativos.
    assert post_event(client, auth, pc, "donacion", {"destinatario": "X"}).status_code == 409

    v = client.get(f"/assets/{pc['public_id']}/verify", headers=auth).json()
    # ingreso, prueba, borrado, donacion: los intentos rechazados no dejan evento.
    assert v["ok"] is True and v["events"] == 4


def test_failed_wipe_does_not_unlock(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot, has_storage=True)
    post_event(client, auth, pc, "prueba", {"result": "ok"})
    post_event(client, auth, pc, "borrado", {"method": "nwipe", "result": "falla"})
    r = post_event(client, auth, pc, "donacion", {"destinatario": "Alguien"})
    assert r.status_code == 409


def test_transition_and_payload_rules(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)

    # No se dona algo que no fue probado.
    assert post_event(client, auth, pc, "donacion", {"destinatario": "X"}).status_code == 409
    # Payload inválido -> 422
    assert post_event(client, auth, pc, "prueba", {"result": "quizas"}).status_code == 422

    post_event(client, auth, pc, "prueba", {"result": "ok"})
    assert post_event(client, auth, pc, "donacion", {}).status_code == 422  # falta destinatario
    # scrap sólo desde 'falla'
    assert post_event(client, auth, pc, "scrap").status_code == 409
    # borrado sobre un equipo sin almacenamiento
    assert post_event(client, auth, pc, "borrado", {"method": "x", "result": "ok"}).status_code == 409


def test_tampering_breaks_the_chain(client, auth):
    from app.db import SessionLocal
    from app.models import Event

    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    post_event(client, auth, pc, "prueba", {"result": "falla"})
    post_event(client, auth, pc, "nota", {"text": "placa quemada"})

    assert client.get(f"/assets/{pc['public_id']}/verify", headers=auth).json()["ok"] is True

    # Alguien edita a mano un evento viejo en la base.
    with SessionLocal() as db:
        ev = db.query(Event).filter(Event.type == "prueba").one()
        ev.payload = {"result": "ok"}
        broken_id = ev.id
        db.commit()

    v = client.get(f"/assets/{pc['public_id']}/verify", headers=auth).json()
    assert v["ok"] is False
    assert v["broken_at_event_id"] == broken_id


def test_client_id_makes_events_idempotent(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)

    a = post_event(client, auth, pc, "prueba", {"result": "ok"}, client_id="cola-0001")
    b = post_event(client, auth, pc, "prueba", {"result": "ok"}, client_id="cola-0001")
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] == b.json()["id"]

    events = client.get(f"/assets/{pc['public_id']}/events", headers=auth).json()
    assert [e["type"] for e in events] == ["ingreso", "prueba"]


def test_offline_creation_with_client_generated_ids_is_idempotent(client, auth):
    pid = "abcdefghij234"
    body = {"public_id": pid, "generator_name": "Offline SA", "weight_kg": 10}
    first = client.post("/lots", json=body, headers=auth)
    again = client.post("/lots", json=body, headers=auth)
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["public_id"] == again.json()["public_id"] == pid

    bad = client.post("/lots", json={**body, "public_id": "NO-VALIDO"}, headers=auth)
    assert bad.status_code == 422


def test_genealogy_disassembly_and_install(client, auth):
    lot = make_lot(client, auth)
    old_pc = make_asset(client, auth, lot, label="PC rota", has_storage=True, weight_kg=8)
    target = make_asset(client, auth, lot, label="PC a refuncionalizar", weight_kg=7)

    post_event(client, auth, old_pc, "prueba", {"result": "falla"})
    r = client.post(
        f"/assets/{old_pc['public_id']}/disassemble",
        json={
            "components": [
                {"kind": "disco", "label": "HDD 500GB", "serial": "WD-1", "weight_kg": 0.4},
                {"kind": "ram", "label": "RAM 4GB DDR3", "weight_kg": 0.05},
            ]
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    disk, ram = r.json()
    assert disk["has_storage"] is True  # inferido por el tipo
    assert disk["source_asset_public_id"] == old_pc["public_id"]
    assert client.get(f"/assets/{old_pc['public_id']}", headers=auth).json()["status"] == "desarmado"

    post_event(client, auth, disk, "prueba", {"result": "ok"})
    post_event(client, auth, target, "prueba", {"result": "ok"})

    # El disco no puede instalarse sin borrado.
    r = client.post(f"/assets/{target['public_id']}/install", json={"component_public_id": disk["public_id"]}, headers=auth)
    assert r.status_code == 409

    post_event(client, auth, disk, "borrado", {"method": "nwipe", "result": "ok"})
    r = client.post(f"/assets/{target['public_id']}/install", json={"component_public_id": disk["public_id"]}, headers=auth)
    assert r.status_code == 200, r.text

    g_disk = client.get(f"/assets/{disk['public_id']}/genealogy", headers=auth).json()
    assert [a["public_id"] for a in g_disk["ancestors"]] == [old_pc["public_id"]]
    assert g_disk["installed_in"]["public_id"] == target["public_id"]
    assert g_disk["asset"]["status"] == "instalado"

    g_target = client.get(f"/assets/{target['public_id']}/genealogy", headers=auth).json()
    assert [a["public_id"] for a in g_target["installed_components"]] == [disk["public_id"]]

    g_old = client.get(f"/assets/{old_pc['public_id']}/genealogy", headers=auth).json()
    assert {a["public_id"] for a in g_old["harvested_components"]} == {disk["public_id"], ram["public_id"]}

    # Reintentar el desarme con el mismo client_id no duplica componentes.
    # (el equipo ya está desarmado, así que se prueba con uno nuevo)
    other = make_asset(client, auth, lot, label="Otra PC rota")
    post_event(client, auth, other, "prueba", {"result": "falla"})
    # Los IDs de los componentes los puede elegir el cliente (para etiquetar sin conexión).
    body = {
        "components": [{"public_id": "compocompo234", "kind": "placa", "label": "Motherboard"}],
        "client_id": "dis-001",
    }
    one = client.post(f"/assets/{other['public_id']}/disassemble", json=body, headers=auth)
    two = client.post(f"/assets/{other['public_id']}/disassemble", json=body, headers=auth)
    assert one.status_code == 201 and two.status_code == 201
    assert one.json()[0]["public_id"] == two.json()[0]["public_id"] == "compocompo234"


def test_mass_balance(client, auth):
    lot = make_lot(client, auth, weight_kg=100)
    donated = make_asset(client, auth, lot, weight_kg=20)
    make_asset(client, auth, lot, weight_kg=45)  # sigue en stock (ingresado)

    post_event(client, auth, donated, "prueba", {"result": "ok"})
    post_event(client, auth, donated, "donacion", {"destinatario": "Escuela N° 3"})

    def add_fraction(kg):
        r = client.post(
            f"/lots/{lot['public_id']}/fractions",
            json={"material": "plastico", "weight_kg": kg, "destination": "Recicladora SA", "destination_kind": "recicladora"},
            headers=auth,
        )
        assert r.status_code == 201, r.text

    add_fraction(30)
    b = client.get(f"/lots/{lot['public_id']}/balance", headers=auth).json()
    assert b["stock_kg"] == 45 and b["reuse_kg"] == 20 and b["fractions_kg"] == 30
    assert b["unaccounted_kg"] == 5
    assert b["balanced"] is False  # 5 kg > 2% de 100

    add_fraction(5)
    b = client.get(f"/lots/{lot['public_id']}/balance", headers=auth).json()
    assert b["unaccounted_kg"] == 0 and b["balanced"] is True


def test_public_view_hides_private_data(client, auth):
    lot = make_lot(client, auth, generator_name="Planta Confidencial")
    pc = make_asset(client, auth, lot, serial="SN-SECRETO-999", has_storage=True)
    post_event(client, auth, pc, "prueba", {"result": "ok"})
    post_event(client, auth, pc, "borrado", {"method": "nwipe", "result": "ok"})
    post_event(client, auth, pc, "donacion", {"destinatario": "Receptor Privado"})
    post_event(client, auth, pc, "nota", {"text": "nota interna"})

    r = client.get(f"/public/a/{pc['public_id']}")  # sin autenticación
    assert r.status_code == 200
    data = r.json()
    text = r.text
    assert data["origin"] == "Generador reservado"
    assert data["data_wipe_certified"] is True
    assert data["chain_verified"] is True
    assert [t["type"] for t in data["timeline"]] == ["ingreso", "prueba", "borrado", "donacion"]
    for secret in ("SN-SECRETO-999", "Receptor Privado", "Planta Confidencial", "Banco de pruebas", "nota interna"):
        assert secret not in text

    # Si la cooperativa lo habilita, el generador se muestra.
    lot2 = make_lot(client, auth, generator_name="Escuela Modelo", generator_public=True)
    pc2 = make_asset(client, auth, lot2)
    assert client.get(f"/public/a/{pc2['public_id']}").json()["origin"] == "Escuela Modelo"

    pl = client.get(f"/public/l/{lot['public_id']}")
    assert pl.status_code == 200 and "Planta Confidencial" not in pl.text


def test_datetimes_are_returned_with_utc_offset(client, auth):
    """Regresión: con SQLite las fechas volvían sin zona y el cliente las leía como hora local."""
    from datetime import datetime

    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    reads = [
        client.get(f"/lots/{lot['public_id']}", headers=auth).json()["received_at"],
        client.get(f"/assets/{pc['public_id']}", headers=auth).json()["created_at"],
        client.get(f"/public/a/{pc['public_id']}").json()["received_at"],
        client.get(f"/public/l/{lot['public_id']}").json()["received_at"],
    ]
    for value in reads:
        assert datetime.fromisoformat(value).utcoffset() is not None, value


def test_auth_is_required_for_private_endpoints(client, auth):
    assert client.get("/lots").status_code == 401
    assert client.get("/lots", headers={"X-Station-Key": "tr_falsa"}).status_code == 401
    assert client.post("/stations", json={"name": "Otra"}).status_code == 401
    assert client.post("/stations", json={"name": "Otra"}, headers={"X-Admin-Key": "mala"}).status_code == 401
    assert client.get("/stations/me", headers=auth).json()["name"] == "Banco de pruebas"
    assert client.get("/health").json() == {"status": "ok"}


def test_labels_encode_the_public_url_only(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot, serial="SN-NO-DEBE-ESTAR")
    r = client.get(f"/labels/a/{pc['public_id']}.svg", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in r.text
    assert client.get(f"/labels/a/{pc['public_id']}.png", headers=auth).content[:4] == b"\x89PNG"
    assert client.get(f"/labels/x/{pc['public_id']}.svg", headers=auth).status_code == 404
    assert client.get(f"/labels/a/{pc['public_id']}.svg").status_code == 401
