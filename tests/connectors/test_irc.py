from app.connectors import irc

def test_irc_connection():
    # Replace with your actual test IRC server and credentials
    irc_server = "irc.example.com"
    irc_port = 6667
    irc_channel = "#test"
    irc_nickname = "test_bot"
    irc_password = "your_password"

    connector = irc.IRCConnector(server=irc_server, port=irc_port, channel=irc_channel,
                                  nickname=irc_nickname, password=irc_password)
    assert connector.connect() is True
