"""Connector for Outlook mail via IMAP (basic auth)."""

from typing import Optional

from .imap_connector import IMAPConnector


class OutlookConnector(IMAPConnector):
    id = "outlook"
    name = "Outlook Mail"

    def __init__(
        self,
        username: str,
        password: str,
        mailbox: str = "INBOX",
        host: str = "imap-mail.outlook.com",
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
