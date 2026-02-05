"""
Toggle Knowledge Base reasoning effort level.
Usage: py set_reasoning_level.py [minimal|low|medium]
"""

import sys
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    KnowledgeBase,
    KnowledgeRetrievalMinimalReasoningEffort,
    KnowledgeRetrievalLowReasoningEffort,
    KnowledgeRetrievalMediumReasoningEffort,
    KnowledgeRetrievalOutputMode,
    KnowledgeSourceReference
)

SEARCH_ENDPOINT = "https://srch-j6lw7vswhnnhw.search.windows.net"
KB_NAME = "davenport-machine-kb"

# Knowledge sources to include
KNOWLEDGE_SOURCES = [
    "ks-azureblob-video-training",
    "ks-azureblob-engineering-tips",
    "ks-azureblob-maintenance-manuals",
    "ks-azureblob-technical-tips",
    "ks-azureblob-troubleshooting"
]

REASONING_LEVELS = {
    "minimal": KnowledgeRetrievalMinimalReasoningEffort(),
    "low": KnowledgeRetrievalLowReasoningEffort(),
    "medium": KnowledgeRetrievalMediumReasoningEffort()
}


def set_reasoning_level(level: str):
    if level not in REASONING_LEVELS:
        print(f"Invalid level. Choose: minimal, low, or medium")
        return

    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)

    kb = KnowledgeBase(
        name=KB_NAME,
        knowledge_sources=[KnowledgeSourceReference(name=ks) for ks in KNOWLEDGE_SOURCES],
        output_mode=KnowledgeRetrievalOutputMode.EXTRACTIVE_DATA,
        retrieval_reasoning_effort=REASONING_LEVELS[level]
    )

    index_client.create_or_update_knowledge_base(knowledge_base=kb)
    print(f"[OK] Knowledge Base reasoning set to: {level.upper()}")
    print()
    print("Expected performance:")
    if level == "minimal":
        print("  - Speed: ~5-15 seconds")
        print("  - Single query, basic retrieval")
    elif level == "low":
        print("  - Speed: ~15-25 seconds")
        print("  - Some query planning")
    else:  # medium
        print("  - Speed: ~30-50 seconds")
        print("  - Full query decomposition, parallel search, reranking")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: py set_reasoning_level.py [minimal|low|medium]")
        print()
        print("Current levels and tradeoffs:")
        print("  minimal - Fast (~10s), single query, good for simple lookups")
        print("  low     - Moderate (~20s), some planning, balanced")
        print("  medium  - Thorough (~45s), full agentic reasoning, best answers")
    else:
        set_reasoning_level(sys.argv[1])
