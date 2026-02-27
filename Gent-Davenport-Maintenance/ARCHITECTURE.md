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

### Decision 5: Direct azure_ai_search Tool with Unified Index (V1 — Feb 2026)
- **Context**: Foundry MCP knowledge base pipeline took 43-49s per query (confirmed via trace analysis). Total response time was 85-95s — too slow for shop floor use.
- **Decision**: Merge all 5 ks-azureblob-* indexes into one `davenport-kb-unified` index. Wire agents to use a single `azure_ai_search` direct tool instead of MCP.
- **Rationale**: Direct azure_ai_search calls take ~0.5-2s vs 43-49s for MCP. The MCP pipeline's multi-pass retrieval, vectorization, and citation generation are designed for quality but too slow. BM25 simple search is fast and sufficient for keyword-based shop floor queries.
- **Trade-offs**: Loses Foundry IQ's semantic reranking and multi-pass retrieval. Gains ~3x speed improvement (85-95s → ~30s). The 3-mode selector (fast/balanced/thorough) is meaningless with direct search since speed is now dominated by LLM answer generation, not retrieval — so new SWA (`static-web-app-direct/`) removes it.
- **Result**: `davenport-kb-unified` (1,241 docs across 5 categories), `davenport-direct-v1` agent, `static-web-app-direct/` parallel front-end.
- **Measured timings**: Search 0.5-2s | LLM answer generation ~21-25s (6,700 tokens) | Total ~30s.

### Decision 1: Azure AI Search Agentic Retrieval / Foundry IQ (V2 — Legacy)
- **Context**: Need to search across multiple document collections with intelligent query planning.
- **Decision**: Use Foundry's agentic retrieval — knowledge sources, knowledge bases, and MCP-connected agents. Three agents (fast/balanced/thorough) connected via MCP to `davenport-machine-kb`.
- **Rationale**: Foundry manages the full pipeline (blob → indexer → skillset → index) and adds LLM-powered query planning. Less custom code vs. building from scratch.
- **Trade-offs**: Locked into Foundry's auto-generated index schema and field names. Less control over indexer behavior. **Retired**: MCP pipeline took 43-49s per query (85-95s total) — replaced by V1 direct search.

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

### Decision 6: Graph RAG with Cosmos DB Gremlin (V3 — Feb 2026)
- **Context**: V1 direct search works for "find me info about X" but struggles with troubleshooting. BM25 keyword search doesn't understand component relationships, can't do structured diagnostics, and misses expert knowledge that isn't in any document (Dave's "10th answer"). The Davenport Model B has ~10,000 parts — a static JSON ontology won't scale or improve over time.
- **Decision**: Cosmos DB Gremlin (serverless) for a dynamic machine ontology graph. Graph stores systems, components, symptoms, causes, and fixes as vertices with edges representing relationships (contains, caused_by, involves, fixed_by). Usage-tracked with hit_count and last_accessed for iterative refinement.
- **Rationale**: Graph database gives traversal queries ("what causes X?"), dynamic schema (add knowledge without redeploying), usage tracking (trim cold nodes, expand hot ones), and iterative refinement. Cosmos DB Gremlin is native Azure, serverless (~$5-15/month), and works with the existing Python stack.
- **Why not Microsoft GraphRAG**: GraphRAG auto-discovers communities in large unstructured text. Our domain is well-understood — we want curated expert knowledge with Ishikawa/fishbone structure, not statistical patterns.
- **Trade-offs**: Adds a new Azure resource (Cosmos DB) and dependency (gremlinpython). Query-time adds a classification step + graph traversal before search. Degrades gracefully to V1 behavior if graph is empty or Cosmos DB is down.
- **Result**: `cosmos-gent-gremlin` account, `davenport-graph` database, `machine-ontology` graph container. 570 vertices, 790 edges from 10 training videos + MasterTask flowcharts + Dave's expert knowledge.

## Component Overview

### V3 Architecture (Graph RAG — In Progress)
```
  static-web-app-direct/
         │
  ┌──────▼───────────┐
  │  Azure Function   │
  │  (func-api/)      │
  └──────┬────────────┘
         │
  ┌──────▼──────────────────────────────────┐
  │  1. Symptom Classification (gpt-5-mini) │
  │     "My part is feeding short"          │
  │      → symptom_id: "part_short"         │
  └──────┬──────────────────────────────────┘
         │
  ┌──────▼──────────────────────────────────┐
  │  2. Graph Traversal (Cosmos DB Gremlin) │
  │     g.V('part_short').outE('caused_by') │
  │      → 5 causes in priority order       │
  │      → components, fixes, categories    │
  └──────┬──────────────────────────────────┘
         │
  ┌──────▼──────────────────────────────────┐
  │  3. Enhanced Agent Call                 │
  │     davenport-direct-v1 gets:           │
  │     GRAPH CONTEXT (diagnostic checklist)│
  │     + USER QUESTION                     │
  │     → searches with intent, not just    │
  │       keywords                          │
  └──────┬──────────────────────────────────┘
         │
  ┌──────▼──────────────────────────────────┐
  │  4. davenport-kb-unified (AI Search)    │
  │     BM25 search guided by graph context │
  └──────┬──────────────────────────────────┘
         │
  ┌──────▼──────────────────────────────────┐
  │  5. Citation Pipeline + Analytics       │
  │     Increment hit_count on activated    │
  │     graph nodes (async, non-blocking)   │
  └─────────────────────────────────────────┘
```

### Graph Model (Cosmos DB Gremlin)
```
Vertex Types:
  system (47)     — Spindle System, Cross Working Tools, Feed & Chuck
  component (235) — collet, brake, cam roll, feed finger, cutoff tool
  symptom (47)    — part short, burr on cutoff, machine jumping, chatter
  cause (118)     — cutoff ring on bar, loose brake, worn cam roll
  fix (123)       — adjust cutoff depth, tighten brake, replace cam roll

Edge Types:
  contains (314)  — system → component
  caused_by (118) — symptom → cause (with priority ranking)
  involves (118)  — cause → component
  fixed_by (123)  — cause → fix
  connects_to, drives, etc. — component → component relationships

Fishbone / Ishikawa Pattern:
  Symptom: "Part is short"
    ├── caused_by (P1) → "Cutoff ring on bar end" [Tooling]
    │       └── fixed_by → "Adjust cutoff depth or resharpen"
    ├── caused_by (P2) → "Feed finger tension low" [Work Holding]
    │       └── fixed_by → "Adjust spring pressure"
    ├── caused_by (P3) → "Collet wear" [Work Holding]
    │       └── fixed_by → "Check bore for scoring, replace"
    ├── caused_by (P4) → "Positive stop worn" [Machine]
    │       └── fixed_by → "Inspect, readjust or replace"
    └── caused_by (P5) → "Bar stock bent" [Stock/Material]
            └── fixed_by → "Check straightness, reject bad stock"
```

### V1 Architecture (Direct Search — Current Production)
```
  static-web-app-direct/
         │
  ┌──────▼───────────┐
  │  Azure Function   │  POST /api/chat/stream
  │  (func-api/)      │
  └──────┬────────────┘
         │
  ┌──────▼──────────────────┐
  │  davenport-direct-v1    │  gpt-5-mini + azure_ai_search tool
  │  BM25 simple query      │
  └──────┬──────────────────┘
         │
  ┌──────▼──────────────────────────────────┐
  │  davenport-kb-unified (1,241 docs)      │
  │  Merged from 5 ks-azureblob-* indexes   │
  └─────────────────────────────────────────┘
```

### V2 Architecture (Foundry IQ / MCP — Legacy)
The original approach: 3 agents (davenport-fast, davenport-balanced, davenport-assistant) connected via MCP to `davenport-machine-kb` knowledge base. Foundry IQ provided semantic reranking and multi-pass retrieval, but the MCP pipeline took 43-49s per query — total response time 85-95s. Retired in favor of V1 direct search. Agents still exist in Foundry but are not actively used.

## Data Flow

### V3 Query-Time Flow (In Progress)
1. **User question** arrives at Function App (`POST /api/chat/stream`)
2. **Symptom classification** — quick gpt-5-mini call classifies the question into a known symptom ID
3. **Graph traversal** — Gremlin query traverses symptom → causes (priority ordered) → components → fixes
4. **Enhanced agent input** — graph context (diagnostic checklist) prepended to user question
5. **AI Search** — agent searches `davenport-kb-unified` guided by graph context
6. **Answer synthesis** — agent combines graph knowledge + search results into structured answer
7. **Citation pipeline** — clean URLs, link citations, transform video URLs
8. **Analytics** — async increment hit_count on activated graph nodes

### V1 Data Flow (Current Production)
1. **Ingest**: PDFs uploaded to Azure Blob Storage containers (one per topic)
2. **Index**: Indexer pulls blobs, skillset extracts text + verbalizes images, stores in search index
3. **Query**: User asks question → Agent searches unified index → Agent synthesizes answer with citations
4. **Serve**: Answer returned through Azure Function API → Static Web App UI

## Key Files

| File | Purpose |
|------|---------|
| `graph_client.py` | Cosmos DB Gremlin connection helper + query-time traversals |
| `build_graph.py` | Extract ontology from video + MasterTask chunks, populate graph |
| `build_unified_index.py` | Merge 5 source indexes into davenport-kb-unified |
| `create_direct_search_agent.py` | Create/update davenport-direct-v1 agent |
| `func-api/function_app.py` | Azure Function API — chat, streaming, feedback, citations |
| `func-api/graph_helper.py` | Query-time graph functions for Function App (V3) |
| `graph_extractions.json` | Raw LLM extraction output (debug/review artifact) |

## Azure Resources

| Resource | Type | Purpose | Cost |
|----------|------|---------|------|
| `srch-j6lw7vswhnnhw` | Azure AI Search (Basic) | Unified index + source indexes | ~$70/month |
| `aoai-j6lw7vswhnnhw` | Azure OpenAI | gpt-5-mini agent + embeddings | Pay-per-use |
| `stj6lw7vswhnnhw` | Storage Account | PDF blobs + feedback table | ~$5/month |
| `cosmos-gent-gremlin` | Cosmos DB (Gremlin, Serverless) | Machine ontology graph | ~$5-15/month |

## What This System Is NOT
- Not a real-time indexing system — batch processing with up to 30-minute delay
- Not a general-purpose search engine — specifically tuned for Davenport Model B documentation
- Not designed for public-facing scale — internal tool for a small team
- Not auto-pruning — cold graph nodes flagged for manual review, never auto-deleted

## Future Considerations
- **Phase 2: Query-time graph integration** — wire symptom classification + graph traversal into function_app.py
- **Phase 3: Page numbers** — extract page numbers from PDFs, add to unified index, include in citations
- **Phase 4: Admin dashboard** — graph usage stats, hot/cold nodes, add/edit graph nodes
- **Phase 5: LLM expansion + Dave review** — expand extraction to all source docs, Dave verifies unverified nodes
- **Foundry IQ long-term**: Re-evaluate when Microsoft resolves MCP latency (currently 43-49s structural)
