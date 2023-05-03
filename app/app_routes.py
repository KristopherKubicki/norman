from fastapi import APIRouter, Body, Depends, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse
from fastapi import Depends

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse
from starlette.responses import RedirectResponse

from app.schemas import Token
from app.crud.user import authenticate_user
from app.models.interaction import Interaction
from app.models.channel_filter import Filter
from app.connectors import get_connector

from datetime import timedelta
import os

from .views import home, connectors, filters, channels, process_message, bots, messages

current_dir = os.path.dirname(os.path.realpath(__file__))
app_routes = APIRouter()


@app_routes.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(current_dir, "static/favicon.ico"))

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

@app_routes.get("/bots.html")
async def bots_page(request: Request):
    return await bots(request)

@app_routes.get("/messages_log.html")
async def messages_page(request: Request):
    return await messages(request)

'''
@app_routes.post("/bots/create")
async def create_bot(request: Request):
    if request.method == "POST":
        form_data = await request.form()
        name = form_data["name"]
        description = form_data["description"]
        # Add logic to create bot in the database
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("add_bot.html", {"request": request})


@app_routes.post("/channels/create")
async def create_channel(request: Request):
    if request.method == "POST":
        form_data = await request.form()
        name = form_data["name"]
        connector = form_data["connector"]
        details = form_data["details"]
        # Add logic to create channel in the database
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("add_channel.html", {"request": request})


@app_routes.post("/filters/create")
async def create_filter(request: Request):
    if request.method == "POST":
        form_data = await request.form()
        regex = form_data["regex"]
        # Add logic to create filter in the database
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("add_filter.html", {"request": request})


@app_routes.post("/api/process_message")
async def process_message_endpoint(request: Request):
    return await process_message(request)
'''


# TODO: this doesn't seem like it goes here.  
@app_routes.post("/webhook")
async def process_webhook(request: Request, payload: dict = Body(...)):
    # Process the payload received from the webhook
    # Assuming the payload has a 'channel' key with the channel identifier
    channel_id = payload["channel"]
    # Fetch the filters for the given channel from the database
    filters = await ChannelFilter.get_filters_for_channel(channel_id)

    # Loop through the filters and check if any of them match the payload
    for lfilter in filters:
        match = lfilter.matches(payload)
        if match:
            # Create an interaction entry in the database
            interaction = Interaction(channel_id=channel_id, filter_id=lfilter.id, payload=payload)
            await interaction.save()

            # If the filter has a reply, send the reply to the specified channel
            if lfilter.reply:
                connector = get_connector(lfilter.reply_channel.connector)
                await connector.send_message(lfilter.reply_channel, filter.reply)

@app_routes.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}




@app_routes.post("/login", response_class=HTMLResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response
