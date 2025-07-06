# SMTP Connector

The SMTP connector allows Norman to send email notifications via a standard SMTP server.

## Requirements

- Access to an SMTP server
- Credentials for authentication if required

## Configuration

Add the following fields to your `config.yaml`:

```yaml
smtp_host: "smtp.example.com"
smtp_port: 587
smtp_username: "your_username"
smtp_password: "your_password"
smtp_from_address: "bot@example.com"
smtp_to_address: "destination@example.com"
```

## Usage

When enabled, Norman can send messages through the configured SMTP server. Incoming messages are not supported for this
connector.

## Troubleshooting

1. Verify the SMTP credentials and host information are correct.
2. Ensure the network allows outbound connections to the SMTP server.
