"""
Fix Knowledge Bases for MCP compatibility.
- Adds api_key to model config (required for MCP)
- Changes output_mode from extractiveData to answerSynthesis (required for MCP)
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

# Configuration
SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
AOAI_RESOURCE_URL = "https://aoai-j6lw7vswhnnhw.openai.azure.com"
MODEL = "gpt-5-mini"

# Get API key from environment or prompt
AOAI_KEY = os.environ.get("AOAI_KEY")

KNOWLEDGE_SOURCES = [
    "ks-azureblob-video-training",
    "ks-azureblob-engineering-tips",
    "ks-azureblob-maintenance-manuals",
    "ks-azureblob-technical-tips",
    "ks-azureblob-troubleshooting"
]


def main():
    if not AOAI_KEY:
        print("ERROR: AOAI_KEY environment variable not set")
        print("Get the key with: az cognitiveservices account keys list --name aoai-j6lw7vswhnnhw --resource-group rg-gent-foundry-eus2 --query key1 -o tsv")
        print("Then set: $env:AOAI_KEY = 'your-key-here'")
        return

    print("Fixing Knowledge Bases for MCP compatibility...")
    print("=" * 50)

    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)

    # Model config WITH api_key (critical for MCP)
    aoai_model = KnowledgeBaseAzureOpenAIModel(
        azure_open_ai_parameters=AzureOpenAIVectorizerParameters(
            resource_url=AOAI_RESOURCE_URL,
            deployment_name=MODEL,
            model_name="gpt-5-mini",
            api_key=AOAI_KEY  # Required for MCP!
        )
    )

    # Fix both KBs - must use ANSWER_SYNTHESIS for MCP
    configs = [
        ("davenport-kb-minimal", KnowledgeRetrievalMinimalReasoningEffort()),
        ("davenport-kb-low", KnowledgeRetrievalLowReasoningEffort()),
    ]

    for kb_name, reasoning in configs:
        kb = KnowledgeBase(
            name=kb_name,
            knowledge_sources=[KnowledgeSourceReference(name=ks) for ks in KNOWLEDGE_SOURCES],
            output_mode=KnowledgeRetrievalOutputMode.ANSWER_SYNTHESIS,  # Changed from EXTRACTIVE_DATA
            retrieval_reasoning_effort=reasoning,
            models=[aoai_model]  # Now includes api_key
        )
        index_client.create_or_update_knowledge_base(knowledge_base=kb)
        print(f"[OK] Fixed Knowledge Base: {kb_name}")
        print(f"     - output_mode: answerSynthesis")
        print(f"     - model with api_key: yes")

    print("\n" + "=" * 50)
    print("Knowledge Bases fixed! Fast and Balanced modes should now work.")


if __name__ == "__main__":
    main()
