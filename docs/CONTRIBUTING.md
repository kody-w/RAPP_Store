# Contributing to RAPP Store

Thank you for your interest in contributing to the RAPP Store! This document provides guidelines for contributing agents, skills, and improvements to the project.

## Ways to Contribute

### 1. Submit a New Agent

RAPP Agents are Python classes that follow a specific pattern:

```python
from agents.basic_agent import BasicAgent

class YourAgent(BasicAgent):
    def __init__(self):
        self.name = 'YourAgent'
        self.metadata = {
            "name": self.name,
            "description": "Clear, concise description of what this agent does",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform",
                        "enum": ["action1", "action2"]
                    }
                    # Add more parameters as needed
                },
                "required": ["action"]
            }
        }
        super().__init__(self.name, self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get('action')
        # Your implementation
        return "Result"
```

**Checklist for new agents:**
- [ ] Follows `BasicAgent` pattern
- [ ] Has clear, descriptive metadata
- [ ] Includes comprehensive parameter documentation
- [ ] Handles errors gracefully
- [ ] Includes logging for debugging
- [ ] Has a README.md with usage examples

### 2. Submit a New Skill

Claude Skills are Markdown files with YAML frontmatter:

```markdown
---
name: your-skill
description: What this skill does and when to use it
---

# Your Skill

Detailed instructions and guidance...
```

**Checklist for new skills:**
- [ ] Valid YAML frontmatter with name and description
- [ ] Clear, actionable instructions
- [ ] Examples where appropriate
- [ ] Any required scripts in `scripts/` folder
- [ ] Reference documentation in `references/` folder if needed

### 3. Improve Existing Items

- Fix bugs or issues
- Improve documentation
- Add new features
- Optimize performance

### 4. Report Issues

- Bug reports
- Feature requests
- Documentation improvements
- Security vulnerabilities

## Contribution Process

### Step 1: Fork the Repository

```bash
gh repo fork kody-w/RAPP_Store
```

### Step 2: Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

### Step 3: Make Your Changes

Follow the coding standards and guidelines below.

### Step 4: Update the Manifest

Add your item to `manifest.json`:

**For agents:**
```json
{
  "id": "your_agent",
  "type": "rapp-agent",
  "name": "Your Agent",
  "description": "What it does",
  "version": "1.0.0",
  "category": "appropriate-category",
  "author": "Your Name",
  "license": "Apache-2.0",
  "path": "agents/your_agent",
  "filename": "your_agent.py",
  "icon": "🤖",
  "tags": ["tag1", "tag2"],
  "features": ["Feature 1", "Feature 2"],
  "dependencies": [],
  "min_python": "3.9"
}
```

**For skills:**
```json
{
  "id": "your-skill",
  "type": "claude-skill",
  "name": "Your Skill",
  "description": "What it does",
  "version": "1.0.0",
  "category": "appropriate-category",
  "author": "Your Name",
  "license": "Apache-2.0",
  "path": "skills/your-skill",
  "icon": "✨",
  "tags": ["tag1", "tag2"],
  "features": ["Feature 1", "Feature 2"]
}
```

### Step 5: Test Your Changes

- Ensure the agent/skill works correctly
- Verify manifest.json is valid JSON
- Check that all paths are correct

### Step 6: Submit a Pull Request

```bash
git add .
git commit -m "Add: Your Agent/Skill name"
git push origin feature/your-feature-name
```

Then create a PR on GitHub with:
- Clear title describing the addition
- Description of what the agent/skill does
- Any special instructions or dependencies

## Coding Standards

### Python Agents

1. **Follow PEP 8** style guidelines
2. **Use type hints** where appropriate
3. **Include docstrings** for classes and methods
4. **Handle exceptions** gracefully
5. **Use logging** instead of print statements

```python
import logging

class MyAgent(BasicAgent):
    """
    Agent description.

    Features:
    - Feature 1
    - Feature 2
    """

    def perform(self, **kwargs) -> str:
        """
        Execute agent action.

        Args:
            **kwargs: Action parameters

        Returns:
            str: Action result
        """
        try:
            # Implementation
            pass
        except Exception as e:
            logging.error(f"Error in MyAgent: {str(e)}")
            return f"Error: {str(e)}"
```

### Markdown Skills

1. **Use clear headings** (##, ###)
2. **Include examples** with code blocks
3. **Be concise** but comprehensive
4. **Use lists** for multiple items
5. **Include a "Usage" section**

### Commit Messages

Use conventional commits:
- `Add:` New feature or item
- `Fix:` Bug fix
- `Update:` Improvement to existing item
- `Docs:` Documentation changes
- `Refactor:` Code restructuring

Examples:
```
Add: PDF Processor Agent with form filling support
Fix: Email Assistant template encoding issue
Update: Improve MCP Builder skill examples
Docs: Add contributing guidelines
```

## Review Process

1. **Automated Checks**: CI validates manifest.json structure
2. **Code Review**: Maintainers review code quality and security
3. **Testing**: Verify functionality works as described
4. **Documentation**: Ensure adequate documentation exists

## Categories

Choose the appropriate category for your item:

| Category | Use For |
|----------|---------|
| `document-processing` | PDF, Word, Excel, document tools |
| `code-generation` | Code generators, MCP servers, dev tools |
| `creative` | Art, design, creative tools |
| `business` | CRM, sales, enterprise tools |
| `communication` | Email, messaging, collaboration |
| `data` | Data analysis, visualization |
| `utilities` | General-purpose tools |

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.

## Questions?

- Open an issue for questions
- Start a discussion for ideas
- Tag maintainers for urgent matters

Thank you for contributing to the RAPP Store!
