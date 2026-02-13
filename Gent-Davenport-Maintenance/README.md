# Gent Davenport Maintenance

Technical support system for Davenport Model B 5-Spindle Automatic Screw Machines. Uses Azure AI Search agentic retrieval with Foundry Agent Service to provide conversational search over maintenance manuals, engineering tips, troubleshooting guides, and video training documentation.

## What It Does

Shop floor machinists ask questions in plain English (e.g., "What's the clearance spec for the roll away clutch?") and get answers sourced from the company's technical documentation — with citations back to the original PDFs.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, data flow, and decision rationale.

## Prerequisites

- Python 3.10+
- Azure subscription with:
  - Azure AI Search (Basic tier or higher)
  - Azure OpenAI with `text-embedding-3-large` and `gpt-5-mini` deployments
  - Azure Blob Storage with maintenance documents uploaded
  - Azure AI Foundry project
- `az login` completed (for `DefaultAzureCredential`)

## Setup

1. Copy `sample.env` to `.env` and fill in your values:
   ```
   cp sample.env .env
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create knowledge sources (indexes the blob containers):
   ```
   python setup_knowledge_sources.py
   ```

4. Create the agent:
   ```
   python create_agent.py
   ```

5. Run the chat UI:
   ```
   streamlit run app.py
   ```

## Key Scripts

| Script | Purpose |
|--------|---------|
| `setup_knowledge_sources.py` | Creates Azure Search knowledge source pipelines (data source, indexer, skillset, index) |
| `update_skillset.py` | Updates skillsets with correct embedding model, image prompts, parallelism, and indexer schedule |
| `create_agent.py` | Creates a Foundry Agent connected to knowledge bases via MCP |
| `app.py` | Streamlit chat UI |
| `split_oversized_pdfs.py` | Splits PDFs exceeding Azure Search's 16 MB content extraction limit |
| `build_test_knowledge_source.py` | Builds a minimal test pipeline from scratch for debugging |
| `diagnose_skillset.py` | Dumps skillset auth config for debugging 401 errors |

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
