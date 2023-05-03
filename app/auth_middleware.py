from fastapi import Request, HTTPException
from fastapi.responses import Response
from app.api.deps import get_current_user
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

async def auth_middleware(request: Request, call_next):
    if request.url.path != "/login":
        try:
            token = await oauth2_scheme(request)
            current_user = await get_current_user(token)
        except HTTPException as e:
            if e.status_code == 401:
                return Response(content="Unauthorized", status_code=401)
            raise e

    response = await call_next(request)
    return response

