import os
import hashlib
import base64
from cryptography.fernet import Fernet, InvalidToken


def _get_cipher() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY no está definida en las variables de entorno.")
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    if not value:
        return value
    cipher = _get_cipher()
    return cipher.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """
    Desencripta un valor. Si el valor no está encriptado (texto plano),
    lo devuelve tal cual sin explotar.
    """
    if not value:
        return value
    # Si no empieza con gAAAAA, no es un token Fernet → ya es texto plano
    if not str(value).startswith("gAAAAA"):
        return value
    try:
        cipher = _get_cipher()
        return cipher.decrypt(value.encode()).decode()
    except InvalidToken:
        # Por seguridad, si falla la desencriptación devolvemos el valor original
        return value


def hash_for_search(value: str) -> str:
    key = os.getenv("ENCRYPTION_KEY", "")
    return hashlib.sha256(f"{key}:{value.strip()}".encode()).hexdigest()