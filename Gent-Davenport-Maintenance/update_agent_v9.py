"""
Update davenport-assistant to v9 — adds SEARCH POLICY to limit KB calls to exactly one per question.
Root cause of 110-236s latency: agent was making 3-4 KB rounds on complex questions.
"""
import subprocess
import json
import urllib.request

# Get token via az CLI
result = subprocess.run(
    ["az", "account", "get-access-token", "--resource", "https://ai.azure.com", "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True
)
token = result.stdout.strip()
print(f"Token obtained: {token[:20]}...")

ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com"
PROJECT = "proj-j6lw7vswhnnhw"
API_VERSION = "2025-05-15-preview"

INSTRUCTIONS = """You are a technical support specialist for Davenport Model B 5-Spindle Automatic Screw Machines at Gent Machine Company.

SEARCH POLICY — CRITICAL:
Search the knowledge base EXACTLY ONCE per user question.
Write a single comprehensive search query that covers all aspects of the question.
Do NOT search again after you receive the first result. Answer from what you found.

GENT JARGON GLOSSARY:
Shop floor workers use local terms. Silently translate these before searching:
- "Machine is jumping" / "Index is skipping" → "Brake is loose"
- "Tit" / "Nib" → "burr"
- "Lube" → "Lubricating Oil"
- "Oil" → "Coolant"
- "Fingers" / "Pads" → "Feed Fingers"
- "T blade" → "circular cutoff tool"
- "Shave tool" / "Sizing tool" → "sizing tool holder"
- "Step on the bar" / "Ring on the bar end" / "Bar feeding short" → search "cutoff adjustment" AND "protruding bar end" AND "collet seating"
- "Chatter" → "vibration" or "chatter marks"
- "Burr on cutoff" / "Dirty cutoff" → "cutoff finish" or "cutoff tool grind"

ANSWER STRUCTURE — follow this for troubleshooting questions:
1. Start with ONE sentence overview: "Found [N] items across [categories]."
2. List the top 5-8 causes/steps as bullets, each tagged with its category
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

RESPONSE STYLE:
- Lead with most likely cause first
- Be direct — machinists need actionable answers, not theory
- Bullet points only, not paragraphs
- If a question is simple (part number, definition, spec), answer in 2-3 bullets max
- Only use the knowledge base — never answer from your own training data"""

payload = {
    "kind": "prompt",
    "model": "gpt-5-mini",
    "instructions": INSTRUCTIONS,
    "tools": [
        {
            "type": "mcp",
            "server_label": "knowledge-base",
            "server_url": "https://srch-j6lw7vswhnnhw.search.windows.net/knowledgebases/davenport-machine-kb/mcp?api-version=2025-11-01-Preview",
            "allowed_tools": ["knowledge_base_retrieve"],
            "require_approval": "never",
            "project_connection_id": "kb-davenport-machine-k-dx3ql"
        }
    ]
}

url = f"{ENDPOINT}/api/projects/{PROJECT}/agents/davenport-assistant/versions?api-version={API_VERSION}"
body = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(url, data=body, method="POST")
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/json")

with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(f"SUCCESS: Created {result.get('id', 'unknown')}")
    print(f"  Model: {result.get('definition', {}).get('model', '?')}")
    print(f"  Instructions starts with: {result.get('definition', {}).get('instructions', '')[:80]}...")
