# Google Pub/Sub Connector

The Google Pub/Sub connector publishes messages to a Pub/Sub topic.

## Requirements

- A Google Cloud project with Pub/Sub enabled
- The `google-cloud-pubsub` Python package installed

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
google_pubsub_project_id: "your-project"
google_pubsub_topic_id: "norman"
google_pubsub_credentials_path: "/path/to/credentials.json"  # optional
```

## Usage

Currently this connector only publishes messages to the specified topic.
