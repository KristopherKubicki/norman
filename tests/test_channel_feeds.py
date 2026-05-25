from app.services.channel_feeds import _parse_feed_xml, _validate_http_url


def test_validate_http_url_accepts_http_and_https():
    assert _validate_http_url("http://example.com") == "http://example.com"
    assert _validate_http_url("https://example.com") == "https://example.com"


def test_validate_http_url_rejects_other_schemes():
    try:
        _validate_http_url("file:///etc/passwd")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_feed_xml_rss_extracts_latest_item():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Example RSS</title>
        <item>
          <title>Item A</title>
          <link>https://example.com/a</link>
          <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    parsed = _parse_feed_xml(rss)
    assert parsed
    assert parsed["format"] == "rss"
    assert parsed["title"] == "Item A"
    assert parsed["link"] == "https://example.com/a"


def test_parse_feed_xml_atom_extracts_latest_entry():
    atom = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Example Atom</title>
      <entry>
        <title>Entry A</title>
        <link href="https://example.com/entry-a" />
        <updated>2024-01-01T00:00:00Z</updated>
      </entry>
    </feed>
    """
    parsed = _parse_feed_xml(atom)
    assert parsed
    assert parsed["format"] == "atom"
    assert parsed["title"] == "Entry A"
    assert parsed["link"] == "https://example.com/entry-a"
