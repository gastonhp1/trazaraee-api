import hashlib
from pathlib import Path

from app import config
from conftest import make_asset, make_lot, post_event

# Basta con los primeros bytes: el backend identifica el formato por su firma.
JPEG = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 4
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"webp-body" * 32


def upload(client, auth, kind, pid, data=JPEG, ctype="image/jpeg", **params):
    return client.post(
        f"/{kind}/{pid}/photos",
        params=params,
        content=data,
        headers={**auth, "Content-Type": ctype},
    )


def events(client, auth, kind, pid):
    return client.get(f"/{kind}/{pid}/events", headers=auth).json()


def test_upload_asset_photo_is_stored_hashed_and_chained(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)

    r = upload(client, auth, "assets", pc["public_id"], photo_id="fotofotofoto2", caption="Frente del equipo")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["public_id"] == "fotofotofoto2"
    assert body["sha256"] == hashlib.sha256(JPEG).hexdigest()
    assert body["size_bytes"] == len(JPEG)
    assert body["content_type"] == "image/jpeg"
    assert body["caption"] == "Frente del equipo"

    listed = client.get(f"/assets/{pc['public_id']}/photos", headers=auth).json()
    assert [p["public_id"] for p in listed] == ["fotofotofoto2"]

    got = client.get("/photos/fotofotofoto2", headers=auth)
    assert got.status_code == 200
    assert got.content == JPEG
    assert got.headers["content-type"] == "image/jpeg"
    assert got.headers["cache-control"].startswith("private")

    # El hash de la foto quedó dentro de la cadena de eventos del equipo.
    evs = events(client, auth, "assets", pc["public_id"])
    assert [e["type"] for e in evs] == ["ingreso", "foto"]
    assert evs[1]["payload"]["sha256"] == body["sha256"]
    assert client.get(f"/assets/{pc['public_id']}/verify", headers=auth).json()["ok"] is True


def test_upload_lot_photo(client, auth):
    lot = make_lot(client, auth)
    r = upload(client, auth, "lots", lot["public_id"], data=PNG, ctype="image/png")
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/png"
    assert len(client.get(f"/lots/{lot['public_id']}/photos", headers=auth).json()) == 1
    assert [e["type"] for e in events(client, auth, "lots", lot["public_id"])] == ["ingreso_lote", "foto"]
    assert client.get(f"/lots/{lot['public_id']}/verify", headers=auth).json()["ok"] is True


def test_format_is_detected_from_bytes_not_from_the_declared_type(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    r = upload(client, auth, "assets", pc["public_id"], data=WEBP, ctype="application/octet-stream", photo_id="webpwebpwebp2")
    assert r.status_code == 201
    assert r.json()["content_type"] == "image/webp"
    assert client.get("/photos/webpwebpwebp2", headers=auth).headers["content-type"] == "image/webp"


def test_upload_is_idempotent_and_ids_cannot_cross_subjects(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    other = make_asset(client, auth, lot, label="Otra PC")

    a = upload(client, auth, "assets", pc["public_id"], photo_id="repetidarepeti2")
    b = upload(client, auth, "assets", pc["public_id"], photo_id="repetidarepeti2")
    assert a.status_code == 201 and b.status_code == 201
    assert a.json() == b.json()
    assert [e["type"] for e in events(client, auth, "assets", pc["public_id"])].count("foto") == 1
    assert len(client.get(f"/assets/{pc['public_id']}/photos", headers=auth).json()) == 1

    # Mismo photo_id sobre otro equipo: conflicto, no se reasigna.
    c = upload(client, auth, "assets", other["public_id"], photo_id="repetidarepeti2")
    assert c.status_code == 409


def test_rejects_bad_uploads(client, auth, monkeypatch):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    pid = pc["public_id"]

    # No es una imagen, aunque lo declare
    r = upload(client, auth, "assets", pid, data=b"esto es texto, no una imagen", ctype="image/jpeg")
    assert r.status_code == 422
    # Vacío
    assert upload(client, auth, "assets", pid, data=b"").status_code == 422
    # photo_id inválido
    assert upload(client, auth, "assets", pid, photo_id="NO-VALIDO").status_code == 422
    # Equipo inexistente
    assert upload(client, auth, "assets", "noexistenoexiste2").status_code == 404
    # Demasiado grande
    monkeypatch.setattr(config, "MAX_PHOTO_BYTES", 100)
    assert upload(client, auth, "assets", pid, data=JPEG).status_code == 413

    # Nada de lo rechazado dejó rastro
    assert client.get(f"/assets/{pid}/photos", headers=auth).json() == []
    assert [e["type"] for e in events(client, auth, "assets", pid)] == ["ingreso"]


def test_photo_limit_per_subject(client, auth, monkeypatch):
    monkeypatch.setattr(config, "MAX_PHOTOS_PER_SUBJECT", 2)
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    pid = pc["public_id"]

    assert upload(client, auth, "assets", pid, photo_id="limiteuno22").status_code == 201
    assert upload(client, auth, "assets", pid, photo_id="limitedos22").status_code == 201
    assert upload(client, auth, "assets", pid, photo_id="limitetres2").status_code == 409

    # Al eliminar una, hay lugar de nuevo.
    assert client.delete("/photos/limiteuno22", headers=auth).status_code == 204
    assert upload(client, auth, "assets", pid, photo_id="limitetres2").status_code == 201


def test_delete_removes_the_image_but_keeps_the_audit_trail(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    pid = pc["public_id"]
    created = upload(client, auth, "assets", pid, photo_id="borrarborrar22").json()
    assert list(Path(config.PHOTOS_DIR).rglob("borrarborrar22*")), "la foto debería estar en disco"

    assert client.delete("/photos/borrarborrar22", headers=auth).status_code == 204

    assert client.get("/photos/borrarborrar22", headers=auth).status_code == 410
    assert client.get(f"/assets/{pid}/photos", headers=auth).json() == []
    assert not list(Path(config.PHOTOS_DIR).rglob("borrarborrar22*")), "el archivo debería haberse borrado"

    evs = events(client, auth, "assets", pid)
    assert [e["type"] for e in evs] == ["ingreso", "foto", "foto_eliminada"]
    assert evs[2]["payload"] == {"photo": "borrarborrar22", "sha256": created["sha256"]}
    assert client.get(f"/assets/{pid}/verify", headers=auth).json()["ok"] is True

    # Borrar de nuevo no falla ni duplica eventos.
    assert client.delete("/photos/borrarborrar22", headers=auth).status_code == 204
    assert [e["type"] for e in events(client, auth, "assets", pid)].count("foto_eliminada") == 1
    assert client.delete("/photos/inexistenteinex2", headers=auth).status_code == 404


def test_photos_work_on_assets_in_a_final_state(client, auth):
    """Un equipo ya vendido o en scrap puede seguir documentándose con fotos."""
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    post_event(client, auth, pc, "prueba", {"result": "falla"})
    assert post_event(client, auth, pc, "scrap").status_code == 201
    assert upload(client, auth, "assets", pc["public_id"]).status_code == 201


def test_photos_require_a_station_key(client, auth):
    lot = make_lot(client, auth)
    pc = make_asset(client, auth, lot)
    upload(client, auth, "assets", pc["public_id"], photo_id="privadaprivada2")
    pid = pc["public_id"]

    assert client.post(f"/assets/{pid}/photos", content=JPEG).status_code == 401
    assert client.get(f"/assets/{pid}/photos").status_code == 401
    assert client.get("/photos/privadaprivada2").status_code == 401
    assert client.delete("/photos/privadaprivada2").status_code == 401
    bad = {"X-Station-Key": "tr_falsa"}
    assert client.get("/photos/privadaprivada2", headers=bad).status_code == 401


def test_public_view_never_reveals_photos(client, auth):
    lot = make_lot(client, auth, generator_public=True, generator_name="Empresa Visible")
    pc = make_asset(client, auth, lot)
    pid = pc["public_id"]
    upload(client, auth, "assets", pid, photo_id="nopublicanopub2", caption="Serie SN-SECRETO-1")
    upload(client, auth, "lots", lot["public_id"], photo_id="nopublicalote2")
    client.delete("/photos/nopublicanopub2", headers=auth)

    for path in (f"/public/a/{pid}", f"/public/l/{lot['public_id']}"):
        r = client.get(path)
        assert r.status_code == 200
        low = r.text.lower()
        assert "foto" not in low and "nopublica" not in low and "sn-secreto" not in low, r.text
    timeline = client.get(f"/public/a/{pid}").json()["timeline"]
    assert [t["type"] for t in timeline] == ["ingreso"]
