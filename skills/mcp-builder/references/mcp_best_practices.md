# MCP Server Best Practices

## Tool Design

### Naming Conventions
- Use snake_case for tool names: `get_weather`, `send_email`
- Use action verbs: `create_`, `get_`, `update_`, `delete_`, `list_`
- Be specific: `search_github_repos` not just `search`

### Descriptions
- Lead with what the tool does: "Fetches current weather..."
- Include when to use it: "Use when the user asks about..."
- Mention limitations: "Only supports US zip codes"

### Input Schemas
- Always define `type: "object"` at root
- Use descriptive property names
- Include `description` for every property
- Specify `required` array for mandatory fields
- Use appropriate types (`string`, `number`, `boolean`, `array`, `object`)
- Add `enum` for constrained values

### Example Schema
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query string"
    },
    "limit": {
      "type": "number",
      "description": "Maximum results to return (1-100)",
      "default": 10
    },
    "sort": {
      "type": "string",
      "description": "Sort order for results",
      "enum": ["relevance", "date", "popularity"]
    }
  },
  "required": ["query"]
}
```

## Error Handling

### Return Clear Errors
```python
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "my_tool":
        if "required_param" not in arguments:
            return [TextContent(
                type="text",
                text="Error: 'required_param' is required"
            )]

        try:
            result = await do_work(arguments)
            return [TextContent(type="text", text=result)]
        except ValueError as e:
            return [TextContent(type="text", text=f"Invalid input: {e}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Operation failed: {e}")]
```

### Validation
- Validate all inputs before processing
- Check types, ranges, and formats
- Return helpful error messages

## Resource Design

### URI Patterns
- Use hierarchical URIs: `resource://server/type/id`
- Be consistent across resources
- Document URI structure

### MIME Types
- Use standard MIME types
- `text/plain` for plain text
- `application/json` for structured data
- `text/markdown` for formatted text

## Security

### Input Sanitization
```python
def sanitize_path(path: str, allowed_dir: Path) -> Path:
    """Ensure path is within allowed directory."""
    resolved = Path(path).resolve()
    if not str(resolved).startswith(str(allowed_dir.resolve())):
        raise ValueError("Path outside allowed directory")
    return resolved
```

### Secrets Management
- Never hardcode secrets
- Use environment variables
- Document required environment variables

### Rate Limiting
```python
from collections import defaultdict
from time import time

class RateLimiter:
    def __init__(self, max_calls: int, period: float):
        self.max_calls = max_calls
        self.period = period
        self.calls = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time()
        self.calls[key] = [t for t in self.calls[key] if now - t < self.period]
        if len(self.calls[key]) >= self.max_calls:
            return False
        self.calls[key].append(now)
        return True
```

## Performance

### Async Operations
- Use `async`/`await` for I/O operations
- Don't block the event loop
- Use connection pooling for HTTP clients

### Caching
```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=100)
def cached_lookup(key: str) -> str:
    # Expensive operation
    return result

# Time-based cache
class TimedCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = timedelta(seconds=ttl_seconds)
        self.cache = {}

    def get(self, key: str):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return value
        return None

    def set(self, key: str, value):
        self.cache[key] = (value, datetime.now())
```

## Testing

### Unit Tests
```python
import pytest
from your_server import call_tool

@pytest.mark.asyncio
async def test_tool_success():
    result = await call_tool("my_tool", {"param": "value"})
    assert result[0].text == "expected output"

@pytest.mark.asyncio
async def test_tool_invalid_input():
    result = await call_tool("my_tool", {})
    assert "Error" in result[0].text

@pytest.mark.asyncio
async def test_unknown_tool():
    with pytest.raises(ValueError):
        await call_tool("nonexistent", {})
```

### Integration Tests
- Test with actual MCP client
- Verify end-to-end workflows
- Test error scenarios

## Documentation

### README Structure
1. Overview - What the server does
2. Installation - How to install
3. Configuration - Environment variables, settings
4. Tools - List of available tools with examples
5. Resources - List of available resources
6. Examples - Common usage patterns
7. Troubleshooting - Common issues and solutions

### Tool Documentation
```markdown
## `tool_name`

Description of what this tool does.

### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| param1 | string | Yes | What this parameter does |
| param2 | number | No | Optional parameter (default: 10) |

### Example

```json
{
  "name": "tool_name",
  "arguments": {
    "param1": "example value"
  }
}
```

### Response

Description of the response format.
```
