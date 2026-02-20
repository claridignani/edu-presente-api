from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.dependencies import SessionDep
from app.core.security import decode_token
from app.models.usuario import Usuario

bearer = HTTPBearer(auto_error=False)

def get_current_user(
    session: SessionDep,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> Usuario:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="No autenticado")

    try:
        payload = decode_token(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token inválido")

    user = session.get(Usuario, int(sub))
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")

    return user
