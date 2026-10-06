import base64
import re
import secrets

# ID público opaco: es lo único que va en el QR. No contiene serial ni datos reales.
PUBLIC_ID_RE = re.compile(r"^[a-z2-7]{10,26}$")


def new_public_id() -> str:
    return base64.b32encode(secrets.token_bytes(8)).decode().lower().rstrip("=")


def valid_public_id(value: str) -> bool:
    return bool(PUBLIC_ID_RE.match(value))
