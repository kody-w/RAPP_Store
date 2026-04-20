"""persona_reviewer_agent.py — Reviewer persona, single sacred agent.py."""
from agents.basic_agent import BasicAgent
import json, os, urllib.request, urllib.error

__manifest__ = {"schema": "rapp-agent/1.0", "name": "@rapp/persona-reviewer",
                "tier": "core", "trust": "community", "version": "0.1.0",
                "tags": ["persona", "creative-pipeline"]}

SOUL = """You are a smart reader who didn't build this thing. You score what
works and what bored you. You name the strongest line. You decide whether
you'd keep reading. You're nice but honest."""


class PersonaReviewerAgent(BasicAgent):
    def __init__(self):
        self.name = "Reviewer"
        self.metadata = {
            "name": self.name,
            "description": "The Reviewer persona. Reads cold, scores 1-5, names strongest line.",
            "parameters": {"type": "object",
                "properties": {"input": {"type": "string", "description": "Final content"}},
                "required": ["input"]},
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, input="", **kwargs):
        return _llm_call(SOUL,
            f"Final content:\n{input}\n\nIn 3 short bullets:\n"
            "(1) score 1-5\n(2) strongest line in the piece\n"
            "(3) would you keep reading the next chapter? Why or why not?")


def _llm_call(soul, user_prompt):
    msgs = [{"role": "system", "content": soul}, {"role": "user", "content": user_prompt}]
    ep, key = os.environ.get("AZURE_OPENAI_ENDPOINT", ""), os.environ.get("AZURE_OPENAI_API_KEY", "")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "")
    if ep and key:
        url = ep if "/chat/completions" in ep else ep.rstrip("/") + f"/openai/deployments/{dep}/chat/completions?api-version=2025-01-01-preview"
        if "/chat/completions" in ep and "/openai/v1/" not in ep and "?" not in url:
            url += "?api-version=2025-01-01-preview"
        return _post(url, {"messages": msgs, "model": dep},
                      {"Content-Type": "application/json", "api-key": key})
    if os.environ.get("OPENAI_API_KEY"):
        return _post("https://api.openai.com/v1/chat/completions",
                      {"model": os.environ.get("OPENAI_MODEL", "gpt-4o"), "messages": msgs},
                      {"Content-Type": "application/json",
                       "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
    return "(no LLM configured)"


def _post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode("utf-8"))
        c = j.get("choices") or []
        return (c[0]["message"].get("content") or "") if c else ""
    except urllib.error.HTTPError as e:
        return f"(LLM HTTP {e.code}: {e.read().decode('utf-8')[:200]})"
    except urllib.error.URLError as e:
        return f"(LLM network error: {e})"
