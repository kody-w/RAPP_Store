"""TLDR — the same response, compressed to one sentence.

A sense that translates the main reply into a single declarative
sentence. For UIs that show a one-line preview, mobile shells with
limited screen real estate, or anywhere "what's the point of this
answer" matters more than the answer itself.

Install: drop in rapp_brainstem/senses/. Restart not required.
"""

name = "tldr"
delimiter = "|||TLDR|||"
response_key = "tldr_response"
wrapper_tag = "tldr"
system_prompt = (
    "After your main reply, append `|||TLDR|||` followed by exactly one "
    "sentence that captures the load-bearing point of your answer. No "
    "preamble, no list, no qualifier (\"basically\", \"in short\", "
    "\"essentially\" — none of these). One sentence, period. The sentence "
    "is the answer's spine — what survives if everything else is cut. "
    "Always emit — empty is not allowed."
)
