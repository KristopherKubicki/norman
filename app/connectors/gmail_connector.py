"""Connector for Gmail via IMAP (basic auth)."""

from typing import Optional

from .imap_connector import IMAPConnector


class GmailConnector(IMAPConnector):
    id = "gmail"
    name = "Gmail"

    def __init__(
        self,
        username: str,
        password: str,
        mailbox: str = "INBOX",
        host: str = "imap.gmail.com",
        port: int = 993,
        use_ssl: bool = True,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            mailbox=mailbox,
            use_ssl=use_ssl,
            config=config,
        )
