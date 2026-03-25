# Architecture

## Overview
Conversational technical support system for Davenport Model B screw machines. Shop floor machinists ask questions in plain English and get answers sourced from the company's maintenance manuals, engineering tips, troubleshooting docs, and training videos — with citations and a visual machine graph.

## Business Context & Constraints
- **Data Volume**: ~31 PDFs + 10 training video transcripts across 5 blob containers, updated infrequently. Some PDFs are image-heavy (engineering diagrams, parts lists, schematics). ~1,241 chunks in unified search index.
- **User Scale**: Internal tool, small team of machinists at Gent Machine (~20-50 queries/day).
- **Performance Requirements**: Conversational latency acceptable (seconds, not milliseconds). Indexing is batch, not real-time.
- **Budget Constraints**: Minimize Azure costs. Basic-tier search, serverless Cosmos DB.
- **Compliance/Security**: Internal data only. Managed identity for service-to-service auth.
- **Team Context**: Solo developer with domain expert (Dave) providing machine knowledge.

---

## V3 Architecture: Two-Layer Graph RAG

### Design Principle

The system uses two layers of graph context to help the LLM search smarter:

- **Layer 1 (World Model)**: A lean, cached structural overview of the entire machine (~500 tokens). Prepended to every query. Gives the LLM orientation — "here's what the machine looks like."
- **Layer 2 (Focused Traversal)**: A dynamic, question-specific subgraph. Classifies the question to 1-2 components, traverses 1-2 hops, and feeds the relevant neighborhood (causes, fixes, connections) to the LLM. Also drives the sidebar graph visualization.

**Why two layers**: Layer 1 alone is too broad (the LLM knows everything exists but nothing specific). Layer 2 alone misses the big picture (the LLM doesn't know where a component fits in the machine). Together, the LLM gets both orientation and focus.

### Query-Time Data Flow

```
User: "Why is my part coming out short?"
        │
        ▼
┌─── Layer 1: World Model ────────────────────────┐
│ Static, cached on Function App startup           │
│ "DAVENPORT MODEL B — MACHINE OVERVIEW:           │
│   Work Spindles: Spindle, Collet, ...            │
│   Chuck and Feed: Feed Fingers, Positive Stop    │
│   ..."                                           │
│ ~500 tokens, every query gets this               │
└──────────────────────────────────────────────────┘
        │
        ▼
┌─── Layer 2: Focused Traversal ──────────────────┐
│ Dynamic, per-question                            │
│                                                  │
│ 1. classify_component() → cutoff_tool            │
│    (gpt-5-mini, ~200ms)                          │
│                                                  │
│ 2. Gremlin traversal from cutoff_tool:           │
│    → Parent system: Cross Working Tools          │
│    → Causes: cutoff_ring_on_bar (conf 1.0, P1)  │
│              cutoff_tool_dull (conf 0.7, P2)     │
│    → Fixes: adjust cutoff depth, resharpen       │
│    → Connected: collet, positive_stop            │
│                                                  │
│ 3. Serialized as text → agent context            │
│ 4. Same data → sidebar graph visualization       │
│                                                  │
│ 5. Hit counters incremented on traversed edges   │
└──────────────────────────────────────────────────┘
        │
        ▼
┌─── Agent + Search ──────────────────────────────┐
│ Input = Layer 1 + Layer 2 + User Question        │
│ davenport-direct-v1 (gpt-5-mini)                 │
│ Uses azure_ai_search on davenport-kb-unified     │
│ Graph context helps prioritize the answer        │
└──────────────────────────────────────────────────┘
        │
        ▼
┌─── Citation Pipeline (9 passes) ───────────────┐
│ markers → search URLs → empty links → inline →  │
│ embedded → brackets → single-bracket →           │
│ fallback link → YouTube conversion               │
│ (see "Citation Pipeline" section for details)    │
└──────────────────────────────────────────────────┘
        │
        ▼
┌─── Analytics ───────────────────────────────────┐
│ JSONL data lake: conversation logs               │
│ Table Storage: user feedback                     │
│ Table Storage: graph usage counters              │
│ Table Storage: verification ledger               │
└──────────────────────────────────────────────────┘
```

### Three-Store Model

The system separates data by durability requirements:

| Store | Purpose | Durability | Rebuild safe? |
|-------|---------|------------|---------------|
| **Cosmos DB Gremlin graph** | Structure + relationships (systems, components, causes, fixes, edges) | Rebuildable from documents | Yes — can be dropped and reconstructed |
| **Table Storage: `graph-verifications`** | Human decisions (Dave's expert knowledge, admin verifications) | Permanent | Never auto-deleted — this is the source of truth for human knowledge |
| **Table Storage: `graph-usage`** | Hit counters, success counts per edge | Permanent | Survives graph rebuilds — restored after reconstruction |

**Why separate stores**: The graph can be rebuilt anytime (re-extract from documents, add new sources, fix bad extractions). But human verification decisions and accumulated usage data represent irreplaceable effort and history. Separating them means a graph rebuild never loses knowledge.

### Confidence Model

Every vertex in the graph has a `confidence` property (0.0–1.0) that affects traversal ranking:

| Level | Meaning | How set |
|-------|---------|---------|
| **1.0** | Expert confirmed | Dave verifies via admin page → written to verification ledger |
| **0.7** | Multi-document corroboration | Automatic: same relationship extracted from 3+ independent documents |
| **0.5** | Single document extraction | Default for all LLM-extracted entries |
| **0.3** | Low confidence / contradicted | Flagged during review when conflicting information found |
| **0.0** | Rejected | Dave rejects → removed from graph on next rebuild |

**Traversal uses confidence for ranking**: When Layer 2 traverses causes for a component, results are sorted by confidence descending. The agent sees the most trusted answers first.

**Confidence + hit counters together**: High confidence + high hits = proven path (weight heavily). High confidence + low hits = expert knowledge not yet validated by usage (trust but monitor). Low confidence + high hits = users ask about this frequently but the knowledge isn't verified (flag for Dave's review).

### Verification Lifecycle

```
Documents → LLM extraction → graph entries (confidence 0.5)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            Cross-doc match?   Usage signals    Dave reviews
            confidence → 0.7   hit counters     confidence → 1.0
                                build history     or rejected (0.0)
                                    │
                                    ▼
                            Analytics lake
                            informs future
                            graph improvements
```

Dave's expert knowledge (originally hardcoded in `build_graph.py` as `add_expert_knowledge()`) lives in the `graph-verifications` table as seed data with confidence 1.0. New verifications from the admin page go to the same table. On graph rebuild, the verification ledger is re-applied — all human decisions survive.

### Graph Rebuild Safety Protocol

```
Step 1: Export usage counters from graph-usage table (backup)
Step 2: Drop only vertices with confidence < 1.0
         → Expert-verified vertices (confidence=1.0) survive
Step 3: Re-run LLM extraction from all documents
         → New entries get confidence=0.5
Step 4: Apply cross-document corroboration
         → Entries from 3+ sources bumped to 0.7
Step 5: Apply verification ledger from Table Storage
         → All human decisions re-applied (includes Dave's seed data)
Step 6: Restore usage counters from backup
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
  connects_to, drives — component → component relationships

Vertex Properties:
  confidence (float) — 0.0 to 1.0, drives traversal ranking
  source (string)    — "dave_expert", "video_transcript", "troubleshooting", etc.

Fishbone / Ishikawa Pattern:
  Symptom: "Part is short"
    ├── caused_by (P1, conf 1.0) → "Cutoff ring on bar end" [Tooling]
    │       └── fixed_by → "Adjust cutoff depth or resharpen"
    ├── caused_by (P2, conf 1.0) → "Feed finger tension low" [Work Holding]
    │       └── fixed_by → "Adjust spring pressure"
    ├── caused_by (P3, conf 0.7) → "Collet wear" [Work Holding]
    │       └── fixed_by → "Check bore for scoring, replace"
    ├── caused_by (P4, conf 0.5) → "Positive stop worn" [Machine]
    │       └── fixed_by → "Inspect, readjust or replace"
    └── caused_by (P5, conf 0.5) → "Bar stock bent" [Stock/Material]
            └── fixed_by → "Check straightness, reject bad stock"
```

---

## Architecture Decisions

### Decision 6: Two-Layer Graph RAG with Confidence Model (V3 — Feb 2026)
- **Context**: V1 direct search works for "find me info about X" but struggles with troubleshooting. BM25 keyword search doesn't understand component relationships and can't do structured diagnostics. A static JSON ontology won't scale or improve over time.
- **Decision**: Cosmos DB Gremlin (serverless) for a dynamic machine ontology graph. Two-layer query architecture: Layer 1 (cached world model for orientation) + Layer 2 (dynamic focused traversal for specific context). Confidence-based vertex ranking replaces binary verified/unverified.
- **Rationale**: Layer 1 is cheap (~500 tokens, cached) and gives every query baseline machine knowledge. Layer 2 is targeted and aligns the sidebar visualization with what the agent actually knows. Confidence levels let unverified LLM-extracted knowledge participate at lower weight while expert-verified knowledge gets priority.
- **Why one graph, not two**: Keeping curated and extracted knowledge in one graph means traversals discover both — Dave's expert cause→fix chains appear alongside document-extracted ones. Physical separation would require duplicating components or merging results at query time. Protection comes from the confidence property and rebuild safety protocol, not physical isolation.
- **Why not Microsoft GraphRAG**: GraphRAG auto-discovers communities in large unstructured text. Our domain is well-understood — we want curated expert knowledge with Ishikawa/fishbone structure, not statistical patterns. At ~1,241 docs, the overhead of GraphRAG's indexing pipeline isn't justified. LazyGraphRAG principles (lightweight structure, heavy lifting at query time) influenced the Layer 1/Layer 2 split.
- **Trade-offs**: Adds Cosmos DB dependency and classification step. Degrades gracefully to V1 behavior if graph is empty or Cosmos DB is down.
- **Result**: `cosmos-gent-gremlin` account, `davenport-graph` database, `machine-ontology` graph. 570 vertices, 790 edges. Three durable stores (graph, verification ledger, usage counters).

### Decision 5: Direct azure_ai_search Tool with Unified Index (V1 — Feb 2026)
- **Context**: Foundry MCP knowledge base pipeline took 43-49s per query (confirmed via trace analysis). Total response time was 85-95s — too slow for shop floor use.
- **Decision**: Merge all 5 ks-azureblob-* indexes into one `davenport-kb-unified` index. Wire agents to use a single `azure_ai_search` direct tool instead of MCP.
- **Rationale**: Direct azure_ai_search calls take ~0.5-2s vs 43-49s for MCP. BM25 simple search is fast and sufficient for keyword-based shop floor queries.
- **Trade-offs**: Loses Foundry IQ's semantic reranking and multi-pass retrieval. Gains ~3x speed improvement (85-95s → ~30s).
- **Result**: `davenport-kb-unified` (1,241 docs across 5 categories), `davenport-direct-v1` agent.

### Decision 1: Azure AI Search Agentic Retrieval / Foundry IQ (V2 — Legacy)
- **Context**: Need to search across multiple document collections with intelligent query planning.
- **Decision**: Use Foundry's agentic retrieval — knowledge sources, knowledge bases, and MCP-connected agents.
- **Rationale**: Foundry manages the full pipeline and adds LLM-powered query planning.
- **Trade-offs**: **Retired**: MCP pipeline took 43-49s per query (85-95s total) — replaced by V1 direct search.

### Decision 2: text-embedding-3-large at 1536 Dimensions
- **Context**: Foundry defaults to text-embedding-3-small (1536d). We wanted better embedding quality without changing index dimensions.
- **Decision**: Switch to text-embedding-3-large truncated to 1536d (Matryoshka embeddings).
- **Rationale**: Better retrieval quality at the same vector size. No index schema changes needed.
- **Trade-offs**: Slightly higher AOAI cost per embedding call. Negligible for our data volume.

### Decision 3: ChatCompletionSkill for Image Verbalization
- **Context**: Many PDFs contain engineering diagrams, parts lists, and schematics. Standard OCR extracts text but misses spatial relationships and diagram meaning.
- **Decision**: Use ChatCompletionSkill (gpt-5-mini) to verbalize each image into searchable text.
- **Rationale**: LLM can understand diagrams, identify part numbers, describe assemblies.
- **Trade-offs**: Slow — one API call per image. The 2-hour indexer limit means image-heavy batches need scheduled auto-resume.

### Decision 4: Scheduled Indexer (PT30M) Instead of On-Demand
- **Context**: Image-heavy PDFs cause the indexer to exceed the 2-hour execution limit.
- **Decision**: Schedule the indexer every 30 minutes so it auto-resumes after timeout.
- **Rationale**: Indexers are single-instance and track a high-water mark (resume from last success).
- **Trade-offs**: After uploading new docs, up to a 30-minute delay before indexing starts.

---

## Component Overview

### Frontend
- **Static Web App** (`static-web-app-direct/src/index.html`): Single-page app with chat interface, graph sidebar, admin page
- Graph sidebar: vis.js network visualization showing the Layer 2 focused subgraph
- SSE streaming: Frontend calls Function App directly (not via SWA proxy — required for SSE)

### Graph Sidebar Visual Design

The sidebar always shows a graph — Layer 2 focused traversal when a component is matched, Layer 1 overview when no match. The visual language is consistent across all question types.

**Node types and visual encoding** (derived from brand palette — refined pastels, not bright primaries):

| Node type | Shape | Fill | Border | When shown |
|-----------|-------|------|--------|------------|
| System | Box | `#c4dae8` (pale blue) | `#7fadc8` | Always — parent system context |
| Component (queried) | Circle, large | `#fde8d9` (pale peach) | `#F3802B` (brand orange) | The classified component |
| Component (related) | Circle, small | `#e8ecf0` (cool gray) | `#b8c4d0` | Connected or sibling components |
| Cause | Diamond | `#f5e6d4` (warm sand) | `#d4b896` | Diagnostic paths |
| Fix | Rounded box | `#d8e8d8` (sage green) | `#a8c8a8` | Resolution steps |
| Symptom | Hexagon | `#f0dada` (soft blush) | `#d4a8a8` | Problem being diagnosed |

**Confidence encoding**: Node opacity scales with confidence (1.0 = fully opaque, 0.5 = 70% opacity). This subtly communicates trust level without adding text clutter.

**Edge styling**: Light `#ccc` default, brand blue `#00528A` on hover. Priority labels (P1, P2) on cause edges. "contains" labels hidden (structural noise).

**Sidebar tiers** (the graph is never empty):
1. **Component matched** → Layer 2 focused traversal: queried component + causes + fixes + connections
2. **No component matched** → Layer 1 interactive overview: systems with their components, clickable
3. **Graph unavailable** → Sidebar hidden (graceful V1 degradation)

**Graph shapes by question type**:
- Diagnostic ("why is my part short?") → tree: symptom → causes (P1, P2...) → fixes
- Component ("how do I adjust the collet?") → star: component → parent system + connections + causes
- Multi-component ("collet scoring the bar") → merged stars from 2 components
- General ("what is a Davenport?") → Layer 1 overview map

### Backend
- **Azure Function App** (`func-api/function_app.py`): Python 3.12, Linux consumption plan
  - `POST /api/chat` — non-streaming chat endpoint
  - `POST /api/chat/stream` — SSE streaming endpoint (primary)
  - `POST /api/feedback` — user feedback (thumbs up/down/flag)
  - `GET /api/feedback` — admin feedback review
  - `POST /api/voice-memo` — voice memo upload to blob storage
- **Citation pipeline**: 9-pass processing — see detailed section below

### Citation Pipeline (detailed)

The agent outputs citations in **8+ inconsistent formats** depending on how Foundry and the LLM interact on a given run. The pipeline normalizes all of them into `[Display Name](URL)` markdown links.

**Why this is complex**: The agent uses `azure_ai_search`, which returns blob URLs for documents and `【N:M†source】` markers. But the agent also generates its own markdown links, empty-URL links, parenthetical citations, and bracket citations. Video transcripts are `.md` files in blob storage that must redirect to YouTube URLs. Timestamps like `04:14–05:22` (en-dash, not hyphen) should become YouTube deep links.

**Agent output formats** (all observed in production):
| Format | Example | Handled by |
|--------|---------|------------|
| A | `(Name) 【7:1†source】` | Step 1: process_citations |
| B | `[Name](blob_url)` | Step 9: transform_transcript_urls |
| C | `[Name]()` | Step 3: fill_empty_url_citations |
| D | `([Name](blob_url) timestamp)` | Step 8: fallback (embedded markdown detection) |
| E | `(Name)(url)` | Step 4: convert_inline_url |
| F | `(Name (url))` | Step 5: convert_embedded_url |
| G | `[Name]` | Step 7: convert_single_bracket |
| H | `[[Name]]` | Step 6: convert_bracket_citations |

**Pipeline order** (both streaming and non-streaming paths must match):
1. `process_citations` — Format A: replaces `(Name)【marker】` using annotation lookup
2. `clean_search_service_urls` — strips `.search.windows.net` URLs (not real blob URLs)
3. `fill_empty_url_citations` — Format C: `[Name]()` → YouTube or `(Name)` for fallback
4. `convert_inline_url_citations` — Format E: `(Name)(url)` → `[Name](url)`
5. `convert_embedded_url_citations` — Format F: `(Name (url))` → `[Name](url)`
6. `convert_bracket_citations` — Format H: `[[Name]]` → `(Name)`
7. `convert_single_bracket_citations` — Format G: `[Name]` → `(Name)`
8. `fallback_link_citations` — `(Name)` → `[Name](blob_url)` or YouTube. **Also handles Format D** — detects `[text](url)` already inside the parenthetical and extracts properly instead of nesting
9. `transform_transcript_urls_to_youtube` — Format B: `[Name](video-training/*.md)` → YouTube

**Critical gotchas**:
- Steps 1-9 MUST run in this order. Step 8 (fallback) is the catch-all that handles anything left as `(Name)`. Steps 6-7 normalize brackets to parens so step 8 can handle them.
- Step 8 can accidentally match Format D (`([Name](url) timestamp)`) because its regex matches any `(text)`. The `replace_unlinked` function detects embedded markdown links and handles them correctly.
- Video transcript blob URLs (`.md` files in `video-training/`) have NO value as user-facing links — they must become YouTube links via `YOUTUBE_VIDEO_MAP`.
- The agent uses en-dash (U+2013), not hyphen, between timestamp ranges. All timestamp regexes must handle both.
- Both streaming and non-streaming code paths run the exact same 9 steps — keep them in sync.

### Graph
- **Cosmos DB Gremlin** (`cosmos-gent-gremlin`, serverless): Machine ontology graph
- **graph_helper.py** (in func-api): Query-time graph functions
  - `build_world_model()` — Layer 1 structural summary
  - `build_component_graph_viz()` — Sidebar visualization data
  - `build_focused_context()` — Layer 2 focused traversal (planned)
- **graph_client.py**: Gremlin connection helper, vertex/edge CRUD
- **build_graph.py**: Offline script to extract ontology from documents and populate graph

### Search
- **Azure AI Search** (`srch-j6lw7vswhnnhw`): `davenport-kb-unified` index, 1,241 docs
- **Foundry Agent**: `davenport-direct-v1` (gpt-5-mini + azure_ai_search tool)

---

## Key Files

| File | Purpose |
|------|---------|
| `func-api/function_app.py` | Azure Function API — chat, streaming, feedback, citation pipeline |
| `func-api/graph_helper.py` | Query-time graph functions for Function App (Layer 1 + Layer 2) |
| `graph_client.py` | Cosmos DB Gremlin connection helper + CRUD operations |
| `build_graph.py` | Extract ontology from documents, populate graph (offline) |
| `build_unified_index.py` | Merge 5 source indexes into davenport-kb-unified |
| `create_direct_search_agent.py` | Create/update davenport-direct-v1 agent in Foundry |
| `static-web-app-direct/src/index.html` | Frontend SPA — chat, graph sidebar, streaming |
| `static-web-app-direct/src/admin.html` | Admin page — feedback review, graph verification |

## Azure Resources

| Resource | Type | Purpose | Cost |
|----------|------|---------|------|
| `srch-j6lw7vswhnnhw` | Azure AI Search (Basic) | Unified index + source indexes | ~$70/month |
| `aoai-j6lw7vswhnnhw` | Azure OpenAI | gpt-5-mini agent + embeddings + classification | Pay-per-use |
| `stj6lw7vswhnnhw` | Storage Account | PDF blobs + feedback table + verification ledger + usage counters + analytics lake | ~$5/month |
| `cosmos-gent-gremlin` | Cosmos DB (Gremlin, Serverless) | Machine ontology graph | ~$5-15/month |

## What This System Is NOT
- Not a real-time indexing system — batch processing with up to 30-minute delay
- Not a general-purpose search engine — specifically tuned for Davenport Model B documentation
- Not designed for public-facing scale — internal tool for a small team
- Not auto-pruning — low-confidence graph nodes flagged for manual review, never auto-deleted
- Not a replacement for the machinist's expertise — it's a support tool that surfaces relevant documentation and expert knowledge, guided by the graph

## Analytics & Observability

### Data Stores

| Store | Purpose | Location | Durability |
|-------|---------|----------|------------|
| **JSONL analytics lake** | Activity log — every query, full response metrics | `stj6lw7vswhnnhw` / `analytics/conversations/YYYY/MM/DD.jsonl` | Append-only, one file per day |
| **JSONL feedback lake** | Feedback events mirrored to blob | `stj6lw7vswhnnhw` / `analytics/feedback/YYYY/MM/DD.jsonl` | Append-only |
| **JSONL graph-nodes lake** | Graph classifier selections per query | `stj6lw7vswhnnhw` / `analytics/graph-nodes/YYYY/MM/DD.jsonl` | Append-only |
| **JSONL graph-edges lake** | Graph traversal paths per query | `stj6lw7vswhnnhw` / `analytics/graph-edges/YYYY/MM/DD.jsonl` | Append-only |
| **Table: `feedback`** | User feedback — thumbs up/down/flag, conversation history | `stj6lw7vswhnnhw` | PartitionKey=YYYY-MM-DD, RowKey=turn_id |
| **Table: `graph-verifications`** | Human verification decisions — permanent | `stj6lw7vswhnnhw` | Never auto-deleted |
| **Table: `graph-usage`** | Edge hit/success counters — permanent | `stj6lw7vswhnnhw` | Survives graph rebuilds |
| **Cosmos DB Gremlin** | Machine knowledge graph — queried at runtime | `cosmos-gent-gremlin` / `machine-ontology` | Rebuildable from documents |

### JSONL Conversation Fields (per turn)

Each line in `analytics/conversations/YYYY/MM/DD.jsonl` captures:

| Field | Type | Purpose |
|-------|------|---------|
| `message` | string | User's question (truncated 32KB) |
| `response` | string | Agent's answer (truncated 32KB) |
| `initials` | string | Shop floor technician self-reported identity |
| `username` | string | JWT-authenticated display name |
| `conversation_id` | string | Links multi-turn conversations |
| `duration_ms` | int | Total server-side response time |
| `timing_agent_ms` | int | Foundry agent call time |
| `timing_graph_ms` | int | Graph classifier + traversal time |
| `timing_citations_ms` | int | Citation extraction time |
| `input_tokens` | int | LLM input token count |
| `output_tokens` | int | LLM output token count |
| `sources_cited` | list | Documents the agent cited |
| `source_count` | int | Number of sources cited |
| `graph_starting_names` | list | Ontology nodes the classifier picked |
| `graph_context_provided` | bool | Whether graph context was sent to agent |
| `graph_context_chars` | int | Size of graph context in characters |
| `agent_input_chars` | int | Total context size sent to agent |
| `categories_tagged` | list | Answer categories (Tooling, Machine, etc.) |

### Key Metrics for Managed AIR Reporting

| Metric | How to Compute | What It Tells Us |
|--------|---------------|-----------------|
| **Daily query volume** | Count lines per day in JSONL | Adoption trend |
| **Unique users/day** | Distinct `initials` per day | Breadth of adoption |
| **Satisfaction rate** | Feedback table: thumbs_up / (thumbs_up + thumbs_down + flagged) | Answer quality |
| **Knowledge gaps** | Feedback table: count where rating = flagged or thumbs_down | Content investment priority |
| **Avg response time** | Mean `duration_ms` per day | Performance health |
| **Avg sources cited** | Mean `source_count` per day | Retrieval quality |
| **Graph utilization** | % of queries where `graph_context_provided` = true | V3 graph value |
| **Top graph paths** | graph-usage table: highest hit_count edges | Most valuable knowledge paths |
| **Token cost proxy** | Sum `input_tokens` + `output_tokens` per day | Cost forecasting |

### Accessing Analytics Data

**Admin page** (`admin.html`): Built-in analytics tab shows 30-day summary with bar chart, summary cards (Total Turns, Avg Response Time, Conversations, Active Days), and performance breakdown. Requires admin role.

**API endpoint** (`/api/analytics/summary`): Returns last 30 days of daily aggregates (turn_count, avg_duration_sec, unique_conversations, unique_users, avg_input_tokens, avg_output_tokens).

**Azure CLI** (bulk analysis):
```bash
# Download a specific day's analytics
az storage blob download \
  --account-name stj6lw7vswhnnhw \
  --container-name analytics \
  --name "conversations/2026/03/18.jsonl" \
  --file today.jsonl \
  --auth-mode login

# Parse with Python
python -c "import json; [print(json.loads(l).get('initials','?'), json.loads(l).get('message','')[:80]) for l in open('today.jsonl')]"
```

### UI Trace Panel

The trace panel in the UI (expandable under each response) shows:
- **Collapsed**: duration + mode indicator
- **Expanded**: Agent version, matched component ID, graph context used, timings breakdown, token usage, sources found

## Future Considerations
- **Graph expansion**: Process ALL document types (maintenance manuals, engineering tips, technical tips) — currently only video transcripts + troubleshooting flowcharts
- **Cross-document corroboration**: Automatically bump confidence when multiple independent sources confirm the same relationship
- **Community summaries**: Pre-compute summaries for system-level communities (e.g., "Spindle Assembly commonly fails due to...") — inspired by Microsoft GraphRAG's community summarization
- **Page numbers in citations**: Extract page numbers from PDFs, add to unified index, include in citation links
- **Foundry IQ re-evaluation**: Re-assess when Microsoft resolves MCP latency (currently 43-49s structural)
