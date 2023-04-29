from fastapi import APIRouter, Request
from starlette.staticfiles import StaticFiles
import os

from .views import home, connectors, filters, channels

current_dir = os.path.dirname(os.path.realpath(__file__))
app_routes = APIRouter()

@app_routes.get("/")
async def home_page(request: Request):
    return await home(request)

@app_routes.get("/index.html")
async def index_page(request: Request):
    return await home(request)

@app_routes.get("/connectors.html")
async def connectors_page(request: Request):
    return await connectors(request)

@app_routes.get("/filters.html")
async def filters_page(request: Request):
    return await filters(request)

@app_routes.get("/channels.html")
async def channels_page(request: Request):
    return await channels(request)
