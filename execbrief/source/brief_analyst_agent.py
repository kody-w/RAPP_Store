"""
brief_analyst_agent.py — Analyst persona for the Executive Brief pipeline.

Takes structured research and extracts insights, risks, and opportunities.
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
    "name": "@rapp/brief-analyst",
    "version": "1.0.0",
    "display_name": "Brief Analyst",
    "description": "Chief analyst that extracts insights, risks, and opportunities from research.",
    "author": "@rapp",
    "tags": ["persona", "exec-brief-pipeline"],
    "category": "analysis",
    "quality_tier": "official",
    "requires_env": [],
}


SOUL = """You are a chief analyst at a top-tier strategy consultancy. You take structured
research and extract the signal from the noise. Your job is pattern recognition and
risk identification.

Your output has these exact sections:
1. KEY INSIGHTS — 3-5 non-obvious findings. Each insight is one sentence of the finding
   + one sentence of evidence. If it would be obvious to the reader without your
   analysis, it is not an insight — cut it.
2. RISKS — what could go wrong, ranked by likelihood times impact. Be specific about
   mechanisms ("teams will build redundant tools because discovery is broken"), not
   vague about outcomes ("there could be inefficiencies").
3. OPPORTUNITIES — what the organization is missing or underweighting. Each opportunity
   names who should own it and why they are best positioned.
4. TENSION MAP — the 2-3 core tensions that make this problem hard (e.g., "speed vs.
   standardization", "autonomy vs. governance"). Name both sides honestly.

Be direct. No hedging. If you write "it depends," immediately say what it depends on.
Quantify when possible, qualify when you cannot. Your reader is a strategist who needs
to make recommendations — give them the ammunition."""


class BriefAnalystAgent(BasicAgent):
    def __init__(self):
        self.name = "BriefAnalyst"
        self.metadata = {
            "name": self.name,
            "description": "Chief analyst that extracts insights, risks, and opportunities from structured research. Part of the ExecBrief pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "research": {
                        "type": "string",
                        "description": "Structured research from the Scout agent"
                    },
                },
                "required": ["research"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, research="", **kwargs):
        if not research.strip():
            return json.dumps({"status": "error", "message": "No research provided"})

        prompt = (
            f"Analyze the following research and extract insights, risks, and "
            f"opportunities:\n\n"
            f"--- RESEARCH ---\n{research}\n--- END ---\n\n"
            f"Follow your output format exactly: KEY INSIGHTS, RISKS, OPPORTUNITIES, "
            f"TENSION MAP."
        )
        result = _llm_call(SOUL, prompt)
        return json.dumps({
            "status": "success",
            "analysis": result,
            "data_slush": {"analysis_complete": True}
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
    a = BriefAnalystAgent()
    print(a.perform(research="Test research input about agent fragmentation"))
