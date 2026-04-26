"""HAIKU — the same response, as a 5-7-5 poem.

A sense that translates the main reply into a single haiku. Frontends
that want a "poetic mode" pin haiku_response below the main reply, or
swap it in entirely for a contemplative UI.

Install: drop in rapp_brainstem/senses/. Restart not required.
"""

name = "haiku"
delimiter = "|||HAIKU|||"
response_key = "haiku_response"
wrapper_tag = "haiku"
system_prompt = (
    "After your main reply, append `|||HAIKU|||` followed by a single "
    "haiku that captures the essence of your answer. Strict 5/7/5 "
    "syllable count, three lines, no title, no commentary. The haiku "
    "is a TRANSLATION of the answer into poetic form — same meaning, "
    "different mode. If the answer cannot meaningfully compress to a "
    "haiku, write one about the gap between question and answer instead. "
    "Always emit a haiku — empty is not allowed."
)
