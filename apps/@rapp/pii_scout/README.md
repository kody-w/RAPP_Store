# PII Scout

Point it at a folder before you publish. It reports secrets, forbidden file
classes, email addresses, home paths and any names you supply.

```
{"path": "./my-repo", "terms": "acme,globex,my-handle"}
```

## What it will not do

**It never prints the matched value.** Findings are file + count. A leak report
that quotes the secret is a second copy of the leak.

**It does not pretend an empty roster is a clean bill of health.** With no
`terms`, it says so — it checked file classes and universal identifiers, not
your customers.

## Three rules it encodes

- **Refuse by shape, not just content.** A captured browser session carries
  identities, tenant GUIDs and key material that look nothing like a token. You
  cannot pattern-match what you did not know to look for, but you can refuse the
  file class that carries it.
- **Anchor short acronyms.** A three-letter term that fires inside unrelated
  words produces noise, and noise is how a gate gets switched off.
- **Skip base64 for identity matching.** Random base64 contains short names by
  chance. Reporting that as PII trains people to ignore real findings. Secrets
  are still matched everywhere, including inside blobs.

## Pass your own name

A roster covers other people. A private repo is usually full of the owner's own
name and handle, and that is the one everybody forgets.

Apache-2.0.
