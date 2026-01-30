---
name: mcp-builder
description: Guide for creating high-quality Model Context Protocol (MCP) servers. Use this skill when the user wants to build an MCP server to extend Claude's capabilities.
---

# MCP Server Builder

You are an expert at building Model Context Protocol (MCP) servers that extend Claude's capabilities. MCP servers provide tools, resources, and prompts that Claude can use to interact with external systems.

## MCP Overview

The Model Context Protocol enables:
- **Tools**: Functions Claude can call to perform actions
- **Resources**: Data sources Claude can read from
- **Prompts**: Pre-defined conversation templates

## Server Architecture

### Python MCP Server Template

```python
#!/usr/bin/env python3
"""
MCP Server: [Server Name]
Description: [What this server does]
"""

import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource

# Initialize server
server = Server("your-server-name")

# Define tools
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="tool_name",
            description="What this tool does",
            inputSchema={
                "type": "object",
                "properties": {
                    "param1": {
                        "type": "string",
                        "description": "Parameter description"
                    }
                },
                "required": ["param1"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "tool_name":
        param1 = arguments.get("param1")
        # Tool implementation
        result = f"Processed: {param1}"
        return [TextContent(type="text", text=result)]

    raise ValueError(f"Unknown tool: {name}")

# Define resources (optional)
@server.list_resources()
async def list_resources():
    return [
        Resource(
            uri="resource://your-server/resource-name",
            name="Resource Name",
            description="What this resource provides",
            mimeType="text/plain"
        )
    ]

@server.read_resource()
async def read_resource(uri: str):
    if uri == "resource://your-server/resource-name":
        # Return resource content
        return "Resource content here"

    raise ValueError(f"Unknown resource: {uri}")

# Main entry point
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)

if __name__ == "__main__":
    asyncio.run(main())
```

### Node.js MCP Server Template

```typescript
#!/usr/bin/env node
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  { name: "your-server-name", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// List available tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "tool_name",
      description: "What this tool does",
      inputSchema: {
        type: "object",
        properties: {
          param1: {
            type: "string",
            description: "Parameter description",
          },
        },
        required: ["param1"],
      },
    },
  ],
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "tool_name") {
    const param1 = args?.param1 as string;
    // Tool implementation
    return {
      content: [{ type: "text", text: `Processed: ${param1}` }],
    };
  }

  throw new Error(`Unknown tool: ${name}`);
});

// Start server
const transport = new StdioServerTransport();
server.connect(transport);
```

## Best Practices

### Tool Design
1. **Clear naming**: Use descriptive, action-oriented names (`get_weather`, `send_email`)
2. **Detailed descriptions**: Explain what the tool does and when to use it
3. **Comprehensive schemas**: Define all parameters with types and descriptions
4. **Error handling**: Return clear error messages for invalid inputs

### Resource Design
1. **Meaningful URIs**: Use hierarchical, descriptive URI paths
2. **Appropriate MIME types**: Match content type to data format
3. **Efficient retrieval**: Cache when appropriate, paginate large resources

### Security
1. **Input validation**: Never trust input data
2. **Least privilege**: Request only necessary permissions
3. **Secrets management**: Use environment variables, never hardcode
4. **Rate limiting**: Protect against abuse

## Configuration

### Claude Desktop (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "your-server": {
      "command": "python",
      "args": ["/path/to/your_server.py"],
      "env": {
        "API_KEY": "your-api-key"
      }
    }
  }
}
```

### Claude Code (.mcp.json)

```json
{
  "mcpServers": {
    "your-server": {
      "command": "python",
      "args": ["your_server.py"],
      "cwd": "/path/to/server"
    }
  }
}
```

## Testing

### Manual Testing
```bash
# Test with MCP Inspector
npx @anthropic/mcp-inspector your_server.py

# Test stdio directly
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python your_server.py
```

### Automated Testing
```python
import pytest
from your_server import call_tool

@pytest.mark.asyncio
async def test_tool_execution():
    result = await call_tool("tool_name", {"param1": "test"})
    assert result[0].text == "Processed: test"
```

## Common Patterns

### API Integration
```python
import httpx

async def fetch_data(endpoint: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(endpoint)
        response.raise_for_status()
        return response.json()
```

### Database Access
```python
import sqlite3

def query_database(sql: str, params: tuple = ()) -> list:
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(sql, params)
    results = cursor.fetchall()
    conn.close()
    return results
```

### File Operations
```python
from pathlib import Path

def read_file_safely(filepath: str) -> str:
    path = Path(filepath).resolve()
    # Validate path is within allowed directory
    allowed_dir = Path("/allowed/directory").resolve()
    if not str(path).startswith(str(allowed_dir)):
        raise ValueError("Access denied")
    return path.read_text()
```

## Deployment

### Package for Distribution
```
your-mcp-server/
├── pyproject.toml
├── README.md
├── src/
│   └── your_server/
│       ├── __init__.py
│       └── server.py
└── tests/
    └── test_server.py
```

### pyproject.toml
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "your-mcp-server"
version = "1.0.0"
dependencies = ["mcp>=0.9.0"]

[project.scripts]
your-mcp-server = "your_server.server:main"
```
