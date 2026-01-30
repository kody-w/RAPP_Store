"""
RAPP Store Agent - Universal Agent and Skill Marketplace Interface

Enables browsing, searching, and installing agents and skills from RAPP Store
repositories. Supports both RAPP Agents and Claude Skills with cross-format
conversion capabilities.

Part of the RAPP Store - https://github.com/kody-w/RAPP_Store
"""

from agents.basic_agent import BasicAgent
import logging
import json
import re
from datetime import datetime

# Try to import httpx for async HTTP requests, fall back to urllib
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_HTTPX = False


class RAPPStoreAgent(BasicAgent):
    """
    Universal marketplace agent for RAPP Agents and Claude Skills.

    Supports:
    - Browsing available agents and skills
    - Searching by name, category, or tags
    - Installing items to local system
    - Adding external RAPP Store repositories
    - Cross-format conversion (Agent ↔ Skill)
    """

    # Default store configuration
    DEFAULT_STORE = {
        "name": "RAPP Store",
        "owner": "kody-w",
        "repo": "RAPP_Store",
        "branch": "main"
    }

    def __init__(self):
        self.name = 'RAPPStore'
        self.metadata = {
            "name": self.name,
            "description": "Universal marketplace for RAPP Agents and Claude Skills. Browse, search, and install agents/skills from RAPP Store repositories. Supports cross-format conversion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'browse' (list all items), 'search' (find by query), 'details' (item info), 'install' (download item), 'add_store' (add external store), 'list_stores' (show registered stores), 'convert' (change format)",
                        "enum": ["browse", "search", "details", "install", "add_store", "list_stores", "convert", "categories"]
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for 'search' action"
                    },
                    "item_id": {
                        "type": "string",
                        "description": "Item ID for 'details', 'install', or 'convert' actions"
                    },
                    "item_type": {
                        "type": "string",
                        "description": "Filter by type: 'agent', 'skill', or 'all'",
                        "enum": ["agent", "skill", "all"]
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category ID"
                    },
                    "store_url": {
                        "type": "string",
                        "description": "GitHub repository URL for 'add_store' action"
                    },
                    "target_format": {
                        "type": "string",
                        "description": "Target format for 'convert' action: 'agent' or 'skill'",
                        "enum": ["agent", "skill"]
                    },
                    "include_external": {
                        "type": "boolean",
                        "description": "Include items from external stores (default: true)"
                    }
                },
                "required": ["action"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

        # Registered stores
        self.stores = [self.DEFAULT_STORE]
        self._manifest_cache = {}

    def perform(self, **kwargs):
        action = kwargs.get('action')

        try:
            if action == 'browse':
                return self._browse(kwargs)
            elif action == 'search':
                return self._search(kwargs)
            elif action == 'details':
                return self._get_details(kwargs)
            elif action == 'install':
                return self._install(kwargs)
            elif action == 'add_store':
                return self._add_store(kwargs)
            elif action == 'list_stores':
                return self._list_stores()
            elif action == 'convert':
                return self._convert(kwargs)
            elif action == 'categories':
                return self._list_categories()
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            logging.error(f"Error in RAPPStoreAgent: {str(e)}")
            return f"Error: {str(e)}"

    def _get_raw_url(self, store: dict, path: str) -> str:
        """Get raw GitHub URL for a file."""
        return f"https://raw.githubusercontent.com/{store['owner']}/{store['repo']}/{store['branch']}/{path}"

    def _fetch_url(self, url: str) -> str:
        """Fetch content from URL."""
        if HAS_HTTPX:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
        else:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read().decode('utf-8')

    def _fetch_manifest(self, store: dict) -> dict:
        """Fetch and cache store manifest."""
        cache_key = f"{store['owner']}/{store['repo']}"
        if cache_key in self._manifest_cache:
            return self._manifest_cache[cache_key]

        url = self._get_raw_url(store, 'manifest.json')
        content = self._fetch_url(url)
        manifest = json.loads(content)
        self._manifest_cache[cache_key] = manifest
        return manifest

    def _get_all_items(self, include_external: bool = True) -> list:
        """Get all items from all stores."""
        items = []
        stores_to_check = self.stores if include_external else [self.DEFAULT_STORE]

        for store in stores_to_check:
            try:
                manifest = self._fetch_manifest(store)
                store_name = manifest.get('store', {}).get('name', 'Unknown')

                # Add agents
                for agent in manifest.get('agents', []):
                    items.append({
                        **agent,
                        'item_type': 'agent',
                        'store': store_name,
                        '_store_config': store
                    })

                # Add skills
                for skill in manifest.get('skills', []):
                    items.append({
                        **skill,
                        'item_type': 'skill',
                        'store': store_name,
                        '_store_config': store
                    })
            except Exception as e:
                logging.warning(f"Failed to fetch from {store['owner']}/{store['repo']}: {e}")

        return items

    def _browse(self, params: dict) -> str:
        """Browse all available items."""
        item_type = params.get('item_type', 'all')
        category = params.get('category')
        include_external = params.get('include_external', True)

        items = self._get_all_items(include_external)

        # Filter by type
        if item_type != 'all':
            items = [i for i in items if i['item_type'] == item_type]

        # Filter by category
        if category:
            items = [i for i in items if i.get('category') == category]

        if not items:
            return "No items found matching your criteria."

        # Group by type
        agents = [i for i in items if i['item_type'] == 'agent']
        skills = [i for i in items if i['item_type'] == 'skill']

        response = f"""🏪 RAPP Store Browser

📊 Found {len(items)} items ({len(agents)} agents, {len(skills)} skills)

"""

        if agents:
            response += "## 🤖 Agents\n\n"
            for agent in agents:
                response += f"**{agent.get('icon', '🤖')} {agent['name']}** (`{agent['id']}`)\n"
                response += f"   {agent['description'][:80]}{'...' if len(agent['description']) > 80 else ''}\n"
                response += f"   Category: {agent.get('category', 'N/A')} | v{agent.get('version', '1.0.0')}\n\n"

        if skills:
            response += "## ✨ Skills\n\n"
            for skill in skills:
                response += f"**{skill.get('icon', '✨')} {skill['name']}** (`{skill['id']}`)\n"
                response += f"   {skill['description'][:80]}{'...' if len(skill['description']) > 80 else ''}\n"
                response += f"   Category: {skill.get('category', 'N/A')} | v{skill.get('version', '1.0.0')}\n\n"

        response += """---
**Commands:**
• `action='details', item_id='...'` - Get full details
• `action='install', item_id='...'` - Install item
• `action='search', query='...'` - Search by keyword
• `action='categories'` - List all categories
"""

        return response

    def _search(self, params: dict) -> str:
        """Search for items by query."""
        query = params.get('query', '').lower()
        if not query:
            return "Error: 'query' parameter is required for search action"

        items = self._get_all_items()

        # Search in name, description, and tags
        matches = []
        for item in items:
            score = 0
            if query in item['name'].lower():
                score += 3
            if query in item['id'].lower():
                score += 2
            if query in item['description'].lower():
                score += 1
            if any(query in tag.lower() for tag in item.get('tags', [])):
                score += 2
            if score > 0:
                matches.append((item, score))

        # Sort by score
        matches.sort(key=lambda x: x[1], reverse=True)

        if not matches:
            return f"No items found matching '{query}'"

        response = f"""🔍 Search Results for "{query}"

Found {len(matches)} matching items:

"""

        for item, score in matches[:10]:
            type_icon = '🤖' if item['item_type'] == 'agent' else '✨'
            response += f"**{item.get('icon', type_icon)} {item['name']}** (`{item['id']}`)\n"
            response += f"   {item['description'][:80]}{'...' if len(item['description']) > 80 else ''}\n"
            response += f"   Type: {item['item_type'].capitalize()} | Category: {item.get('category', 'N/A')}\n\n"

        if len(matches) > 10:
            response += f"\n...and {len(matches) - 10} more results\n"

        return response

    def _get_details(self, params: dict) -> str:
        """Get detailed information about an item."""
        item_id = params.get('item_id')
        if not item_id:
            return "Error: 'item_id' parameter is required"

        items = self._get_all_items()
        item = next((i for i in items if i['id'] == item_id), None)

        if not item:
            return f"Error: Item '{item_id}' not found"

        type_icon = '🤖' if item['item_type'] == 'agent' else '✨'

        response = f"""📋 Item Details

# {item.get('icon', type_icon)} {item['name']}

**ID:** `{item['id']}`
**Type:** {item['item_type'].capitalize()}
**Version:** {item.get('version', '1.0.0')}
**Category:** {item.get('category', 'N/A')}
**Author:** {item.get('author', 'Unknown')}
**License:** {item.get('license', 'Not specified')}
**Store:** {item.get('store', 'RAPP Store')}

## Description

{item['description']}

## Features

"""
        for feature in item.get('features', []):
            response += f"• {feature}\n"

        if item.get('tags'):
            response += f"\n## Tags\n\n{', '.join(item['tags'])}\n"

        if item.get('dependencies'):
            response += f"\n## Dependencies\n\n"
            for dep in item['dependencies']:
                response += f"• {dep}\n"

        response += f"""
---
**Actions:**
• `action='install', item_id='{item_id}'` - Download this item
• `action='convert', item_id='{item_id}', target_format='skill'` - Convert to skill format
• `action='convert', item_id='{item_id}', target_format='agent'` - Convert to agent format
"""

        return response

    def _install(self, params: dict) -> str:
        """Install an item (returns the code/content)."""
        item_id = params.get('item_id')
        if not item_id:
            return "Error: 'item_id' parameter is required"

        items = self._get_all_items()
        item = next((i for i in items if i['id'] == item_id), None)

        if not item:
            return f"Error: Item '{item_id}' not found"

        store = item.get('_store_config', self.DEFAULT_STORE)

        try:
            if item['item_type'] == 'agent':
                # Fetch agent Python code
                url = self._get_raw_url(store, f"{item['path']}/{item['filename']}")
                code = self._fetch_url(url)

                return f"""📥 Downloaded Agent: {item['name']}

**Installation Instructions:**
1. Save the code below to `agents/{item['id']}/{item['filename']}`
2. Restart your agent system to load the new agent

**Dependencies:** {', '.join(item.get('dependencies', [])) or 'None'}

---

```python
{code}
```
"""
            else:
                # Fetch skill SKILL.md
                url = self._get_raw_url(store, f"{item['path']}/SKILL.md")
                content = self._fetch_url(url)

                return f"""📥 Downloaded Skill: {item['name']}

**Installation Instructions:**
1. Save the content below to `skills/{item['id']}/SKILL.md`
2. Add to your Claude skills configuration

---

```markdown
{content}
```
"""
        except Exception as e:
            return f"Error downloading item: {str(e)}"

    def _convert(self, params: dict) -> str:
        """Convert an item between formats."""
        item_id = params.get('item_id')
        target_format = params.get('target_format')

        if not item_id:
            return "Error: 'item_id' parameter is required"
        if not target_format:
            return "Error: 'target_format' parameter is required ('agent' or 'skill')"

        items = self._get_all_items()
        item = next((i for i in items if i['id'] == item_id), None)

        if not item:
            return f"Error: Item '{item_id}' not found"

        if target_format == 'agent':
            code = self._generate_agent_from_item(item)
            return f"""🔄 Converted to RAPP Agent

**Original:** {item['name']} ({item['item_type']})
**Target:** RAPP Agent

**Save as:** `agents/{item['id']}_agent/{item['id']}_agent.py`

---

```python
{code}
```
"""
        else:
            content = self._generate_skill_from_item(item)
            return f"""🔄 Converted to Claude Skill

**Original:** {item['name']} ({item['item_type']})
**Target:** Claude Skill

**Save as:** `skills/{item['id']}/SKILL.md`

---

```markdown
{content}
```
"""

    def _generate_agent_from_item(self, item: dict) -> str:
        """Generate RAPP Agent code from item metadata."""
        # Create class name from ID
        class_name = ''.join(
            part.capitalize() for part in re.split(r'[-_]', item['id'])
        ) + 'Agent'

        features_list = '\n'.join(f'    - {f}' for f in item.get('features', []))

        return f'''"""
{item['name']} - RAPP Agent

{item['description']}

Generated from RAPP Store - https://github.com/kody-w/RAPP_Store
Original Type: {item['item_type']}
"""

from agents.basic_agent import BasicAgent
import logging


class {class_name}(BasicAgent):
    """
    {item['description']}

    Features:
{features_list}
    """

    def __init__(self):
        self.name = '{class_name.replace("Agent", "")}'
        self.metadata = {{
            "name": self.name,
            "description": "{item['description']}",
            "parameters": {{
                "type": "object",
                "properties": {{
                    "action": {{
                        "type": "string",
                        "description": "Action to perform: 'help' (show capabilities), 'execute' (perform task)",
                        "enum": ["help", "execute"]
                    }},
                    "request": {{
                        "type": "string",
                        "description": "Your request or task description"
                    }}
                }},
                "required": ["action"]
            }}
        }}
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get('action', 'help')
        request = kwargs.get('request', '')

        try:
            if action == 'help':
                return self._show_help()
            elif action == 'execute':
                return self._execute(request)
            else:
                return f"Unknown action '{{action}}'. Use 'help' or 'execute'."
        except Exception as e:
            logging.error(f"Error in {class_name}: {{str(e)}}")
            return f"Error: {{str(e)}}"

    def _show_help(self):
        return """{item.get('icon', '🤖')} {item['name']}

{item['description']}

**Features:**
{chr(10).join('• ' + f for f in item.get('features', []))}

**Usage:**
action='execute', request='your task description'
"""

    def _execute(self, request: str):
        if not request:
            return "Error: 'request' parameter is required for 'execute' action"

        return f"""Processing request: {{request}}

This agent provides {item['name'].lower()} capabilities.
Please implement specific logic based on your requirements.
"""
'''

    def _generate_skill_from_item(self, item: dict) -> str:
        """Generate Claude Skill content from item metadata."""
        features = '\n'.join(f'- {f}' for f in item.get('features', []))

        return f"""---
name: {item['id']}
description: {item['description']}
---

# {item['name']}

{item['description']}

## Features

{features}

## Usage

This skill provides guidance for {item['name'].lower()} tasks.

## Original Source

- **Type:** {item['item_type'].capitalize()}
- **Version:** {item.get('version', '1.0.0')}
- **Category:** {item.get('category', 'N/A')}
- **Author:** {item.get('author', 'Unknown')}
- **License:** {item.get('license', 'Apache-2.0')}

Generated from RAPP Store - https://github.com/kody-w/RAPP_Store
"""

    def _add_store(self, params: dict) -> str:
        """Add an external RAPP Store repository."""
        store_url = params.get('store_url')
        if not store_url:
            return "Error: 'store_url' parameter is required"

        # Parse GitHub URL
        match = re.match(r'https://github\.com/([^/]+)/([^/]+)', store_url)
        if not match:
            return "Error: Invalid GitHub URL. Expected format: https://github.com/owner/repo"

        owner, repo = match.groups()
        repo = repo.rstrip('.git')

        # Check if already registered
        for store in self.stores:
            if store['owner'] == owner and store['repo'] == repo:
                return f"Store '{owner}/{repo}' is already registered"

        # Verify manifest exists
        new_store = {
            "name": f"{owner}/{repo}",
            "owner": owner,
            "repo": repo,
            "branch": "main"
        }

        try:
            manifest = self._fetch_manifest(new_store)
            store_name = manifest.get('store', {}).get('name', f"{owner}/{repo}")
            agent_count = len(manifest.get('agents', []))
            skill_count = len(manifest.get('skills', []))

            self.stores.append(new_store)

            return f"""✅ Store Added Successfully

**Name:** {store_name}
**URL:** {store_url}
**Items:** {agent_count} agents, {skill_count} skills

The store's items are now available when browsing and searching.
"""
        except Exception as e:
            return f"Error: Could not fetch manifest from '{store_url}'. Make sure it's a valid RAPP Store repository. ({str(e)})"

    def _list_stores(self) -> str:
        """List all registered stores."""
        response = """📚 Registered RAPP Stores

"""
        for i, store in enumerate(self.stores):
            try:
                manifest = self._fetch_manifest(store)
                store_name = manifest.get('store', {}).get('name', f"{store['owner']}/{store['repo']}")
                agent_count = len(manifest.get('agents', []))
                skill_count = len(manifest.get('skills', []))
                default_marker = " (default)" if i == 0 else ""

                response += f"**{i+1}. {store_name}**{default_marker}\n"
                response += f"   URL: https://github.com/{store['owner']}/{store['repo']}\n"
                response += f"   Items: {agent_count} agents, {skill_count} skills\n\n"
            except Exception as e:
                response += f"**{i+1}. {store['owner']}/{store['repo']}** (error fetching)\n\n"

        response += """---
**Add a store:**
`action='add_store', store_url='https://github.com/owner/repo'`
"""

        return response

    def _list_categories(self) -> str:
        """List all available categories."""
        try:
            manifest = self._fetch_manifest(self.DEFAULT_STORE)
            categories = manifest.get('categories', [])

            response = """📂 Available Categories

"""
            for cat in categories:
                response += f"**{cat.get('icon', '📁')} {cat['name']}** (`{cat['id']}`)\n"
                response += f"   {cat.get('description', '')}\n\n"

            response += """---
**Filter by category:**
`action='browse', category='category-id'`
"""

            return response
        except Exception as e:
            return f"Error fetching categories: {str(e)}"
