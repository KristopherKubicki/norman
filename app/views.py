from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")

async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

async def connectors(request: Request):
    return templates.TemplateResponse("connectors.html", {"request": request})

async def filters(request: Request):
    return templates.TemplateResponse("filters.html", {"request": request})

async def channels(request: Request):
    return templates.TemplateResponse("channels.html", {"request": request})
