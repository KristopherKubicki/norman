# tests/test_webhook.py
import pytest

# Replace with your actual schema and endpoint imports
from app.schemas import (
    BotCreate,
    ChannelCreate,
    FilterCreate,
    IncomingWebhookMessage,
    OutgoingWebhookMessage,
)
from app.endpoints import (
    create_bot,
    create_channel,
    create_filter,
    process_incoming_webhook,
    send_outgoing_webhook,
)


def test_webhook_process(test_app):
    # Create a bot
    bot = BotCreate(name="TestBot")
    created_bot = create_bot(bot)

    # Create a channel
    channel = ChannelCreate(name="TestChannel", connector="webhook", bot_id=created_bot.id)
    created_channel = create_channel(channel)

    # Create a filter with regex pattern
    filter = FilterCreate(
        pattern=r"Hello, (.+)",
        bot_id=created_bot.id,
        channel_id=created_channel.id,
    )
    created_filter = create_filter(filter)

    # Process an incoming webhook message
    incoming_message = IncomingWebhookMessage(
        text="Hello, World!",
        channel_id=created_channel.id,
    )
    matched_filter, extracted_data = process_incoming_webhook(incoming_message)

    assert matched_filter == created_filter
    assert extracted_data == {"1": "World"}

    # Send an outgoing webhook message
    outgoing_message = OutgoingWebhookMessage(
        text=f"Hi {extracted_data['1']}! Your message was processed.",
        channel_id=created_channel.id,
    )
    sent_message = send_outgoing_webhook(outgoing_message)

    assert sent_message.text == "Hi World! Your message was processed."

