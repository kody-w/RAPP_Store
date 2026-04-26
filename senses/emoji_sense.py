"""EMOJI — the same response, as an emoji sequence.

A sense that translates the main reply into a sequence of emoji that
tells the same story. Frontends with chat-bubble UIs render this above
or alongside the prose; teaches accessibility tools an at-a-glance
summary; works as a tone fingerprint for the response.

Install: drop in rapp_brainstem/senses/. Restart not required.
"""

name = "emoji"
delimiter = "|||EMOJI|||"
response_key = "emoji_response"
wrapper_tag = "emoji"
system_prompt = (
    "After your main reply, append `|||EMOJI|||` followed by 3-7 emoji "
    "that together tell the same story as your answer. Read left-to-right "
    "as a tiny narrative or as a thematic chord. No spaces between emoji, "
    "no commentary, no text — just the emoji. The sequence is a "
    "TRANSLATION of the answer into pictographic form. Always emit — "
    "if the answer is purely abstract, pick emoji that capture its mood "
    "or shape."
)
