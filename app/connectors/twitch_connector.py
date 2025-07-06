from __future__ import annotations

import asyncio
import socket
from typing import Optional

from .base_connector import BaseConnector


class TwitchConnector(BaseConnector):
    """Connector for interacting with Twitch chat via IRC."""

    id = "twitch"
    name = "Twitch"

    def __init__(
        self,
        token: str,
        nickname: str,
        channel: str,
        server: str = "irc.chat.twitch.tv",
        port: int = 6667,
        config: Optional[dict] = None,
    ):
        super().__init__(config)
        self.token = token
        self.nickname = nickname
        self.channel = channel
        self.server = server
        self.port = port
        self.socket: Optional[socket.socket] = None

    def connect(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.server, self.port))
        # Twitch requires the token to be prefixed with "oauth:"
        self.socket.sendall(f"PASS {self.token}\r\n".encode("utf-8"))
        self.socket.sendall(f"NICK {self.nickname}\r\n".encode("utf-8"))
        self.socket.sendall(f"JOIN #{self.channel}\r\n".encode("utf-8"))

    def disconnect(self) -> None:
        if self.socket:
            try:
                self.socket.sendall(b"QUIT\r\n")
            finally:
                self.socket.close()
                self.socket = None

    def send_message(self, message: str) -> None:
        if not self.socket:
            raise RuntimeError("TwitchConnector is not connected")
        self.socket.sendall(f"PRIVMSG #{self.channel} :{message}\r\n".encode("utf-8"))

    def receive_message(self) -> str:
        if not self.socket:
            raise RuntimeError("TwitchConnector is not connected")
        data = self.socket.recv(2048).decode("utf-8")
        if data.startswith("PING"):
            self.socket.sendall(f"PONG {data.split()[1]}\r\n".encode("utf-8"))
            return ""
        return data

    async def listen_and_process(self):
        if not self.socket:
            self.connect()
        messages = []
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self.receive_message)
        if data:
            processed = self.process_incoming({"raw": data})
            if asyncio.iscoroutine(processed):
                processed = await processed
            if processed:
                messages.append(processed)
        return messages

    def process_incoming(self, message: dict) -> dict:
        return message

    def is_connected(self) -> bool:
        return self.socket is not None
