from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.connectors.connector_utils import get_connector, get_connectors_data

from app.core.logging import setup_logger
logger = setup_logger(__name__)



templates = Jinja2Templates(directory="app/templates")

async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

async def connectors(request: Request):
    connectors_data = get_connectors_data()
    return templates.TemplateResponse("connectors.html", {"request": request, "connectors": connectors_data})

async def filters(request: Request):
    return templates.TemplateResponse("filters.html", {"request": request})

async def channels(request: Request):
    return templates.TemplateResponse("channels.html", {"request": request})

async def messages(request: Request):
    return templates.TemplateResponse("messages_log.html", {"request": request})

async def bots(request: Request):
    return templates.TemplateResponse("bots.html", {"request": request})


async def process_message(request: Request):
    data = await request.json()
    message = data.get('message')
    channel_id = data.get('connector')

    # Use the get_connector function to get the appropriate connector for the given channel_id.
    connector = get_connector(channel_id)

    # Use the connector to process the message.
    response = await connector.process_message(message)

    # Return the response to the frontend, which can be used to update the messages log.
    return templates.TemplateResponse("process_message.html", {"request": request, "response": response})
