"""
brief_writer_agent.py — Writer persona for the Executive Brief pipeline.

Takes the full pipeline context and composes a polished sub-400-word executive brief.
Drop this file into any RAPP brainstem's agents/ directory and it works.
"""

import json
import os
import urllib.request
import urllib.error

try:
    from agents.basic_agent import BasicAgent
except ImportError:
    from basic_agent import BasicAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/brief-writer",
    "version": "1.0.0",
    "display_name": "Brief Writer",
    "description": "Executive communications director that composes polished sub-400-word briefs.",
    "author": "@rapp",
    "tags": ["persona", "exec-brief-pipeline"],
    "category": "analysis",
    "quality_tier": "official",
    "requires_env": [],
}


SOUL = """You are an executive communications director who writes for C-suite readers.
You know your reader has 3 minutes and will be interrupted twice.

Rules:
- Lead with the "so what." First sentence is the conclusion.
- Pyramid principle: answer first, evidence after.
- Bullets over paragraphs. Every bullet earns its place.
- One clear ask at the end. Not three asks. One.
- If the reader remembers one thing, make sure it is the right thing.
- No jargon unless the reader uses it daily.
- Bold the 3-5 most important phrases in the entire brief.
- Total length: under 400 words. If you need more, you have not edited enough.

Format exactly like this:

# [TITLE — 8 words or fewer]

**Bottom line:** [one sentence]

**Context:** [2-3 sentences max]

**What we found:**
- [key finding 1]
- [key finding 2]

**What we recommend:**
1. [recommendation 1 — one sentence]
2. [recommendation 2 — one sentence]
3. [recommendation 3 — one sentence]

**What we are asking for:** [one sentence]

---
*Prepared by the ExecBrief pipeline — 4 agents, one file.*

The brief should feel like it was written by someone who respects the reader's time
more than their own word count. Every sentence must survive the test: "would the
reader's decision change if I cut this?" If no, cut it."""


class BriefWriterAgent(BasicAgent):
    def __init__(self):
        self.name = "BriefWriter"
        self.metadata = {
            "name": self.name,
            "description": "Executive communications director that composes a polished sub-400-word brief from pipeline inputs. Part of the ExecBrief pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The original business topic"
                    },
                    "research": {
                        "type": "string",
                        "description": "Structured research from the Scout"
                    },
                    "analysis": {
                        "type": "string",
                        "description": "Insights and risks from the Analyst"
                    },
                    "strategy": {
                        "type": "string",
                        "description": "Recommendations from the Strategist"
                    },
                },
                "required": ["strategy"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, topic="", research="", analysis="", strategy="", **kwargs):
        if not strategy.strip():
            return json.dumps({"status": "error", "message": "No strategy provided"})

        sections = []
        if topic:
            sections.append(f"TOPIC: {topic}")
        if research:
            sections.append(f"RESEARCH:\n{research}")
        if analysis:
            sections.append(f"ANALYSIS:\n{analysis}")
        sections.append(f"STRATEGY & RECOMMENDATIONS:\n{strategy}")

        prompt = (
            f"Compose a polished executive brief from the following pipeline outputs. "
            f"Follow your format exactly. Under 400 words. The brief must stand alone — "
            f"the reader has not seen the research, analysis, or strategy documents.\n\n"
            + "\n\n---\n\n".join(sections)
        )
        result = _llm_call(SOUL, prompt)
        return json.dumps({
            "status": "success",
            "brief": result,
            "data_slush": {"brief_complete": True}
        })


# ─── Inlined LLM dispatch (Azure OpenAI / OpenAI / Copilot API) ─────────

def _llm_call(soul: str, user_prompt: str) -> str:
    messages = [{"role": "system", "content": soul},
                {"role": "user", "content": user_prompt}]

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = (os.environ.get("AZURE_OPENAI_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", ""))
    if endpoint and api_key:
        url = endpoint.rstrip("/")
        if "/chat/completions" not in url:
            url = f"{url}/openai/deployments/{deployment}/chat/completions?api-version=2025-01-01-preview"
        elif "?" not in url:
            url += "?api-version=2025-01-01-preview"
        return _post(url, {"messages": messages, "model": deployment},
                     {"Content-Type": "application/json", "api-key": api_key})

    if os.environ.get("OPENAI_API_KEY"):
        return _post("https://api.openai.com/v1/chat/completions",
                     {"model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
                      "messages": messages},
                     {"Content-Type": "application/json",
                      "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})

    import time as _time
    session_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".copilot_session")
    if os.path.exists(session_file):
        try:
            with open(session_file) as f:
                sess = json.load(f)
            if sess.get("token") and _time.time() < sess.get("expires_at", 0) - 60:
                return _post(
                    sess["endpoint"] + "/chat/completions",
                    {"model": os.environ.get("GITHUB_MODEL", "gpt-4o"),
                     "messages": messages},
                    {"Content-Type": "application/json",
                     "Authorization": "Bearer " + sess["token"],
                     "Editor-Version": "vscode/1.95.0",
                     "Copilot-Integration-Id": "vscode-chat"})
        except Exception:
            pass

    return "(no LLM configured — set AZURE_OPENAI_*, OPENAI_API_KEY, or start brainstem for Copilot)"


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        choices = j.get("choices") or []
        return (choices[0]["message"].get("content") or "") if choices else ""
    except urllib.error.HTTPError as e:
        return f"(LLM HTTP {e.code}: {e.read().decode('utf-8')[:200]})"
    except urllib.error.URLError as e:
        return f"(LLM network error: {e})"


if __name__ == "__main__":
    a = BriefWriterAgent()
    print(a.perform(topic="Agent sharing", strategy="Test strategy recommendations"))
