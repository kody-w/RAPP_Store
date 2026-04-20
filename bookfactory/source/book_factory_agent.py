"""
book_factory_agent.py — top-level composite for the digital twin book factory.

Direct-imports each persona agent.py and runs them in order. No pipeline DSL,
no orchestrator endpoint, no special step kinds. Just one agent.py whose
perform() does Python function calls on other agent.py files.

Run via the sacred OG path:
    POST /api/swarm/{guid}/agent  {"name":"BookFactory","args":{...}}

Returns the final chapter as a string. Also writes intermediate artifacts
to a workspace dir so .egg snapshots can capture the in-flight state.

Inputs:
    source       — raw source material (a string)
    chapter_title — working title for the chapter
    workspace    — optional dir to drop artifacts in (default: $TWIN_WORKSPACE/book or /tmp/book-factory)

Returns:
    The final chapter markdown.
"""
from agents.basic_agent import BasicAgent
from agents.persona_writer_agent    import PersonaWriterAgent
from agents.persona_editor_agent    import PersonaEditorAgent
from agents.persona_ceo_agent       import PersonaCEOAgent
from agents.persona_publisher_agent import PersonaPublisherAgent
from agents.persona_reviewer_agent  import PersonaReviewerAgent
import os


__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@rapp/book-factory",
    "tier": "core",
    "trust": "community",
    "version": "0.1.0",
    "tags": ["composite", "creative-pipeline", "twin-stack"],
    "delegates_to": [
        "@rapp/persona-writer",
        "@rapp/persona-editor",
        "@rapp/persona-ceo",
        "@rapp/persona-publisher",
        "@rapp/persona-reviewer",
    ],
    "example_call": {"args": {"source": "raw notes...", "chapter_title": "Chapter 1"}},
}


class BookFactoryAgent(BasicAgent):
    def __init__(self):
        self.name = "BookFactory"
        self.metadata = {
            "name": self.name,
            "description": "Five-persona content pipeline. Source → Writer → Editor → "
                           "CEO → Publisher → Reviewer. Returns the final chapter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source":        {"type": "string", "description": "Raw source material"},
                    "chapter_title": {"type": "string", "description": "Working title"},
                    "author":        {"type": "string", "description": "Author byline"},
                    "workspace":     {"type": "string", "description": "Dir for intermediate artifacts"},
                },
                "required": ["source"],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, source="", chapter_title="Untitled chapter",
                author="@rapp", workspace=None, **kwargs):
        ws = workspace or os.environ.get("TWIN_WORKSPACE") or "/tmp/book-factory"
        os.makedirs(ws, exist_ok=True)

        def save(name, content):
            path = os.path.join(ws, name)
            with open(path, "w") as f:
                f.write(content if isinstance(content, str) else str(content))
            return path

        save("00-source.md", source)

        # 1. Writer
        draft = PersonaWriterAgent().perform(input=source, chapter_title=chapter_title)
        save("01-draft.md", draft)

        # 2. Editor (composite — calls cutweak + factcheck + voicecheck)
        edited = PersonaEditorAgent().perform(input=draft)
        save("02-edited.md", edited)

        # 3. CEO (composite — calls risk + decision)
        ceo_note = PersonaCEOAgent().perform(input=edited)
        save("03-ceo-note.md", ceo_note)

        # 4. Publisher
        final = PersonaPublisherAgent().perform(input=edited, ceo_note=ceo_note,
                                                  title=chapter_title, author=author)
        save("04-final-chapter.md", final)

        # 5. Reviewer (read it cold)
        review = PersonaReviewerAgent().perform(input=final)
        save("05-review.md", review)

        # Summary header + the final chapter (the artifact the caller wants)
        return (
            f"Book factory complete. Workspace: {ws}\n"
            f"---\n"
            f"FINAL CHAPTER:\n\n{final}\n"
            f"---\n"
            f"REVIEWER:\n\n{review}\n"
        )
