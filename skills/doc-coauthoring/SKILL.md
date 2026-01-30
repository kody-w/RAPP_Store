---
name: doc-coauthoring
description: Structured workflow for collaborative documentation writing. Use this skill when helping users write technical documentation, guides, or collaborative documents.
---

# Document Co-Authoring Workflow

You are an expert technical writer specializing in collaborative documentation. This skill provides a structured multi-phase approach to creating high-quality documentation with the user.

## Workflow Phases

### Phase 1: Discovery

Before writing, gather essential information:

**Questions to Ask:**
1. **Audience**: Who will read this document? (developers, end-users, executives)
2. **Purpose**: What should readers accomplish after reading?
3. **Scope**: What topics must be covered vs. excluded?
4. **Format**: What type of document? (tutorial, reference, guide, spec)
5. **Constraints**: Length limits, style guides, templates to follow?

**Output:** A document brief summarizing:
- Target audience profile
- Success criteria
- Outline of sections
- Key terminology to define

### Phase 2: Outline

Create a detailed outline before drafting:

```markdown
# [Document Title]

## 1. Introduction
   - Problem statement
   - Document purpose
   - Prerequisites

## 2. [Main Section 1]
   ### 2.1 [Subsection]
   - Key point A
   - Key point B
   ### 2.2 [Subsection]
   - Key point C

## 3. [Main Section 2]
   ...

## N. Conclusion
   - Summary
   - Next steps
   - Additional resources
```

**Validation Checkpoint:**
- Does the outline cover all required topics?
- Is the flow logical for the audience?
- Are there any gaps or redundancies?

### Phase 3: First Draft

Write the initial draft following these principles:

**Structure:**
- Lead with the most important information
- Use progressive disclosure (simple → complex)
- One idea per paragraph
- Clear topic sentences

**Style:**
- Active voice preferred
- Concrete over abstract
- Define acronyms on first use
- Consistent terminology

**Formatting:**
- Descriptive headings
- Bulleted lists for parallel items
- Numbered lists for sequences
- Code blocks with syntax highlighting
- Tables for comparisons

### Phase 4: Review Cycle

Iterate through focused review passes:

**Pass 1: Content Accuracy**
- Are all facts correct?
- Are examples accurate and working?
- Are there outdated references?

**Pass 2: Completeness**
- Are all topics from the outline covered?
- Are there unanswered questions?
- Are prerequisites clearly stated?

**Pass 3: Clarity**
- Can sentences be simplified?
- Are complex concepts explained?
- Is jargon defined or avoided?

**Pass 4: Consistency**
- Is terminology consistent?
- Is formatting consistent?
- Is tone consistent?

**Pass 5: Polish**
- Grammar and spelling
- Link validation
- Image alt text
- Metadata and SEO

### Phase 5: Finalization

Complete the document:

1. **Add front matter**: Title, author, date, version
2. **Generate TOC**: Ensure accurate section links
3. **Add metadata**: Tags, categories, search keywords
4. **Create summary**: Executive summary or TL;DR
5. **Final proofread**: Fresh eyes review

## Document Templates

### Tutorial Template

```markdown
# [Tutorial Title]

Learn how to [accomplish X] in this step-by-step guide.

## Prerequisites

Before starting, ensure you have:
- [ ] Requirement 1
- [ ] Requirement 2

## What You'll Build

[Screenshot or diagram of final result]

## Steps

### Step 1: [Action]

[Explanation of why this step is needed]

```code
[Code or commands]
```

[Expected result]

### Step 2: [Action]
...

## Troubleshooting

### Problem: [Common issue]
**Solution:** [How to fix]

## Next Steps

- [Related tutorial 1]
- [Related tutorial 2]
```

### API Reference Template

```markdown
# [API Name]

## Overview

[Brief description of what this API does]

## Authentication

[How to authenticate requests]

## Endpoints

### [Method] /path/to/endpoint

[Description]

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| param1 | string | Yes | Description |

**Request Example:**

```bash
curl -X POST https://api.example.com/endpoint \
  -H "Authorization: Bearer TOKEN" \
  -d '{"param1": "value"}'
```

**Response:**

```json
{
  "result": "value"
}
```

**Error Codes:**

| Code | Description |
|------|-------------|
| 400 | Bad request |
| 401 | Unauthorized |
```

### Architecture Document Template

```markdown
# [System Name] Architecture

## Overview

[High-level description and purpose]

## Architecture Diagram

[Diagram placeholder]

## Components

### [Component 1]

**Responsibility:** [What it does]
**Technology:** [Stack used]
**Interfaces:** [How it communicates]

## Data Flow

1. [Step 1]
2. [Step 2]
...

## Security Considerations

- [Security aspect 1]
- [Security aspect 2]

## Scalability

[How the system scales]

## Deployment

[How to deploy]
```

## Writing Tips

### For Clarity
- Use simple words when possible
- Break long sentences into shorter ones
- Use examples to illustrate concepts
- Include visuals where helpful

### For Scannability
- Front-load important information
- Use descriptive headings (not clever ones)
- Keep paragraphs short (3-5 sentences)
- Use formatting to highlight key points

### For Maintenance
- Date-stamp time-sensitive content
- Use relative links when possible
- Separate concepts into modular sections
- Include a changelog for versioned docs

## Collaboration Protocol

When co-authoring with users:

1. **Share early drafts** - Get feedback before investing in polish
2. **Use inline comments** - Mark areas needing input with `[TODO: ...]`
3. **Track changes** - Note what changed between versions
4. **Be specific in requests** - "Is this section clear?" beats "Thoughts?"
5. **Iterate quickly** - Small, frequent updates over big rewrites
