import socket
from .base_connector import BaseConnector


class IRCConnector(BaseConnector):

    name = 'IRC'
    id = 'irc'

    def __init__(self, server: str, port: int = 6667, channel: str | None = None,
                 nickname: str = "bot", username: str | None = None,
                 realname: str | None = None, password: str | None = None,
                 config=None):
        """Create a new :class:`IRCConnector`.

        Parameters mirror common IRC connection settings so that the
        configuration system can provide them individually instead of as a
        single dictionary.
        """
        super().__init__(config)
        self.server = server
        self.port = port
        self.channel = channel
        self.nickname = nickname
        self.username = username or nickname
        self.realname = realname or nickname
        self.password = password
        self.socket = None

    def connect(self):
        """Establish the connection to the IRC server."""

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.server, self.port))
        if self.password:
            self.socket.send(f"PASS {self.password}\r\n".encode("utf-8"))
        self.socket.send(f"NICK {self.nickname}\r\n".encode("utf-8"))
        self.socket.send(
            f"USER {self.username} 0 * :{self.realname}\r\n".encode("utf-8")
        )
        if self.channel:
            self.socket.send(f"JOIN {self.channel}\r\n".encode("utf-8"))
        return True

    def disconnect(self):
        """Close the IRC connection."""
        if not self.socket:
            return
        self.socket.send(b"QUIT\r\n")
        self.socket.close()

    def send_message(self, channel: str | None, message):
        """Send ``message`` to ``channel`` or the default channel."""
        target = channel or self.channel
        if not target:
            raise ValueError("Channel must be specified")
        self.socket.send(f"PRIVMSG {target} :{message}\r\n".encode("utf-8"))

    def receive_message(self):
        """Block until a message is received, responding to pings."""
        while True:
            data = self.socket.recv(1024).decode("utf-8")
            if data.startswith("PING"):
                self.socket.send(f"PONG {data.split()[1]}\r\n".encode("utf-8"))
            else:
                return data

    def is_connected(self):
        """Return ``True`` if a socket connection has been established."""
        return self.socket is not None and self.socket.getpeername() is not None
