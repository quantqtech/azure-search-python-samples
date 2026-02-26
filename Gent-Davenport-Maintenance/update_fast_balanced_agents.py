"""
Update davenport-fast and davenport-balanced agents to v3.
Points them to the fixed Knowledge Bases with correct MCP config.
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
MODEL = "gpt-5-mini"

AGENT_INSTRUCTIONS = """You are a technical support specialist for Davenport Model B 5-Spindle Automatic Screw Machines at Gent Machine Company.

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
- Only use the knowledge base — never answer from your own training data
"""


def main():
    print("Updating Fast and Balanced agents to v3...")
    print("=" * 50)

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    # Agent configs: (name, mcp_connection, kb_name)
    agents_config = [
        ("davenport-fast", "kb-minimal-connection", "davenport-kb-minimal"),
        ("davenport-balanced", "kb-low-connection", "davenport-kb-low"),
    ]

    for agent_name, mcp_connection, kb_name in agents_config:
        mcp_endpoint = f"{SEARCH_ENDPOINT}/knowledgebases/{kb_name}/mcp?api-version=2025-11-01-Preview"

        mcp_tool = MCPTool(
            server_label="knowledge-base",
            server_url=mcp_endpoint,
            require_approval="never",
            allowed_tools=["knowledge_base_retrieve"],
            project_connection_id=mcp_connection
        )

        agent = project_client.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(
                model=MODEL,
                instructions=AGENT_INSTRUCTIONS,
                tools=[mcp_tool]
            )
        )
        print(f"[OK] {agent_name} updated to v{agent.version}")
        print(f"     Using KB: {kb_name}")
        print(f"     MCP connection: {mcp_connection}")

    print("\n" + "=" * 50)
    print("Agents updated! Test Fast and Balanced modes now.")


if __name__ == "__main__":
    main()
