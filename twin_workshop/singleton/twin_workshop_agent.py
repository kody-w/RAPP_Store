"""
twin_workshop_agent.py — TwinWorkshop singleton.

The 60-minute personal-twin workshop, performed by the platform on itself,
with the customer in the room. Sixty minutes. They leave with the artifact.
The artifact runs everywhere.

Stages:
  1. INTAKE      — capture what the user wants to delegate (free-form)
  2. CLARIFY     — turn the description into a tight task contract
  3. DESIGN      — generate the agent.py source (single-file BasicAgent)
  4. VALIDATE    — run the generated agent against user-provided test input
  5. SHIP        — return the .py for download / AirDrop

Drop this file into any RAPP brainstem's agents/ directory and it works.
The companion index.html (rapp_store/twin_workshop/ui/index.html) is the
iframe-mounted UI that walks a user through the five stages. Both ship as
rapplication.egg via the standard binder import/export path.

Each stage is a single LLM call with its own SOUL (system prompt). The
top-level TwinWorkshop class is the only public entrypoint; the per-stage
classes are prefixed _Internal so they stay out of the brainstem's *Agent
auto-discovery — only TwinWorkshop appears in the LLM's tool list.
"""
from agents.basic_agent import BasicAgent
import json
import os
import re
import urllib.request
import urllib.error


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/twin-workshop-singleton",
    "display_name": "TwinWorkshop",
    "version": "0.1.0",
    "description": "Workshop a personal twin in 60 minutes. Asks what to delegate, designs the agent in front of the user, validates against test input, hands them the file.",
    "tags": ["composite", "killer-app", "swarm-factory-generated", "rapplication"],
    "category": "creative-pipeline",
    "delegates_to_inlined": [
        "@rapp/twin-intake",
        "@rapp/twin-clarify",
        "@rapp/twin-designer",
        "@rapp/twin-validator",
        "@rapp/twin-shipper",
    ],
    "example_call": {"args": {"stage": "design", "task_contract": "..."}},
}


# ─── Persona SOULs ─────────────────────────────────────────────────────

_SOUL_INTAKE = (
    "You are an intake interviewer for a personal-twin workshop. The user "
    "tells you, in their own words, something they want to delegate to an "
    "AI agent. Your job: turn their description into a structured intake "
    "summary. Return JSON only, with these keys:\n"
    "  goal: one-sentence statement of what the agent should accomplish\n"
    "  inputs: list of inputs the agent will receive (each: name + description)\n"
    "  outputs: what the agent returns (one sentence)\n"
    "  followup_questions: 2-4 short questions to ask the user that would\n"
    "                      sharpen the contract. Empty list if none.\n"
    "Be tight. No prose outside the JSON. If the user's description is "
    "vague, the followup_questions field is where you get specific — don't "
    "guess inputs/outputs; ask."
)

_SOUL_CLARIFY = (
    "You are a contract sharpener. You receive an intake summary plus the "
    "user's answers to the followup questions. Your job: produce a tight "
    "task contract the designer can build from. Return JSON only:\n"
    "  task_name: PascalCase, 1-3 words, what to call the agent\n"
    "  task_description: one sentence the LLM tool catalog will display\n"
    "  inputs: list of {name, type, description, required}\n"
    "  output_shape: one-paragraph description of what the agent returns\n"
    "  acceptance_criteria: 2-5 short bullets describing what 'works' looks like\n"
    "No prose outside the JSON. If the user's answers contradict the "
    "intake, the contract reflects the LATEST answer."
)

_SOUL_DESIGNER = (
    "You are a Python agent designer. You receive a task contract and write "
    "a SINGLE FILE Python agent that satisfies it. The agent must:\n"
    "  - import: from agents.basic_agent import BasicAgent\n"
    "  - define a __manifest__ dict with schema, name, display_name, description\n"
    "  - define ONE class <TaskName>Agent(BasicAgent) with __init__ + perform\n"
    "  - perform(**kwargs) returns json.dumps({...}) — never raw text\n"
    "  - inputs come in as kwargs.get('input_name', default)\n"
    "  - graceful handling of missing inputs (return error JSON, don't raise)\n"
    "Output ONLY the Python source — no markdown fences, no commentary. The "
    "user is going to install this file directly into their brainstem's "
    "agents/ directory; ANY non-code text breaks the install."
)

_SOUL_VALIDATOR = (
    "You are a behavioral validator. You receive an agent's source code, "
    "the task contract, and a test input the user provided. You mentally "
    "execute the agent against the test input and report whether the output "
    "would satisfy the acceptance criteria. Return JSON only:\n"
    "  pass: true|false\n"
    "  predicted_output: what you think the agent returns for this input\n"
    "  reasoning: 2-4 sentence explanation\n"
    "  suggested_fixes: list of short bullets if pass=false; empty if pass=true\n"
    "Mental execution, not real execution — be honest if the agent calls an\n"
    "external API you can't predict. Mark pass=true only if the OUTPUT SHAPE\n"
    "and CORE BEHAVIOR clearly satisfy the contract for this specific input."
)


# ─── Inlined LLM dispatch ─────────────────────────────────────────────

def _llm_call(soul, user_prompt, timeout=120):
    """Call the configured LLM with this soul + user prompt. Tries Azure,
    then OpenAI. Returns the assistant content string. Returns the literal
    string '(no LLM configured)' if neither is available — the caller's
    job to surface that, since it's the user's only signal that they need
    to set env vars."""
    msgs = [{"role": "system", "content": soul},
            {"role": "user", "content": user_prompt}]

    ep = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    dep = os.environ.get("AZURE_OPENAI_DEPLOYMENT") \
          or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "")
    if ep and key:
        url = ep if "/chat/completions" in ep \
              else ep.rstrip("/") + f"/openai/deployments/{dep}/chat/completions?api-version=2025-01-01-preview"
        if "/chat/completions" in ep and "?" not in url:
            url += "?api-version=2025-01-01-preview"
        return _post(url, {"messages": msgs, "model": dep},
                      {"Content-Type": "application/json", "api-key": key},
                      timeout)
    if os.environ.get("OPENAI_API_KEY"):
        return _post("https://api.openai.com/v1/chat/completions",
                      {"model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
                       "messages": msgs},
                      {"Content-Type": "application/json",
                       "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]},
                      timeout)
    return "(no LLM configured)"


def _post(url, body, headers, timeout=120):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8"))
        c = j.get("choices") or []
        return (c[0]["message"].get("content") or "") if c else ""
    except urllib.error.HTTPError as e:
        return f"(LLM HTTP {e.code}: {e.read().decode('utf-8')[:200]})"
    except urllib.error.URLError as e:
        return f"(LLM network error: {e})"


# ─── Helpers shared across personas ───────────────────────────────────

def _strip_code_fences(s):
    """LLMs love wrapping code in ```python ...``` even when told not to.
    Strip the most common fence shapes so the file we write is pure code."""
    s = s.strip()
    m = re.match(r"^```(?:python|py)?\s*\n(.*?)```\s*$", s, re.DOTALL)
    if m:
        return m.group(1).strip()
    return s


def _safe_json_parse(s, default=None):
    """LLMs sometimes return JSON wrapped in commentary. Try the straight
    parse first, then look for the first {...} block. Returns default on
    total failure so the caller can show a graceful error."""
    s = s.strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return default


# ─── Internal personas (one per stage) ────────────────────────────────

class _InternalIntake:
    def perform(self, description):
        raw = _llm_call(_SOUL_INTAKE, description.strip())
        parsed = _safe_json_parse(raw, {})
        if not parsed:
            return {"error": "intake LLM returned non-JSON",
                    "raw": raw[:500]}
        return parsed


class _InternalClarify:
    def perform(self, intake_summary, user_answers):
        prompt = (
            "Intake summary:\n" + json.dumps(intake_summary, indent=2)
            + "\n\nUser answers to followup questions:\n"
            + json.dumps(user_answers, indent=2)
            + "\n\nProduce the task contract."
        )
        raw = _llm_call(_SOUL_CLARIFY, prompt)
        parsed = _safe_json_parse(raw, {})
        if not parsed:
            return {"error": "clarify LLM returned non-JSON",
                    "raw": raw[:500]}
        return parsed


class _InternalDesigner:
    def perform(self, task_contract):
        prompt = (
            "Task contract:\n" + json.dumps(task_contract, indent=2)
            + "\n\nWrite the agent.py source. Output ONLY Python code."
        )
        raw = _llm_call(_SOUL_DESIGNER, prompt, timeout=180)
        code = _strip_code_fences(raw)
        # Sanity check: must parse as Python and define a class with perform
        import ast
        try:
            tree = ast.parse(code)
            classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
            has_perform = any(
                isinstance(m, ast.FunctionDef) and m.name == "perform"
                for c in classes for m in c.body
            )
            if not classes or not has_perform:
                return {"error": "generated code missing class with perform()",
                        "code": code}
        except SyntaxError as e:
            return {"error": f"generated code has SyntaxError on line {e.lineno}: {e.msg}",
                    "code": code}
        # Suggest a filename based on the task name
        task_name = (task_contract.get("task_name") or "MyAgent").strip()
        slug = re.sub(r"[^a-z0-9]", "", task_name.lower()) or "myagent"
        return {
            "code": code,
            "filename": f"{slug}_agent.py",
            "task_name": task_name,
            "lines": code.count("\n") + 1,
            "bytes": len(code),
        }


class _InternalValidator:
    def perform(self, code, task_contract, test_input):
        prompt = (
            "Task contract:\n" + json.dumps(task_contract, indent=2)
            + "\n\nGenerated agent code:\n```python\n" + code + "\n```"
            + "\n\nTest input the user provided:\n"
            + json.dumps(test_input, indent=2)
            + "\n\nValidate."
        )
        raw = _llm_call(_SOUL_VALIDATOR, prompt)
        parsed = _safe_json_parse(raw, {})
        if not parsed:
            return {"error": "validator LLM returned non-JSON",
                    "raw": raw[:500]}
        return parsed


class _InternalShipper:
    """The shipper isn't an LLM call — it just packages the artifact for
    delivery (write the .py to the user's agents dir AND return the source
    so the UI can offer it as a download / AirDrop / paste-into-someone-
    else's-brainstem). Every workshop ends with a tangible artifact."""
    def perform(self, code, filename, also_install=False):
        result = {
            "code": code,
            "filename": filename,
            "bytes": len(code),
        }
        if also_install:
            agents_dir = os.environ.get(
                "AGENTS_PATH",
                os.path.join(os.path.dirname(os.path.abspath(__file__))))
            os.makedirs(agents_dir, exist_ok=True)
            dest = os.path.join(agents_dir, filename)
            try:
                with open(dest, "w") as f:
                    f.write(code)
                result["installed_to"] = dest
            except Exception as e:
                result["install_error"] = str(e)
        return result


# ─── PUBLIC ENTRYPOINT ────────────────────────────────────────────────

class TwinWorkshopAgent(BasicAgent):
    def __init__(self):
        self.name = "TwinWorkshop"
        self.metadata = {
            "name": self.name,
            "description": (
                "60-minute personal-twin workshop, performed by the platform on "
                "itself. Stages: intake (capture what to delegate), clarify "
                "(sharpen the contract), design (write the agent), validate "
                "(check against user's test input), ship (return the .py). "
                "The UI walks the user through stage-by-stage; this agent can "
                "also be called direct with stage='<name>' to drive a single "
                "stage from a chat tool call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "enum": ["intake", "clarify", "design", "validate", "ship", "full"],
                        "description": "Which stage to run. 'full' runs the whole pipeline (intake → clarify → design) when description + answers are both supplied."
                    },
                    "description": {
                        "type": "string",
                        "description": "For intake/full: free-form description of what the user wants to delegate."
                    },
                    "intake_summary": {
                        "type": "object",
                        "description": "For clarify: the JSON intake summary from a prior intake stage."
                    },
                    "user_answers": {
                        "type": "object",
                        "description": "For clarify/full: a {question: answer} map for the followup_questions."
                    },
                    "task_contract": {
                        "type": "object",
                        "description": "For design/validate: the JSON task contract from a prior clarify stage."
                    },
                    "code": {
                        "type": "string",
                        "description": "For validate/ship: the generated agent source code."
                    },
                    "test_input": {
                        "type": "object",
                        "description": "For validate: a {input_name: value} map of test inputs the user supplied."
                    },
                    "filename": {
                        "type": "string",
                        "description": "For ship: the filename to write (defaults to <slug>_agent.py)."
                    },
                    "also_install": {
                        "type": "boolean",
                        "description": "For ship: if true, ALSO write the file into the brainstem's agents/ dir so it hot-loads."
                    }
                },
                "required": ["stage"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, stage="intake", **kwargs):
        try:
            if stage == "intake":
                desc = kwargs.get("description", "")
                if not desc:
                    return json.dumps({"status": "error",
                        "stage": "intake",
                        "message": "description required for intake."})
                result = _InternalIntake().perform(desc)
                return json.dumps({"status": "ok", "stage": "intake", "result": result})

            if stage == "clarify":
                summary = kwargs.get("intake_summary") or {}
                answers = kwargs.get("user_answers") or {}
                if not summary:
                    return json.dumps({"status": "error",
                        "stage": "clarify",
                        "message": "intake_summary required for clarify."})
                result = _InternalClarify().perform(summary, answers)
                return json.dumps({"status": "ok", "stage": "clarify", "result": result})

            if stage == "design":
                contract = kwargs.get("task_contract") or {}
                if not contract:
                    return json.dumps({"status": "error",
                        "stage": "design",
                        "message": "task_contract required for design."})
                result = _InternalDesigner().perform(contract)
                return json.dumps({"status": "ok", "stage": "design", "result": result})

            if stage == "validate":
                code = kwargs.get("code", "")
                contract = kwargs.get("task_contract") or {}
                test_input = kwargs.get("test_input") or {}
                if not code or not contract:
                    return json.dumps({"status": "error",
                        "stage": "validate",
                        "message": "code and task_contract required for validate."})
                result = _InternalValidator().perform(code, contract, test_input)
                return json.dumps({"status": "ok", "stage": "validate", "result": result})

            if stage == "ship":
                code = kwargs.get("code", "")
                filename = kwargs.get("filename", "myagent_agent.py")
                also_install = bool(kwargs.get("also_install"))
                if not code:
                    return json.dumps({"status": "error",
                        "stage": "ship",
                        "message": "code required for ship."})
                result = _InternalShipper().perform(code, filename, also_install)
                return json.dumps({"status": "ok", "stage": "ship", "result": result})

            if stage == "full":
                # Convenience: intake → clarify → design in one call. Used
                # by the chat-tool path where the LLM has all the inputs
                # in one shot. The UI usually drives stage-by-stage.
                desc = kwargs.get("description", "")
                answers = kwargs.get("user_answers") or {}
                if not desc:
                    return json.dumps({"status": "error",
                        "stage": "full",
                        "message": "description required for full pipeline."})
                summary = _InternalIntake().perform(desc)
                contract = _InternalClarify().perform(summary, answers)
                designed = _InternalDesigner().perform(contract)
                return json.dumps({"status": "ok", "stage": "full",
                    "intake": summary, "contract": contract, "design": designed})

            return json.dumps({"status": "error",
                "message": f"unknown stage '{stage}' — must be one of intake|clarify|design|validate|ship|full"})

        except Exception as e:
            return json.dumps({"status": "error", "stage": stage,
                "message": f"{type(e).__name__}: {e}"})


# Some catalog entries probe TwinWorkshop too — alias for compatibility
class TwinWorkshop(TwinWorkshopAgent):
    pass
