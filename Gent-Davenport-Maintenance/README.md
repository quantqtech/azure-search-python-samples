# Gent Davenport Maintenance

Technical support system for Davenport Model B 5-Spindle Automatic Screw Machines. Uses Azure AI Search with a Foundry Agent (gpt-4.1-mini + `azure_ai_search` tool) to provide conversational search over maintenance manuals, engineering tips, troubleshooting guides, and video training documentation. Includes an operator time entry module and admin analytics.

## What It Does

- **Shop floor chat** — machinists ask questions in plain English (e.g., "What's the clearance spec for the roll away clutch?") and get answers sourced from the company's technical documentation, with citations back to the original PDFs and timestamped links to training video transcripts
- **Operator time entry** — digital version of the paper "Operator Hour Report" — hours per machine per activity (Setup/Run/Reset/Repair/Wait Tool/Other)
- **Admin analytics** — app usage rollups, feedback by user (ISO-week), time & machines dashboards (Chart.js), user management

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, data flow, data stores, and decision rationale.

## Production Topology

| Component | Location | Purpose |
|-----------|----------|---------|
| Frontend (SWA) | `static-web-app-direct/src/` — `index.html`, `admin.html`, `time.html`, `login.html` | Chat, graph sidebar, time entry, admin, analytics |
| API (Azure Function) | `func-api/function_app.py` | Chat streaming, feedback, time entries, analytics endpoints |
| Foundry Agent | `davenport-direct-v1` (gpt-4.1-mini + `azure_ai_search` tool) | Conversational retrieval |
| Search | Azure AI Search `davenport-kb-unified` (1,241 docs) | Document retrieval |
| Graph | Cosmos DB Gremlin `machine-ontology` (serverless) | V3 Graph RAG — symptom classification + traversal |
| Storage | Azure Table (`feedback`, `timeentries`, `users`) + Blob (`analytics/*.jsonl` lake) | Dual-write hot + cold pattern |

## Prerequisites

- Python 3.12
- Azure subscription with:
  - Azure AI Search (Basic tier)
  - Azure OpenAI with `text-embedding-3-large`, `gpt-4.1-mini` (Foundry agent) and `gpt-5-mini` (classification) deployments
  - Azure Blob Storage with maintenance documents uploaded
  - Azure AI Foundry project
  - Cosmos DB (Gremlin, serverless) for V3 graph
- `az login` completed (for `DefaultAzureCredential`)
- Azure Functions Core Tools (`func`) for Function App deploys
- `swa` CLI (Azure Static Web Apps) for frontend deploys

## Setup — one-time infra

1. Copy `sample.env` to `.env` and fill in your values:
   ```
   cp sample.env .env
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create the search knowledge sources (indexes the blob containers):
   ```
   python setup_knowledge_sources.py
   ```
4. Build the unified search index from the source indexes:
   ```
   python build_unified_index.py
   ```
5. Create/update the production Foundry agent:
   ```
   python create_direct_search_agent.py
   ```
6. (Optional, V3) Build the Cosmos DB graph ontology:
   ```
   python build_graph.py
   ```

## Deploying updates

- **Function App** (NEVER use `az functionapp deployment source config-zip` — see CLAUDE.md):
  ```
  cd func-api && func azure functionapp publish func-davenport-api --build remote --python
  ```
- **Static Web App** (NOT auto-deployed from GitHub):
  ```
  cd static-web-app-direct && swa deploy src --deployment-token <token> --env production
  ```
- **Agent definition / model / instructions**:
  ```
  python create_direct_search_agent.py
  ```
  Or change the model directly in the Foundry portal → Agents → `davenport-direct-v1` → Model dropdown.

## Key Scripts

| Script | Purpose |
|--------|---------|
| `setup_knowledge_sources.py` | Creates Azure Search knowledge source pipelines (data source, indexer, skillset, index) |
| `update_skillset.py` | Updates skillsets with correct embedding model, image prompts, parallelism, and indexer schedule |
| `build_unified_index.py` | Merges the 5 source indexes into `davenport-kb-unified` |
| `create_direct_search_agent.py` | **Production.** Creates/updates the `davenport-direct-v1` Foundry agent |
| `build_graph.py` | Extracts ontology from documents and populates Cosmos DB Gremlin (V3) |
| `split_oversized_pdfs.py` | Splits PDFs exceeding Azure Search's 16 MB content extraction limit |
| `build_test_knowledge_source.py` | Builds a minimal test pipeline from scratch for debugging |
| `diagnose_skillset.py` | Dumps skillset auth config for debugging 401 errors |

### Quarantined V2 scripts (do NOT run)

Legacy MCP knowledge-base pipeline — retired due to 85-95s latency. Kept for reference only:

| Script | Status |
|--------|--------|
| `create_agent.py` | Creates `davenport-assistant` via MCP/KB — **retired** |
| `update_fast_balanced_agents.py` | Updates `davenport-fast` / `davenport-balanced` MCP agents — **retired** |
| `app.py` | Streamlit UI targeting `davenport-assistant` — **retired** (production UI is the Static Web App) |

## Knowledge Sources

| Container | Content |
|-----------|---------|
| `maintenance-manuals` | Davenport Model B maintenance and parts manuals (image-heavy PDFs) |
| `engineering-tips` | Engineering tips and best practices |
| `technical-tips` | Technical tips for machine operation |
| `troubleshooting` | Troubleshooting procedures |
| `video-training` | Transcripts and notes from training videos |

## Troubleshooting

- **Indexer times out**: Normal for image-heavy PDFs. The indexer has a 2-hour limit. Set a 30-minute schedule via `update_skillset.py` — it auto-resumes where it left off.
- **401 errors on indexer**: API keys may have been wiped by a GET→PUT cycle. Run `update_skillset.py` to restore them.
- **"Deployment not found" errors**: Check that `deploymentId` uses the Foundry deployment name (with suffix), not the model name.
