# MCP Connector

The MCP connector integrates Norman with a Model Context Protocol (MCP) service. MCP servers expose tools to the Agents SDK so that LLMs can interact with external systems.  Norman can forward webhooks from an MCP server and access its tools.

## Requirements

- An MCP server available via HTTP or SSE
- An API key for authenticating requests

## Configuration

Add the following keys to your `config.yaml` file:

```yaml
mcp_api_url: "https://mcp.example.com/api"
mcp_api_key: "your_mcp_api_key"
```

The fields are:

- `mcp_api_url`: Base URL of your MCP server
- `mcp_api_key`: API key used for requests to the MCP server

## Usage

Once configured, Norman will initialize the MCP connector at startup. Incoming updates can be posted to `/api/v1/connectors/mcp/webhooks/mcp`. The connector can also be used programmatically to list and call tools from the MCP server.

## Troubleshooting

1. Ensure the MCP server URL and API key are correct.
2. Check that the server is reachable from the Norman instance.
3. Review application logs for any HTTP errors when communicating with the MCP service.
