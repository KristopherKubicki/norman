# SMTP Email Connector

The SMTP connector allows Norman to send messages using a standard SMTP server. It can be configured with any SMTP provider, including Gmail.

## Configuration

Add the following settings to your `config.yaml`:

```yaml
smtp_host: "smtp.gmail.com"
smtp_port: 587
smtp_username: "your_username"
smtp_password: "your_password"
smtp_from_addr: "bot@example.com"
smtp_to_addr: "destination@example.com"
```

Replace the values with your SMTP server details. Incoming email is not currently processed by this connector; only sending messages is supported.
