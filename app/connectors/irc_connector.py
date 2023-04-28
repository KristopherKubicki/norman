import socket
from .base_connector import BaseConnector


class IRCConnector(BaseConnector):
    def __init__(self, config):
        super().__init__(config)
        self.socket = None

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.config["server"], self.config["port"]))
        self.socket.send(f"NICK {self.config['nickname']}\r\n".encode("utf-8"))
        self.socket.send(f"USER {self.config['username']} 0 * :{self.config['realname']}\r\n".encode("utf-8"))

    def disconnect(self):
        self.socket.send(b"QUIT\r\n")
        self.socket.close()

    def send_message(self, channel, message):
        self.socket.send(f"PRIVMSG {channel} :{message}\r\n".encode("utf-8"))

    def receive_message(self):
        while True:
            data = self.socket.recv(1024).decode("utf-8")
            if data.startswith("PING"):
                self.socket.send(f"PONG {data.split()[1]}\r\n".encode("utf-8"))
            else:
                return data

    def is_connected(self):
        return self.socket is not None and self.socket.getpeername() is not None
