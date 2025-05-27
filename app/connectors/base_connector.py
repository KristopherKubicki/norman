import asyncio
from abc import ABC, abstractmethod


class BaseConnector(ABC):

    def __init__(self, config=None):
        """Initialize the connector with optional configuration.

        Args:
            config (dict | None): Optional configuration dictionary.  If not
                provided, an empty dict is used.
        """
        self.config = config or {}
    @abstractmethod
    async def send_message(self, message):
        """Send a message using the connector.

        Args:
            message (dict): A dictionary containing the message data.
        """
        pass

    @abstractmethod
    async def listen_and_process(self):
        """Listen for incoming messages and process them."""
        pass

    @abstractmethod
    async def process_incoming(self, message):
        """Process an incoming message.

        Args:
            message (dict): A dictionary containing the message data.
        """
        pass

    async def run(self):
        """Start the connector and keep it running."""
        await self.listen_and_process()

