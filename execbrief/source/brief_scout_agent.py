"""
brief_scout_agent.py — Scout persona for the Executive Brief pipeline.

Gathers, structures, and frames intelligence on a business topic.
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
    "name": "@rapp/brief-scout",
    "version": "1.0.0",
    "display_name": "Brief Scout",
    "description": "Research analyst that gathers and structures intelligence on a business topic.",
    "author": "@rapp",
    "tags": ["persona", "exec-brief-pipeline"],
    "category": "analysis",
    "quality_tier": "official",
    "requires_env": [],
}


SOUL = """You are a senior research analyst specializing in technology strategy for
Fortune 100 companies. You gather, verify, and structure intelligence about business
topics. You think in frameworks: market dynamics, stakeholder mapping, competitive
landscape, and trend identification.

Your output is a STRUCTURED INTELLIGENCE BRIEF with these exact sections:
1. SITUATION — what is happening, in 2-3 sentences
2. LANDSCAPE — who are the key players, what are they doing, what patterns emerge
3. SIGNALS — 3-5 specific data points, quotes, or observations that matter
4. GAPS — what information is missing or uncertain

Be concrete. Name names. Cite specifics. Never write "various stakeholders" when you
can write the actual team names. If you don't know a specific, say so — don't fabricate.

You are writing for the next analyst in the chain, not for an executive. Be thorough,
not polished."""


class BriefScoutAgent(BasicAgent):
    def __init__(self):
        self.name = "BriefScout"
        self.metadata = {
            "name": self.name,
            "description": "Research analyst that gathers and structures intelligence on a business topic. Part of the ExecBrief pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The business topic or question to research"
                    },
                },
                "required": ["topic"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, topic="", **kwargs):
        if not topic.strip():
            return json.dumps({"status": "error", "message": "No topic provided"})

        prompt = (
            f"Research the following business topic and produce a structured "
            f"intelligence brief:\n\n"
            f"TOPIC: {topic}\n\n"
            f"Follow your output format exactly: SITUATION, LANDSCAPE, SIGNALS, GAPS."
        )
        result = _llm_call(SOUL, prompt)
        return json.dumps({
            "status": "success",
            "research": result,
            "data_slush": {"topic": topic, "research_complete": True}
        })


# ─── Inlined LLM dispatch (Azure OpenAI / OpenAI / Copilot API) ─────────
# Lives in this file by design: makes the agent.py truly single-file portable.

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
    a = BriefScoutAgent()
    print(a.perform(topic="Why large enterprises need a unified agent sharing standard"))
