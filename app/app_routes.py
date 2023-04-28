import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app_routes = APIRouter()

current_dir = os.path.dirname(os.path.realpath(__file__))

# Serve static files (CSS, JavaScript, images, etc.)
app_routes.mount("/static", StaticFiles(directory=os.path.join(current_dir, "static")), name="static")

# Jinja2 templates instance
templates = Jinja2Templates(directory=os.path.join(current_dir, "templates"))

# Root endpoint to render the index.html template
@app_routes.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


