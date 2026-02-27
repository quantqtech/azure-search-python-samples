"""
Create davenport-direct-v1 — test agent using azure_ai_search direct tool
pointed at the single davenport-kb-unified index.

Run build_unified_index.py first to create the unified index.

This is the speed test. If it runs ~15-20s vs ~85s with MCP,
we then swap all 3 production agents (davenport-fast, davenport-balanced,
davenport-assistant) to this approach.

Run: python create_direct_search_agent.py
"""
import subprocess
import json
import urllib.request

# ── Auth (same az login session as everything else) ───────────────────────────
result = subprocess.run(
    ["az.cmd", "account", "get-access-token", "--resource", "https://ai.azure.com",
     "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True, shell=True
)
token = result.stdout.strip()
print(f"Token: {token[:20]}...")

ENDPOINT    = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com"
PROJECT     = "proj-j6lw7vswhnnhw"
API_VERSION = "2025-05-15-preview"

# ── Search connection — same service, now pointing at unified index ────────────
SEARCH_CONNECTION = (
    "/subscriptions/09d43e37-e7dc-4869-9db4-768d8937df2e"
    "/resourceGroups/rg-gent-foundry-eus2"
    "/providers/Microsoft.CognitiveServices/accounts/aoai-j6lw7vswhnnhw"
    "/projects/proj-j6lw7vswhnnhw/connections/searchConnection"
)

# One tool, one index — the whole point of building davenport-kb-unified
# top=8: enough for a solid 5-bullet answer without drowning the LLM in 6000+ tokens
# v4 returned 6870 tokens and took 24.8s on that step alone — reducing top cuts that directly
SEARCH_TOOLS = [
    {
        "type": "azure_ai_search",
        "azure_ai_search": {
            "indexes": [
                {
                    "project_connection_id": SEARCH_CONNECTION,
                    "index_name": "davenport-kb-unified",
                    "query_type": "simple",  # BM25 — fast, no vector overhead
                    "top": 20                # top param doesn't appear to limit chunks; leaving at 20 as documented intent
                }
            ]
        }
    }
]

# ── Instructions ───────────────────────────────────────────────────────────────
INSTRUCTIONS = """You are a technical support specialist for Davenport Model B 5-Spindle Automatic Screw Machines at Gent Machine Company.

SEARCH POLICY — CRITICAL:
Search EXACTLY ONCE per user question. No exceptions.
Write a single comprehensive search query that covers all aspects of the question.
Do NOT search again after receiving the first result. Answer from what you found.

GENT JARGON GLOSSARY:
Shop floor workers use local terms. Silently translate these before searching:
- "Machine is jumping" / "Index is skipping" -> "Brake is loose"
- "Tit" / "Nib" -> "burr"
- "Lube" -> "Lubricating Oil"
- "Oil" -> "Coolant"
- "Fingers" / "Pads" -> "Feed Fingers"
- "T blade" -> "circular cutoff tool"
- "Shave tool" / "Sizing tool" -> "sizing tool holder"
- "Step on the bar" / "Ring on the bar end" / "Bar feeding short" -> search "cutoff adjustment protruding bar end collet seating"
- "Chatter" -> "vibration" or "chatter marks"
- "Burr on cutoff" / "Dirty cutoff" -> "cutoff finish" or "cutoff tool grind"

ANSWER STRUCTURE — follow this for troubleshooting questions:
1. Start with ONE sentence overview: "Found [N] items across [categories]."
2. List the top 3-5 causes/steps as bullets, each tagged with its category
3. End with: "Ask me to go deeper on [Tooling / Machine / Feeds & Speeds / Work Holding] if needed."

CATEGORY TAGS — include the relevant category after each bullet:
- [Tooling] — tool type, grind angle, sharpness, tip geometry, holder fit
- [Machine] — cam rolls, pins, levers, bearings, gibs, collets, brake
- [Feeds & Speeds] — gear selection, RPM, feed rate
- [Work Holding] — collet tension, feed fingers, chuck
- [Stock/Material] — bar size, straightness, material grade

CITATION FORMAT — CRITICAL:
- Cite INLINE after each bullet, never grouped at the end
- Format: bullet text [Category] ([Source Name](url) page X)
- Video: bullet text [Category] ([Video Name](url) MM:SS)
- Every fact must have a source citation immediately after it
- ALWAYS use [Source Name](url) markdown link format — NEVER output raw https:// URLs

RESPONSE STYLE:
- Lead with most likely cause first
- Be direct — machinists need actionable answers, not theory
- Bullet points only, not paragraphs
- If a question is simple (part number, definition, spec), answer in 2-3 bullets max
- Only use the search results — never answer from your own training data"""

# ── Create the agent ───────────────────────────────────────────────────────────
AGENT_NAME = "davenport-direct-v1"

payload = {
    "definition": {
        "kind": "prompt",
        "model": "gpt-5-mini",
        "instructions": INSTRUCTIONS,
        "tools": SEARCH_TOOLS
    }
}

url  = f"{ENDPOINT}/api/projects/{PROJECT}/agents/{AGENT_NAME}/versions?api-version={API_VERSION}"
body = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(url, data=body, method="POST")
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type",  "application/json")

print(f"\nCreating {AGENT_NAME} with unified index...")

with urllib.request.urlopen(req) as resp:
    result     = json.loads(resp.read())
    version_id = result.get("id", "unknown")
    model      = result.get("definition", {}).get("model", "?")
    tool_count = len(result.get("definition", {}).get("tools", []))
    print(f"\nSUCCESS: Created {version_id}")
    print(f"  Model:      {model}")
    print(f"  Tools:      {tool_count} (1 tool, davenport-kb-unified)")
    print(f"\nTest in Foundry playground:")
    print(f"  Agent:    {AGENT_NAME}")
    print(f"  Question: How do I adjust the brake on a Davenport Model B?")
    print(f"  Expected: ~15-20s (vs ~85s with MCP)")
    print(f"\nIf speed looks good, run update_production_agents.py to swap all 3 agents.")
