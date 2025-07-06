import socket
import ssl
from typing import List, Optional

from .base_connector import BaseConnector


class IRCConnector(BaseConnector):

    name = "IRC"
    id = "irc"

    def __init__(
        self,
        server: str,
        port: int = 6667,
        nickname: str = "norman",
        username: Optional[str] = None,
        realname: Optional[str] = None,
        password: Optional[str] = None,
        channels: Optional[List[str]] = None,
        use_ssl: bool = False,
        config: Optional[dict] = None,
    ):
        super().__init__(config)
        self.server = server
        self.port = port
        self.nickname = nickname
        self.username = username or nickname
        self.realname = realname or nickname
        self.password = password
        self.channels = channels or []
        self.use_ssl = use_ssl
        self.socket: Optional[socket.socket] = None

    def connect(self):
        self.socket = socket.create_connection((self.server, self.port))
        if self.use_ssl:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.socket = context.wrap_socket(self.socket, server_hostname=self.server)
        if self.password:
            self.socket.sendall(f"PASS {self.password}\r\n".encode("utf-8"))
        self.socket.sendall(f"NICK {self.nickname}\r\n".encode("utf-8"))
        self.socket.sendall(
            f"USER {self.username} 0 * :{self.realname}\r\n".encode("utf-8")
        )
        for channel in self.channels:
            self.socket.sendall(f"JOIN {channel}\r\n".encode("utf-8"))

    def disconnect(self):
        if self.socket:
            try:
                self.socket.sendall(b"QUIT\r\n")
            finally:
                self.socket.close()
                self.socket = None

    def send_message(self, message):
        if self.socket and self.channels:
            channel = self.channels[0]
            self.socket.sendall(f"PRIVMSG {channel} :{message}\r\n".encode("utf-8"))

    def receive_message(self):
        while True:
            data = self.socket.recv(1024).decode("utf-8")
            if data.startswith("PING"):
                self.socket.sendall(f"PONG {data.split()[1]}\r\n".encode("utf-8"))
            else:
                return data

    def is_connected(self):
        return self.socket is not None and self.socket.getpeername() is not None

    async def listen_and_process(self) -> None:
        """Listen for a single IRC message and process it."""
        if not self.socket:
            return None
        msg = self.receive_message()
        if msg:
            await self.process_incoming(msg)

    async def process_incoming(self, message):
        """Return the raw ``message`` payload."""
        return message
