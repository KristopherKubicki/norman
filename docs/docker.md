# Docker Deployment

This guide explains how to run Norman inside Docker for a reproducible environment.

## Building the Image

1. Copy `config.yaml.dist` to `config.yaml` and adjust the settings for your installation.
2. Build the Docker image from the repository root:

   ```bash
   docker build -t norman .
   ```

## Running the Container

Run Norman with the generated image and mount your configuration and database directory:

```bash
docker run -v $(pwd)/config.yaml:/app/config.yaml \
           -v $(pwd)/db:/app/db \
           -p 8000:8000 norman
```

Visit `http://localhost:8000` to access the API.

## docker-compose Example

A sample `docker-compose.yml` is included for running Norman together with a PostgreSQL database.
Start both services with:

```bash
docker-compose up
```

The compose file sets the `DATABASE_URL` environment variable so Norman uses the
`db` service. Database data is stored in the `postgres-data` volume.
