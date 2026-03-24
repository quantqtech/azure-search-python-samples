# Gent Davenport Maintenance - Project Instructions

## Project Overview
Davenport Model B screw machine technical support system. Shop floor machinists ask questions, get answers with citations from a unified search index.

**Production agent**: `davenport-direct-v1` — uses `azure_ai_search` tool against `davenport-kb-unified` index (1,241 docs). Fast (~30s).

**Retired (V2)**: Foundry IQ / MCP knowledge base pipeline — 3 separate agents, 3 indexes, 85-95s per query. Too slow. Do NOT use `reasoning_level: "balanced"` — that routes to the old MCP agents.

### Quarantined Scripts (V2 — non-production)
These scripts are kept for reference but target retired V2 agents. Do NOT run them.
- `update_fast_balanced_agents.py` — `davenport-fast` + `davenport-balanced` (MCP/KB)
- `create_agent.py` — `davenport-assistant` (MCP/KB)

Production deployment script: `create_direct_search_agent.py` only.

## Azure Resources (rg-gent-foundry-eus2, East US 2)
- **Search Service**: srch-j6lw7vswhnnhw
- **Azure OpenAI**: aoai-j6lw7vswhnnhw
- **Storage Account**: stj6lw7vswhnnhw
- **Foundry Project**: proj-j6lw7vswhnnhw

## Knowledge Source Pipeline
Knowledge sources are created via `setup_knowledge_sources.py` using `AzureBlobKnowledgeSource`.
Each knowledge source auto-generates: data source, indexer, skillset, and index (all prefixed `ks-`).

**Auth**: All blob connections use **managed identity** (ResourceId connection string format).
The search service's system-assigned managed identity needs `Storage Blob Data Reader` on the storage account.

## Key Patterns
- `SearchIndexClient` with `DefaultAzureCredential` for knowledge source/base management
- `AIProjectClient` with `DefaultAzureCredential` for agent management
- Knowledge Bases reference knowledge sources by name
- Agents connect to KBs via MCP endpoint + project connection
- AOAI_KEY env var required for KB model config (MCP compatibility)

## Models
- **Embedding**: text-embedding-3-large (Matryoshka truncated to 1536d — better quality than -small at same dimensions)
- **Chat/Agent**: gpt-5-mini

### Foundry Deployment Names (MUST match exactly)
Foundry auto-generates deployment names with suffixes. These are NOT the same as model names.
- `text-embedding-3-large-088065` — deploymentId for text-embedding-3-large
- Azure Search requires BOTH `deploymentId` (deployment name) AND `modelName` (model name) separately

## Critical Gotchas

### Azure Search Masks Secrets on GET
When you GET a skillset/data source from Azure Search:
- `apiKey` comes back as `<redacted>`
- `connectionString` comes back as `null`

If you PUT that back, all skills lose auth and fail with 401. **Always restore real credentials before PUT.**
The `update_skillset.py` has a `restore_api_keys()` function for this — requires AOAI_KEY in `.env`.

### REST API 2025-11-01-Preview Property Names
These differ from older versions and from the Python SDK:
- `algorithm` (not `algorithmConfigurationName`)
- `vectorizer` (not `vectorizerName`)
- `prioritizedContentFields` (not `contentFields`)
- Always check `build_test_knowledge_source.py` for verified working property names

## Verified Working Configuration (test-mm-* pipeline)
Built from scratch, all green, 0 errors:
- Index: `test-mm-index` — `content` (searchable), `content_vector` (1536d), semantic config
- Data Source: `test-mm-datasource` — blob storage, managed identity (ResourceId), `ztest` container
- Skillset: `test-mm-skillset` — single AzureOpenAIEmbeddingSkill, text-embedding-3-large-088065, 1536d
- Indexer: `test-mm-indexer` — connects all three, runs successfully
- See `build_test_knowledge_source.py` for the complete, verified pipeline definition
