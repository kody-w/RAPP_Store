# SpineDAG — `@rapp/spine-dag-singleton`

> **Map the spine of anything in 30 seconds.**
> Point it at code, an Excel workbook, a JSON/YAML config, or a paragraph of prose — it builds the dependency graph, scores its Spine Health, and renders a Mermaid diagram you can drop into any deck.

A single-file rapplication for the local **RAPP brainstem**. No services, no server, no API keys. Drop the file in your `agents/` folder and ask the brainstem to use the `SpineDAG` tool.

---

## ✨ What it does

| Mode | Trigger | What you get |
|---|---|---|
| `python` | folder containing `*.py` | module-import graph (uses `ast`) |
| `javascript` | folder containing `*.js/.ts/.jsx/.tsx` | import/require graph |
| `excel` | `.xlsx` / `.xlsm` / `.xlsb` file | sheet-to-sheet formula reference graph |
| `json` / `yaml` | `.json` / `.yaml` file | object reference graph (`$ref` aware) |
| `generic-folder` | any other folder | filename-mention graph |
| `text` | inline string `A -> B; B depends on C` | extracted relation graph |
| `auto` | (default) | best-guess from the target |

For every graph it computes:

* **Spine Health 0-100** with bands `Excellent / Healthy / Fragile / Tangled` (penalises cycles, godfiles, orphan-heavy graphs)
* **Top hubs** (most depended-on)
* **Top leaves** (most outgoing)
* **Orphans** (no in, no out — dead code or top entries)
* **Cycles** via Tarjan-style DFS
* **Critical path** — longest acyclic chain
* **Topological layers** via Kahn's algorithm
* A ready-to-paste **Mermaid diagram** with hubs coloured violet and cycle-nodes coloured coral
* An ASCII tree
* A **`<spine-dag-json>...</spine-dag-json>` envelope** any UI can hydrate

The bundled `ui/index.html` renders all of that into a dark-neon dashboard with a clickable **"Why is this the spine?"** LLM follow-up on each hub.

---

## 📦 Files in this rapplication

```
spine_dag/
  singleton/
    spine_dag_agent.py     ← drop into local brainstem agents/
  ui/
    index.html             ← static dashboard, talks to /chat
  manifest.json            ← rapp-application/1.0 manifest
  index_entry.json         ← snippet for rapp_store/index.json
  README.md                ← this file
```

---

## 🚀 Install (local brainstem)

```bash
curl -L -o ~/.brainstem/src/rapp_brainstem/agents/spine_dag_agent.py \
  https://raw.githubusercontent.com/kody-w/rapp_store/main/spine_dag/singleton/spine_dag_agent.py
```

The brainstem hot-loads agents from disk on every `/chat` request, so the new tool is available immediately.

Open the UI:

```bash
curl -L -o spine_dag.html \
  https://raw.githubusercontent.com/kody-w/rapp_store/main/spine_dag/ui/index.html
start spine_dag.html
```

---

## 💬 Example call

```json
{
  "target": "C:\\path\\to\\your\\project",
  "mode": "auto"
}
```

Or in chat: *"Use SpineDAG on `C:\\path\\to\\budget.xlsx`."*

---

## 🧪 Dependencies

* **Python ≥ 3.10**, stdlib only for code/json/folder/text modes
* `openpyxl` (lazy-imported, brainstem auto-pip-installs on first use) for Excel mode
* `pyyaml` (lazy-imported) for YAML mode

---

## 📜 License
BSD-style (same as the rest of RAPP).

## 👤 Publisher
`@rapp`
