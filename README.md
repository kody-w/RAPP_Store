# RAPP Store

**Universal Store for RAPP Agents and Claude Skills**

A cross-compatible marketplace for AI agents and skills that works with both the RAPP (Rapid AI Agent Production Pipeline) system and Anthropic Claude Skills format.

## Quick Start

### Using the Store

```python
from agents.rapp_store_agent import RAPPStoreAgent

store = RAPPStoreAgent()

# Browse available items
store.perform(action='browse')

# Search for specific functionality
store.perform(action='search', query='pdf')

# Install an agent
store.perform(action='install', item_id='pdf_processor_agent')

# Install a skill
store.perform(action='install', item_id='algorithmic-art')
```

### Adding a Custom Store

```python
# Add any compatible RAPP Store repository
store.perform(
    action='add_store',
    store_url='https://github.com/username/their-rapp-store'
)

# Browse items from all registered stores
store.perform(action='browse', include_external=True)
```

## Repository Structure

```
RAPP_Store/
├── manifest.json           # Store manifest (required)
├── README.md              # Documentation
├── agents/                # RAPP Agents
│   ├── agent_name/
│   │   ├── agent_name.py  # Agent code
│   │   ├── metadata.json  # Agent metadata
│   │   └── README.md      # Usage docs
│   └── ...
├── skills/                # Claude Skills
│   ├── skill-name/
│   │   ├── SKILL.md       # Skill definition
│   │   ├── scripts/       # Optional scripts
│   │   ├── references/    # Optional docs
│   │   └── templates/     # Optional templates
│   └── ...
├── docs/                  # Protocol documentation
│   ├── PROTOCOL.md
│   └── CONTRIBUTING.md
└── schema/                # JSON schemas
    └── manifest.schema.json
```

## Protocol Specification (v1.0)

### Manifest Format

Every RAPP Store must have a `manifest.json` at the repository root:

```json
{
  "$schema": "https://rapp-store.github.io/schema/v1/manifest.json",
  "version": "1.0.0",
  "store": {
    "name": "Your Store Name",
    "description": "Store description",
    "owner": "github-username",
    "url": "https://github.com/username/repo",
    "license": "Apache-2.0"
  },
  "protocol": {
    "version": "1.0",
    "supports": ["rapp-agent", "claude-skill"],
    "discovery_endpoint": "manifest.json",
    "raw_base": "https://raw.githubusercontent.com/username/repo/main"
  },
  "agents": [...],
  "skills": [...]
}
```

### Agent Entry Format

```json
{
  "id": "unique_agent_id",
  "type": "rapp-agent",
  "name": "Human Readable Name",
  "description": "What this agent does",
  "version": "1.0.0",
  "category": "category-id",
  "author": "Author Name",
  "license": "Apache-2.0",
  "path": "agents/agent_folder",
  "filename": "agent_file.py",
  "icon": "emoji",
  "tags": ["tag1", "tag2"],
  "features": ["Feature 1", "Feature 2"],
  "dependencies": ["package1", "package2"],
  "min_python": "3.9"
}
```

### Skill Entry Format

```json
{
  "id": "skill-id",
  "type": "claude-skill",
  "name": "Skill Name",
  "description": "What this skill does",
  "version": "1.0.0",
  "category": "category-id",
  "author": "Author Name",
  "license": "Apache-2.0",
  "path": "skills/skill-folder",
  "icon": "emoji",
  "tags": ["tag1", "tag2"],
  "features": ["Feature 1", "Feature 2"],
  "resources": {
    "scripts": ["script1.py"],
    "references": ["doc.md"],
    "templates": ["template.html"]
  }
}
```

## Creating Your Own RAPP Store

### 1. Fork or Create Repository

```bash
# Option A: Fork this repository
gh repo fork kody-w/RAPP_Store

# Option B: Create from scratch
mkdir my-rapp-store && cd my-rapp-store
git init
```

### 2. Create manifest.json

Copy the manifest template and customize:

```json
{
  "$schema": "https://rapp-store.github.io/schema/v1/manifest.json",
  "version": "1.0.0",
  "store": {
    "name": "My RAPP Store",
    "description": "My custom agent and skill collection",
    "owner": "your-username",
    "url": "https://github.com/your-username/my-rapp-store",
    "license": "MIT"
  },
  "protocol": {
    "version": "1.0",
    "supports": ["rapp-agent", "claude-skill"],
    "discovery_endpoint": "manifest.json",
    "raw_base": "https://raw.githubusercontent.com/your-username/my-rapp-store/main"
  },
  "agents": [],
  "skills": []
}
```

### 3. Add Agents

Create agent in `agents/your_agent/your_agent.py`:

```python
from agents.basic_agent import BasicAgent

class YourAgent(BasicAgent):
    def __init__(self):
        self.name = 'YourAgent'
        self.metadata = {
            "name": self.name,
            "description": "What your agent does",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform"
                    }
                },
                "required": ["action"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get('action')
        # Your implementation
        return "Result"
```

Add to manifest.json:

```json
{
  "id": "your_agent",
  "type": "rapp-agent",
  "name": "Your Agent",
  "description": "Description",
  "version": "1.0.0",
  "category": "utilities",
  "path": "agents/your_agent",
  "filename": "your_agent.py"
}
```

### 4. Add Skills

Create skill in `skills/your-skill/SKILL.md`:

```markdown
---
name: your-skill
description: What this skill does and when to use it
---

# Your Skill

Instructions and guidance for using this skill...
```

Add to manifest.json:

```json
{
  "id": "your-skill",
  "type": "claude-skill",
  "name": "Your Skill",
  "description": "Description",
  "version": "1.0.0",
  "category": "utilities",
  "path": "skills/your-skill"
}
```

### 5. Publish

```bash
git add .
git commit -m "Initial RAPP Store setup"
git push origin main
```

### 6. Register (Optional)

Submit a PR to the main RAPP Store to add your store to the federated registry, or share your store URL directly with users.

## Discovery Protocol

### Store Discovery

Agents discover stores via manifest URL:

```
https://raw.githubusercontent.com/{owner}/{repo}/main/manifest.json
```

### Item Discovery

Items are fetched via paths specified in manifest:

**Agents:**
```
{raw_base}/{agent.path}/{agent.filename}
```

**Skills:**
```
{raw_base}/{skill.path}/SKILL.md
{raw_base}/{skill.path}/scripts/{script}
{raw_base}/{skill.path}/references/{reference}
```

### API Endpoints (via GitHub Raw)

| Endpoint | Description |
|----------|-------------|
| `/manifest.json` | Store manifest with all items |
| `/agents/{id}/{filename}` | Agent Python code |
| `/agents/{id}/metadata.json` | Agent metadata |
| `/skills/{id}/SKILL.md` | Skill definition |
| `/skills/{id}/scripts/*` | Skill scripts |
| `/skills/{id}/references/*` | Skill references |

## Cross-Compatibility

### RAPP Agent → Claude Skill

RAPP agents can be wrapped as Claude Skills by:
1. Generating a SKILL.md from agent metadata
2. Embedding agent code in scripts/

### Claude Skill → RAPP Agent

Claude Skills are converted to RAPP agents by:
1. Parsing SKILL.md frontmatter and body
2. Generating Python agent class with embedded instructions
3. Bundling scripts and references

## Categories

| ID | Name | Description |
|----|------|-------------|
| `document-processing` | Document Processing | PDF, Word, Excel, PowerPoint |
| `code-generation` | Code & Development | Code gen, MCP servers |
| `creative` | Creative & Design | Art, design, visual |
| `business` | Business & Enterprise | CRM, sales, analytics |
| `communication` | Communication | Email, messaging |
| `data` | Data & Analytics | Data processing |
| `utilities` | Utilities | General tools |

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines.

## Support

- Issues: [GitHub Issues](https://github.com/kody-w/RAPP_Store/issues)
- Discussions: [GitHub Discussions](https://github.com/kody-w/RAPP_Store/discussions)
