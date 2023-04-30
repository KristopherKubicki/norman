from fastapi import APIRouter, Body, Depends, Request
from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse
from starlette.responses import RedirectResponse

from app.models.interaction import Interaction
from app.models.channel_filter import Filter
from app.connectors import get_connector

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

