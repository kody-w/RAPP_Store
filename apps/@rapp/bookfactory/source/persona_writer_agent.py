"""
persona_writer_agent.py — the Writer persona, as a single sacred agent.py.

Drop this one file into any RAPP brainstem's agents/ directory and it works.
No sibling imports. The LLM call helper is inlined so this file is the
complete unit of share, version, audit, and trust.

Reads AZURE_OPENAI_* (or OPENAI_API_KEY) from the process environment.
"""
from agents.basic_agent import BasicAgent
import json
import os
import urllib.request
import urllib.error


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/persona-writer",
    "tier": "core",
    "trust": "community",
    "version": "0.1.0",
    "tags": ["persona", "creative-pipeline"],
    "example_call": {"args": {"input": "raw notes", "chapter_title": "Chapter 1"}},
}


SOUL = """You are a senior nonfiction writer. You take raw source material and turn it
into prose that respects the reader's time. You favor concrete examples over
abstractions. You write in scenes, not summaries. You never pad. If the source
has gaps, you say so rather than fabricate.

CRITICAL for technical writing: when the source material contains code blocks
(text inside ```...``` fences) or specific filenames, function names, or API
shapes, INCLUDE THEM VERBATIM in your draft. Code is evidence. A claim about
how a system works lands twice as hard when the reader can see the actual
function being discussed. Use 1-3 fenced code blocks per draft when source
material supports it. Quote real filenames (`agents/foo_agent.py`) and real
identifiers (`run_pipeline`) instead of paraphrasing them.

You also output clean publishable prose — no '## Outline' scaffolding at the
top, no 'TODO' placeholders, no draft-state labels. Write as if your draft
will be published as-is."""


class PersonaWriterAgent(BasicAgent):
    def __init__(self):
        self.name = "Writer"
        self.metadata = {
            "name": self.name,
            "description": "The Writer persona. Takes source material, returns chapter-style prose.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Raw source material"},
                    "chapter_title": {"type": "string", "description": "Working title"},
                    "max_words": {"type": "integer", "description": "Word cap (default 800)"},
                },
                "required": ["input"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, input="", chapter_title="Untitled", max_words=800, **kwargs):
        prompt = (
            f"Source material:\n\n--- SOURCE ---\n{input}\n--- END ---\n\n"
            f"Outline a chapter titled '{chapter_title}'. Then draft it. Lead with one "
            f"concrete scene from the source. Plain prose. Single H1. Under {max_words} words. "
            f"Sign off as @writer."
        )
        return _llm_call(SOUL, prompt)


# ─── LLM dispatch — delegates to utils.llm shim ────────────────────────
# Tier 1 (brainstem) registers a Copilot session getter at startup so
# this routes through the same engine that's powering the host process.
# Tier 2 (swarm) vendors the same utils/llm.py and falls through to
# AZURE_OPENAI_* / OPENAI_API_KEY / Anthropic. No per-rapp LLM config.

def _llm_call(soul: str, user_prompt: str) -> str:
    messages = [{"role": "system", "content": soul},
                {"role": "user", "content": user_prompt}]
    try:
        from utils.llm import call_llm
        return call_llm(messages)
    except Exception as e:
        return f"(LLM dispatch error: {e})"


def _post(*args, **kwargs):
    # Retained as a no-op for build.py, which extracts _llm_call AND
    # _post from this file as the canonical singleton helpers. The
    # singleton no longer needs _post (utils.llm owns all HTTP), but
    # keeping a stub avoids touching the build script in this change.
    return ""
