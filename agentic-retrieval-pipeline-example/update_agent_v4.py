"""
Update all agents to v4 with inline citations.
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
MODEL = "gpt-5-mini"

# Agent configs: (name, mcp_connection, kb_name)
AGENTS = [
    ("davenport-assistant", "kb-davenport-machine-k-dx3ql", "davenport-machine-kb"),
    ("davenport-fast", "kb-minimal-connection", "davenport-kb-minimal"),
    ("davenport-balanced", "kb-low-connection", "davenport-kb-low"),
]

AGENT_INSTRUCTIONS = """You are a technical support assistant for Davenport Model B screw machines.

GENT JARGON GLOSSARY:
Shop floor workers may use local terms. Translate to source terminology:
- "Machine is jumping" or "Index is skipping" → search for "Brake is loose"
- "Tit" or "Nib" → search for "burr"
- "Lube" → search for "Lubricating Oil"
- "Oil" → search for "Coolant"
- "Fingers" or "Pads" → search for "Feed Fingers"

RESPONSE STYLE:
- Use bullet points, be concise
- Lead with most likely cause first
- Shop floor workers need quick answers

CITATION FORMAT - CRITICAL:
- Put citations INLINE after each bullet point, not grouped at the end
- Format: bullet point text ([Source Name](url) page X)
- Include page number or timestamp when available
- Every fact should have its source immediately after it

EXAMPLE GOOD RESPONSE:
"Most likely causes of spindle vibration:
- Bar stock wrong or bent - check and replace ([Troubleshooting Guide](url) page 4)
- Feed fingers worn - test tension, adjust ([Video - Preventive Maintenance](url) 04:14)
- Loose tooling - tighten holders ([Troubleshooting Guide](url) page 4)
- Bad cam rolls - lift lever, feel for flat spots ([Video - Preventive Maintenance](url) 09:49)
- Machine mounting - check floor bolts ([Troubleshooting Guide](url) page 5)"

BAD (don't do this):
"Causes of vibration:
- Bar stock wrong
- Feed fingers worn
- Loose tooling
(Sources: Troubleshooting Guide, Video)"  <-- NO! Don't group at end

RESPONSE LENGTH - KEEP IT SHORT:
- Simple questions: 40-75 words max
- Complex questions: 100-150 words max
- Maximum 5 bullet points per response
- Procedures: max 7 numbered steps
- Skip introductions like "Here are the causes..."
- Skip conclusions like "Let me know if you need more info"
- One sentence per bullet, no fluff
"""


def main():
    print("Updating all agents to v4 with inline citations...")
    print("=" * 50)

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    for agent_name, mcp_connection, kb_name in AGENTS:
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

    print()
    print("Changes in v4:")
    print("  - Inline citations after each bullet point")
    print("  - No more grouped sources at bottom")


if __name__ == "__main__":
    main()
