# Google Pub/Sub Connector

The Google Pub/Sub connector publishes messages to a Pub/Sub topic.

## Requirements

- A Google Cloud project with Pub/Sub enabled
- A service account with publish permissions
- The `google-cloud-pubsub` package installed

## Configuration

```yaml
google_pubsub_project_id: "your_gcp_project"
google_pubsub_topic_id: "your_pubsub_topic"
```

## Usage

Norman sends each message as a Pub/Sub message to the configured topic.
