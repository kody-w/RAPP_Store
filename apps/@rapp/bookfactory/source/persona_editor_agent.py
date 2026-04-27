"""
persona_editor_agent.py — Editor persona, composite of FIVE specialist agents.

v0.3.0: added strip_scaffolding (catches `## Outline` artifacts the Writer
left in) and restructure (consolidates repetitive middle sections). Composite
runs in order: strip → cut → restructure, then runs factcheck and voicecheck
in parallel-style for the editor's note. cutweak now preserves fenced code.

Each specialist is its own portable agent.py with its own inlined LLM call.
Editor's perform() direct-imports them and runs each in sequence, then
composes the final output.

Sacred all the way down: this file is a single agent.py, but its perform()
delegates to other agent.py files. Cat any one of them to read the unit.
"""
from agents.basic_agent import BasicAgent
from agents.editor_strip_scaffolding_agent import EditorStripScaffoldingAgent
from agents.editor_cutweak_agent           import EditorCutweakAgent
from agents.editor_restructure_agent       import EditorRestructureAgent
from agents.editor_factcheck_agent         import EditorFactcheckAgent
from agents.editor_voicecheck_agent        import EditorVoicecheckAgent


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/persona-editor",
    "tier": "core",
    "trust": "community",
    "version": "0.3.0",
    "tags": ["persona", "creative-pipeline", "composite"],
    "delegates_to": [
        "@rapp/editor-strip-scaffolding",
        "@rapp/editor-cutweak",
        "@rapp/editor-restructure",
        "@rapp/editor-factcheck",
        "@rapp/editor-voicecheck",
    ],
    "example_call": {"args": {"input": "draft text"}},
}


class PersonaEditorAgent(BasicAgent):
    def __init__(self):
        self.name = "Editor"
        self.metadata = {
            "name": self.name,
            "description": "The Editor persona. Strips scaffolding → cuts weak prose "
                           "(preserving code) → restructures repetitive middles, then "
                           "runs factcheck + voicecheck for the editor's note.",
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Writer's draft"}},
                "required": ["input"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, input="", **kwargs):
        # Sequential transformations on the prose itself
        stripped     = EditorStripScaffoldingAgent().perform(input=input)
        cut          = EditorCutweakAgent().perform(input=stripped)
        restructured = EditorRestructureAgent().perform(input=cut)

        # Parallel-in-spirit checks against the original draft (so the
        # checks see what was claimed before any cutting happened)
        facts = EditorFactcheckAgent().perform(input=input)
        voice = EditorVoicecheckAgent().perform(input=input)

        return (
            f"{restructured}\n"
            f"---\n"
            f"**Editor's note**\n\n"
            f"_Sourcing flags:_\n{facts}\n\n"
            f"_Voice drift:_\n{voice}\n"
        )
