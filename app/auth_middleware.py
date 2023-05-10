from fastapi import Request, HTTPException
from fastapi.responses import Response, RedirectResponse
from app.api.deps import get_current_user
from fastapi.security import OAuth2PasswordBearer
from starlette.datastructures import MutableHeaders

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

async def auth_middleware(request: Request, call_next):
    token = request.cookies.get("access_token", None)

    if token is None:
        if request.url.path.endswith(".html") and request.url.path != "/login.html":
            return RedirectResponse(url="/login.html", status_code=303)
    elif request.url.path == "/login.html":
        pass
    elif request.url.path not in ("/favicon.ico", "/login"):
        try:
            # Set the token in the Authorization header
            headers = MutableHeaders(scope=request.scope)
            headers["Authorization"] = f"Bearer {token}"
            request.scope['headers'] = headers.items()
            token = await oauth2_scheme(request)
            current_user = await get_current_user(token)
        except HTTPException as e:
            if e.status_code == 401:
                #return Response(content="Unauthorized", status_code=401)
                return RedirectResponse(url="/login.html", content="Unauthorized", status_code=401)
            raise e

    response = await call_next(request)
    return response

