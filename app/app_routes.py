from typing import List
from fastapi import APIRouter, Body, Depends, Request, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import RedirectResponse

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse, HTMLResponse, Response, JSONResponse
from starlette.responses import RedirectResponse

from sqlalchemy.orm import Session

from app.schemas import Token
from app.schemas.user import UserAuthenticate
from app.schemas.bot import Bot, BotCreate, BotOut
from app.schemas.message import Message
from app.core.config import settings
from app.core.security import create_access_token
from app.crud.user import authenticate_user
from app.crud.bot import create_bot, delete_bot
from app.crud.message import create_message, get_messages_by_bot_id, delete_message
from app.models.interaction import Interaction
from app.models.channel_filter import Filter
from app.connectors import get_connector
from app.api.deps import get_async_db

from datetime import timedelta
import os

from .views import home, connectors, filters, channels, process_message, bots, messages, login, logout, get_bots

current_dir = os.path.dirname(os.path.realpath(__file__))
app_routes = APIRouter()

def clear_access_token_cookie(response: Response):
    response.delete_cookie("access_token")
    return response

@app_routes.get("/favicon.ico")
async def favicon():
    return FileResponse(os.path.join(current_dir, "static/favicon.ico"))

@app_routes.get("/")
async def home_endpoint(request: Request):
    return await home(request)

@app_routes.get("/index.html")
async def index_endpoint(request: Request):
    return await home(request)

@app_routes.get("/connectors.html")
async def connectors_endpoint(request: Request):
    return await connectors(request)

@app_routes.get("/filters.html")
async def filters_endpoint(request: Request):
    return await filters(request)

@app_routes.get("/channels.html")
async def channels_endpoint(request: Request):
    return await channels(request)

@app_routes.get("/bots.html")
async def bots_endpoint(request: Request):
    return await bots(request)

@app_routes.get("/messages_log.html")
async def messages_endpoint(request: Request):
    return await messages(request)

@app_routes.post("/api/bots/create")
async def create_bot_endpoint(request: Request, db: Session = Depends(get_async_db)):
    form_data = await request.json()
    bot = BotCreate
    bot.name = form_data["name"]
    bot.description = form_data["description"]
    # Add logic to create bot in the database
    bot = create_bot(db=db, bot_create=bot)
    return JSONResponse(content={"id": bot.id, "name": bot.name, "description": bot.description})

@app_routes.get("/api/bots", response_model=List[BotOut])
async def get_bots_endpoint(request: Request, db: Session = Depends(get_async_db)):
    try:
        bots = await get_bots(db)
        bot_outs = [BotOut.from_orm(bot) for bot in bots]  # Convert the list of Bot objects to a list of BotOut instances
        bot_dicts = [bot_out.dict() for bot_out in bot_outs]  # Convert the list of BotOut instances to a list of dictionaries
        return JSONResponse(content=bot_dicts)  # Return the list of dictionaries as a JSONResponse
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="An error occurred while fetching bots")

@app_routes.delete("/api/bots/{bot_id}")
async def delete_bot_endpoint(bot_id: int, db: Session = Depends(get_async_db)):
    success = delete_bot(db=db, bot_id=bot_id)
    if success:
        return {"status": "success", "message": "Bot deleted successfully"}
    else:
        return {"status": "error", "message": "Failed to delete bot"}

@app_routes.post("/api/bots/{bot_id}/messages")
async def create_message_endpoint(bot_id: int, request: Request, db: Session = Depends(get_async_db)):
    try:
        ljson = await request.json()
        message = create_message(db=db, bot_id=bot_id, text=ljson.get('content'))
        return {"status": "success", "message": "Message created successfully", "data": message}
    except Exception as e:
        print("Error:", e)
        return {"status": "error", "message": "Failed to create message"}


@app_routes.get("/api/bots/{bot_id}/messages", response_model=List[Message])
async def get_messages_endpoint(bot_id: int, db: Session = Depends(get_async_db)):
    # TODO: support pagination
    try:
        messages = get_messages_by_bot_id(db=db, bot_id=bot_id)
        return [Message.from_orm(message).dict() for message in messages]
    except Exception as e:
        print("Error:", e)
        raise HTTPException(status_code=500, detail="Failed to fetch messages")


'''
@app_routes.delete("/api/messages/{message_id}")
async def delete_message_endpoint(message_id: int, db: Session = Depends(get_async_db)):
    try:
        success = await delete_message(db=db, message_id=message_id)
        if success:
            return {"status": "success", "message": "Message deleted successfully"}
        else:
            return {"status": "error", "message": "Failed to delete message"}
    except Exception as e:
        print("Error:", e)
        return {"status": "error", "message": "Failed to delete message"}
'''



'''
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
async def token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_async_db)):
    user_auth = UserAuthenticate(email=form_data.username, password=form_data.password)
    user = await authenticate_user(db, user_auth)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app_routes.get("/login.html")
async def login_endpoint(request: Request):
    return await login(request)

@app_routes.get("/logout", response_class=HTMLResponse)
async def logout_endpoint(request: Request, response: Response = Depends(clear_access_token_cookie)):
    return await logout(request)

#@app_routes.post("/login", response_class=HTMLResponse)
#async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
#    user = await authenticate_user(form_data.username, form_data.password)

@app_routes.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_async_db)):

    user = UserAuthenticate(email=form_data.username, password=form_data.password)

    if user is None:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
    )
    return response

