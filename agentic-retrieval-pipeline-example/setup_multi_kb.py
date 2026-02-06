"""
Set up multiple Knowledge Bases and Agents for UI toggle.
Creates: KB-minimal, KB-low (KB-medium already exists)
         Agent-fast, Agent-balanced (Agent already exists as thorough)

This script creates BASELINE configurations. Fine-tune these in Azure Portal:
- retrieval_instructions: Guide query decomposition (low/medium only)
- answer_instructions: Guide answer synthesis (low/medium only)
- Description: KB description for the agent

IMPORTANT: Requires AOAI_KEY environment variable for MCP compatibility.
Get key: az cognitiveservices account keys list --name aoai-j6lw7vswhnnhw --resource-group rg-gent-foundry-eus2 --query key1 -o tsv
"""

import os
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    KnowledgeBase,
    KnowledgeRetrievalMinimalReasoningEffort,
    KnowledgeRetrievalLowReasoningEffort,
    KnowledgeRetrievalOutputMode,
    KnowledgeSourceReference,
    KnowledgeBaseAzureOpenAIModel,
    AzureOpenAIVectorizerParameters
)
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool
import requests
from azure.identity import get_bearer_token_provider

# Configuration
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
PROJECT_ENDPOINT = "https://aoai-j6lw7vswhnnhw.services.ai.azure.com/api/projects/proj-j6lw7vswhnnhw"
PROJECT_RESOURCE_ID = "/subscriptions/09d43e37-e7dc-4869-9db4-768d8937df2e/resourceGroups/rg-gent-foundry-eus2/providers/Microsoft.CognitiveServices/accounts/aoai-j6lw7vswhnnhw/projects/proj-j6lw7vswhnnhw"
AOAI_RESOURCE_URL = "https://aoai-j6lw7vswhnnhw.openai.azure.com"
MODEL = "gpt-5-mini"

# API key required for MCP compatibility
AOAI_KEY = os.environ.get("AOAI_KEY")

# All knowledge sources - each KB uses all 5 sources
# Speed differences come from reasoning effort level, not source count
ALL_SOURCES = [
    "ks-azureblob-video-training",
    "ks-azureblob-engineering-tips",
    "ks-azureblob-maintenance-manuals",
    "ks-azureblob-technical-tips",
    "ks-azureblob-troubleshooting",
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

CITATION FORMAT:
- Use readable source names: (Source: Video - Topic, Tech Tip - Topic)
- Include page/timestamp when available
- Group sources at end of response
"""

def create_knowledge_bases(credential):
    """Create minimal and low reasoning KBs."""
    if not AOAI_KEY:
        print("ERROR: AOAI_KEY environment variable not set")
        print("Get key: az cognitiveservices account keys list --name aoai-j6lw7vswhnnhw --resource-group rg-gent-foundry-eus2 --query key1 -o tsv")
        return []

    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)

    # Model config WITH api_key (required for MCP compatibility)
    aoai_model = KnowledgeBaseAzureOpenAIModel(
        azure_open_ai_parameters=AzureOpenAIVectorizerParameters(
            resource_url=AOAI_RESOURCE_URL,
            deployment_name=MODEL,
            model_name="gpt-5-mini",
            api_key=AOAI_KEY  # Required for MCP!
        )
    )

    # KB configs: name, reasoning effort, output mode
    # NOTE: Fine-tune retrieval_instructions and answer_instructions in Azure Portal
    #       These are baseline configs for infrastructure-as-code deployment
    configs = [
        (
            "davenport-kb-minimal",
            KnowledgeRetrievalMinimalReasoningEffort(),
            KnowledgeRetrievalOutputMode.EXTRACTIVE_DATA,  # Minimal requires extractiveData
        ),
        (
            "davenport-kb-low",
            KnowledgeRetrievalLowReasoningEffort(),
            KnowledgeRetrievalOutputMode.ANSWER_SYNTHESIS,  # Low/Medium use answerSynthesis
        ),
    ]

    for kb_name, reasoning, output_mode in configs:
        kb = KnowledgeBase(
            name=kb_name,
            knowledge_sources=[KnowledgeSourceReference(name=ks) for ks in ALL_SOURCES],
            output_mode=output_mode,
            retrieval_reasoning_effort=reasoning,
            models=[aoai_model]
        )
        index_client.create_or_update_knowledge_base(knowledge_base=kb)
        print(f"[OK] Created Knowledge Base: {kb_name} (output: {output_mode}, sources: {len(ALL_SOURCES)})")

    return ["davenport-kb-minimal", "davenport-kb-low"]


def create_mcp_connections(credential):
    """Create MCP connections for each KB."""
    bearer_token_provider = get_bearer_token_provider(credential, "https://management.azure.com/.default")
    headers = {"Authorization": f"Bearer {bearer_token_provider()}"}

    connections = [
        ("kb-minimal-connection", "davenport-kb-minimal"),
        ("kb-low-connection", "davenport-kb-low"),
    ]

    for conn_name, kb_name in connections:
        mcp_endpoint = f"{SEARCH_ENDPOINT}/knowledgebases/{kb_name}/mcp?api-version=2025-11-01-Preview"

        response = requests.put(
            f"https://management.azure.com{PROJECT_RESOURCE_ID}/connections/{conn_name}?api-version=2025-10-01-preview",
            headers=headers,
            json={
                "name": conn_name,
                "type": "Microsoft.MachineLearningServices/workspaces/connections",
                "properties": {
                    "authType": "ProjectManagedIdentity",
                    "category": "RemoteTool",
                    "target": mcp_endpoint,
                    "isSharedToAll": True,
                    "audience": "https://search.azure.com/",
                    "metadata": {"ApiType": "Azure"}
                }
            }
        )
        if response.status_code in [200, 201]:
            print(f"[OK] Created MCP connection: {conn_name}")
        else:
            print(f"[!] Connection {conn_name}: {response.status_code} - {response.text[:100]}")

    return connections


def create_agents(credential):
    """Create agents for fast and balanced modes."""
    project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    agents_config = [
        ("davenport-fast", "kb-minimal-connection", "davenport-kb-minimal"),
        ("davenport-balanced", "kb-low-connection", "davenport-kb-low"),
    ]

    for agent_name, conn_name, kb_name in agents_config:
        mcp_endpoint = f"{SEARCH_ENDPOINT}/knowledgebases/{kb_name}/mcp?api-version=2025-11-01-Preview"

        mcp_tool = MCPTool(
            server_label="knowledge-base",
            server_url=mcp_endpoint,
            require_approval="never",
            allowed_tools=["knowledge_base_retrieve"],
            project_connection_id=conn_name
        )

        agent = project_client.agents.create_version(
            agent_name=agent_name,
            definition=PromptAgentDefinition(
                model=MODEL,
                instructions=AGENT_INSTRUCTIONS,
                tools=[mcp_tool]
            )
        )
        print(f"[OK] Created Agent: {agent_name} v{agent.version}")


def main():
    print("Setting up multi-KB infrastructure for UI toggle...")
    print("=" * 50)

    credential = DefaultAzureCredential()

    print("\n1. Creating Knowledge Bases...")
    create_knowledge_bases(credential)

    print("\n2. Creating MCP Connections...")
    create_mcp_connections(credential)

    print("\n3. Creating Agents...")
    create_agents(credential)

    print("\n" + "=" * 50)
    print("Setup complete! Baseline KBs and agents created.")
    print("")
    print("Agents:")
    print("  - davenport-fast (minimal reasoning)")
    print("  - davenport-balanced (low reasoning)")
    print("  - davenport-assistant (medium reasoning) [existing]")
    print("")
    print("Next: Fine-tune KB settings in Azure Portal (AI Search > Knowledge Bases)")
    print("  - retrieval_instructions, answer_instructions for low/medium")


if __name__ == "__main__":
    main()
