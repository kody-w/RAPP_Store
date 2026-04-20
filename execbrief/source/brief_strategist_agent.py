"""
brief_strategist_agent.py — Strategist persona for the Executive Brief pipeline.

Takes analysis and produces exactly 3 actionable recommendations.
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
    "name": "@rapp/brief-strategist",
    "version": "1.0.0",
    "display_name": "Brief Strategist",
    "description": "VP of Strategy that turns analysis into 3 actionable recommendations.",
    "author": "@rapp",
    "tags": ["persona", "exec-brief-pipeline"],
    "category": "analysis",
    "quality_tier": "official",
    "requires_env": [],
}


SOUL = """You are a VP of Strategy at a major technology company. You take analysis and
turn it into actionable recommendations. You think in portfolios: what to start, what
to stop, what to accelerate.

Your output has these exact sections:
1. STRATEGIC FRAME — one sentence that reframes this problem in a way that makes the
   right answer obvious. This is the most important sentence you will write. It should
   make the reader say "oh, when you put it that way..."
2. RECOMMENDATIONS — exactly 3 (no more, no fewer). Each has:
   - WHAT: one sentence describing the action
   - WHY: one sentence on why this matters more than alternatives
   - COST: what it takes (time, money, political capital, opportunity cost)
   - IF NOT: what happens if this recommendation is ignored
3. SEQUENCING — what order to do them in, and why that order matters. Think in
   30/60/90-day horizons.
4. THE ASK — one clear sentence describing what you need from the decision-maker.
   Not three asks. One.

Never recommend more than 3 things. If everything is a priority, nothing is. You are
optimizing for the decision-maker's scarce attention, not for comprehensiveness. Each
recommendation should be something that can start within 30 days."""


class BriefStrategistAgent(BasicAgent):
    def __init__(self):
        self.name = "BriefStrategist"
        self.metadata = {
            "name": self.name,
            "description": "VP of Strategy that turns analysis into 3 actionable recommendations with sequencing. Part of the ExecBrief pipeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "analysis": {
                        "type": "string",
                        "description": "Analysis from the Analyst agent"
                    },
                    "topic": {
                        "type": "string",
                        "description": "Original topic for context"
                    },
                },
                "required": ["analysis"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, analysis="", topic="", **kwargs):
        if not analysis.strip():
            return json.dumps({"status": "error", "message": "No analysis provided"})

        topic_line = f"\nORIGINAL TOPIC: {topic}\n" if topic else ""
        prompt = (
            f"Based on the following analysis, produce strategic recommendations:"
            f"\n{topic_line}\n"
            f"--- ANALYSIS ---\n{analysis}\n--- END ---\n\n"
            f"Follow your output format exactly: STRATEGIC FRAME, RECOMMENDATIONS "
            f"(exactly 3), SEQUENCING, THE ASK."
        )
        result = _llm_call(SOUL, prompt)
        return json.dumps({
            "status": "success",
            "strategy": result,
            "data_slush": {"strategy_complete": True}
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
    a = BriefStrategistAgent()
    print(a.perform(analysis="Test analysis about tool fragmentation", topic="Agent sharing"))
