# Architecture

## Overview
Conversational technical support system for Davenport Model B screw machines. Shop floor machinists ask questions in plain English and get answers sourced from the company's maintenance manuals, engineering tips, and troubleshooting docs — with citations.

## Business Context & Constraints
- **Data Volume**: ~31 PDFs across 5 blob containers, updated infrequently. Some PDFs are image-heavy (engineering diagrams, parts lists, schematics).
- **User Scale**: Internal tool, small team of machinists at Gent Machine.
- **Performance Requirements**: Conversational latency acceptable (seconds, not milliseconds). Indexing is batch, not real-time.
- **Budget Constraints**: Minimize Azure costs. Basic-tier search service.
- **Compliance/Security**: Internal data only. Managed identity for service-to-service auth.
- **Team Context**: Solo developer.

## Architecture Decisions

### Decision 1: Azure AI Search Agentic Retrieval (Foundry IQ)
- **Context**: Need to search across multiple document collections with intelligent query planning.
- **Decision**: Use Foundry's agentic retrieval — knowledge sources, knowledge bases, and MCP-connected agents.
- **Rationale**: Foundry manages the full pipeline (blob → indexer → skillset → index) and adds LLM-powered query planning. Less custom code vs. building from scratch.
- **Trade-offs**: Locked into Foundry's auto-generated index schema and field names. Less control over indexer behavior.

### Decision 2: text-embedding-3-large at 1536 Dimensions
- **Context**: Foundry defaults to text-embedding-3-small (1536d). We wanted better embedding quality without changing index dimensions.
- **Decision**: Switch to text-embedding-3-large truncated to 1536d (Matryoshka embeddings).
- **Rationale**: Better retrieval quality at the same vector size. No index schema changes needed.
- **Trade-offs**: Slightly higher AOAI cost per embedding call. Negligible for our data volume.

### Decision 3: ChatCompletionSkill for Image Verbalization
- **Context**: Many PDFs contain engineering diagrams, parts lists, and schematics. Standard OCR extracts text but misses spatial relationships and diagram meaning.
- **Decision**: Use ChatCompletionSkill (gpt-5-mini) to verbalize each image into searchable text.
- **Rationale**: LLM can understand diagrams, identify part numbers, describe assemblies. OCR alone can't do this.
- **Trade-offs**: Slow — one API call per image. A 50-image PDF takes minutes. `degreeOfParallelism: 5` mitigates this but doesn't eliminate it. The 2-hour indexer limit means image-heavy batches need scheduled auto-resume.

### Decision 4: Scheduled Indexer (PT30M) Instead of On-Demand
- **Context**: Image-heavy PDFs cause the indexer to exceed the 2-hour execution limit.
- **Decision**: Schedule the indexer every 30 minutes so it auto-resumes after timeout.
- **Rationale**: Indexers are single-instance (no backlog) and track a high-water mark (resume from last success). This handles the timeout transparently.
- **Trade-offs**: After uploading new docs, there's up to a 30-minute delay before indexing starts.

## Component Overview

```
                    ┌──────────────────────────┐
                    │   Streamlit Chat UI      │
                    │   (app.py)               │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │   Azure Function API     │
                    │   (func-api/)            │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │   Foundry Agent          │
                    │   (gpt-5-mini)           │
                    │   Connected via MCP      │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │   Knowledge Bases        │
                    │   (group knowledge       │
                    │    sources by topic)      │
                    └──────────┬───────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
┌─────────▼──────┐  ┌─────────▼──────┐  ┌─────────▼──────┐
│ Knowledge      │  │ Knowledge      │  │ Knowledge      │
│ Source:        │  │ Source:        │  │ Source:        │
│ maintenance-   │  │ engineering-   │  │ troubleshooting│
│ manuals        │  │ tips           │  │ + others       │
└────────┬───────┘  └────────┬───────┘  └────────┬───────┘
         │                   │                   │
    ┌────▼────┐         ┌────▼────┐         ┌────▼────┐
    │ Indexer │         │ Indexer │         │ Indexer │
    │ (30min) │         │ (30min) │         │ (30min) │
    └────┬────┘         └────┬────┘         └────┬────┘
         │                   │                   │
    ┌────▼────────────────────────────────────────▼────┐
    │ Skillset Pipeline (per knowledge source):        │
    │  1. Document extraction (text + images)          │
    │  2. ChatCompletionSkill → image verbalization    │
    │  3. Text splitting                               │
    │  4. AzureOpenAIEmbeddingSkill → vectors          │
    └────┬────────────────────────────────────────┬────┘
         │                                        │
    ┌────▼────┐                              ┌────▼────┐
    │ Azure   │                              │ Azure   │
    │ Blob    │                              │ OpenAI  │
    │ Storage │                              │ (embed  │
    │ (PDFs)  │                              │  + chat)│
    └─────────┘                              └─────────┘
```

## Data Flow

1. **Ingest**: PDFs uploaded to Azure Blob Storage containers (one per topic)
2. **Index**: Indexer pulls blobs, skillset extracts text + verbalizes images, embeds content, stores in search index
3. **Query**: User asks question → Agent plans query → Knowledge base searches index → Agent synthesizes answer with citations
4. **Serve**: Answer returned through Azure Function API → Streamlit UI

## Key Patterns Used
- **Managed identity everywhere**: Search service identity reads blobs. `DefaultAzureCredential` for all SDK auth. API keys only where required (AOAI skill auth in skillsets).
- **Scheduled auto-resume**: 30-minute indexer schedule handles the 2-hour timeout transparently for image-heavy PDFs.
- **Parallel image processing**: `degreeOfParallelism: 5` on ChatCompletionSkill to process images concurrently.
- **API key restoration**: `update_skillset.py` always restores masked API keys before PUT to prevent silent auth failures.

## What This System Is NOT
- Not a real-time indexing system — batch processing with up to 30-minute delay
- Not a general-purpose search engine — specifically tuned for Davenport Model B documentation
- Not designed for public-facing scale — internal tool for a small team

## Future Considerations
- Add OCR skill as complement to ChatCompletionSkill for faster text extraction from scanned PDFs
- Re-split image-dense PDFs by image count (not just file size) to stay within indexer time limits
- Update remaining knowledge source skillsets (engineering-tips, technical-tips, troubleshooting, video-training) with corrected deployment names
