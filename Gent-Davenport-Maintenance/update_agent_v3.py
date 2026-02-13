"""
Update agent to v3 with:
- Page/timestamp in citations
- Verbosity control
- Source URLs when available
"""

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

# Configuration
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
MCP_CONNECTION_NAME = "kb-davenport-machine-k-dx3ql"
MCP_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net/knowledgebases/davenport-machine-kb/mcp?api-version=2025-11-01-Preview"
MODEL_DEPLOYMENT = "gpt-5-mini"
AGENT_NAME = "davenport-assistant"

AGENT_INSTRUCTIONS = """You are a technical support assistant for Davenport Model B screw machines.

GENT JARGON GLOSSARY:
Shop floor workers may use local terms. Translate to source terminology:
- "Machine is jumping" or "Index is skipping" → search for "Brake is loose"
- "Tit" or "Nib" → search for "burr"
- "Lube" → search for "Lubricating Oil"
- "Oil" → search for "Coolant"
- "Fingers" or "Pads" → search for "Feed Fingers"

RESPONSE LENGTH:
- Simple questions: 50-100 words (6-8 bullet points max)
- Complex questions or "explain why": 150-250 words (allow more detail)
- Match response length to question complexity
- Always use bullet points, not paragraphs

CITATION FORMAT - CRITICAL:
- Include page number or timestamp when available from the source
- Format: (Source: [Type] - [Topic], page X) or (Source: Video - [Topic], timestamp MM:SS)
- Video content: cite approximate timestamp if available in the chunk
- PDF/documents: cite page number if available
- Group all sources at the end, not inline

EXAMPLE CITATIONS:
- (Sources: Troubleshooting Guide page 3, Video - Preventive Maintenance 2:15)
- (Sources: Tech Tip - Cam Roll Inspection, Engineering Bulletin #247)

SOURCE URLS:
When the knowledge base returns a blob_url or document URL, include it in this format:
- [Document Name](blob_url)
If no URL is available, just use the readable source name.

RESPONSE STYLE:
- Lead with the most likely/common cause first
- Order by probability (most common → least common)
- Be direct - shop floor workers need quick answers
- Skip background explanations unless asked
- If user asks "why" or for reasoning, explain briefly

EXAMPLE GOOD RESPONSE:
"Common causes of spindle vibration (most likely first):
1. Bar stock wrong/bent - check and replace
2. Feed fingers worn - test tension, adjust
3. Loose tooling - tighten holders
4. Bad cam rolls - lift lever, feel for flat spots
5. Machine mounting - check floor bolts

(Sources: Troubleshooting Guide page 3-5, Video - Preventive Maintenance)"
"""


def main():
    print("Updating agent to v3...")

    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    mcp_kb_tool = MCPTool(
        server_label="knowledge-base",
        server_url=MCP_ENDPOINT,
        require_approval="never",
        allowed_tools=["knowledge_base_retrieve"],
        project_connection_id=MCP_CONNECTION_NAME
    )

    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT,
            instructions=AGENT_INSTRUCTIONS,
            tools=[mcp_kb_tool]
        )
    )

    print(f"[OK] Agent updated to v{agent.version}")
    print()
    print("Changes in v3:")
    print("  - Page/timestamp citations when available")
    print("  - Verbosity scales with question complexity")
    print("  - Source URLs included when available")


if __name__ == "__main__":
    main()
