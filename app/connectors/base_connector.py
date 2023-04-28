from abc import ABC, abstractmethod


class BaseConnector(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def send_message(self, channel, message):
        pass

    @abstractmethod
    def receive_message(self):
        pass

    @abstractmethod
    def is_connected(self):
        pass
