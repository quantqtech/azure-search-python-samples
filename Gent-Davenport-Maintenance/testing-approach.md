# Davenport Assistant — Diagnostic Playbook

When someone reports the agent gave a wrong answer or was too slow, follow this guide to diagnose.

## Where the Data Lives

Every conversation turn is logged to blob storage as JSONL:

```
Storage account: stj6lw7vswhnnhw
Container:       analytics
Path:            conversations/{YYYY}/{MM}/{DD}.jsonl
```

Each line is one JSON record with these fields:

| Field | What It Tells You |
|-------|-------------------|
| `message` | What the user asked (up to 4000 chars) |
| `response` | What the agent answered (up to 4000 chars) |
| `sources_cited` | Documents the agent cited (name + URL) |
| `source_count` | How many sources were cited |
| `graph_starting_names` | Which ontology nodes the graph classifier picked |
| `graph_context_provided` | Whether graph context was sent to the agent |
| `categories_tagged` | Answer categories: Tooling, Machine, etc. |
| `duration_ms` | Total server-side time |
| `timing_agent_ms` | Foundry agent call (search + LLM combined) |
| `timing_graph_ms` | Graph classifier + Gremlin traversal |
| `timing_citations_ms` | Citation extraction |
| `input_tokens` / `output_tokens` | LLM token usage |
| `graph_context_chars` | Size of graph context fed to agent |
| `conversation_id` | Links multi-turn conversations together |

### Download Today's Analytics

```bash
az storage blob download \
  --account-name stj6lw7vswhnnhw \
  --container-name analytics \
  --name "conversations/2026/03/24.jsonl" \
  --file today.jsonl \
  --auth-mode login
```

Change the date path as needed. Then view with:

```bash
# Pretty-print all records
cat today.jsonl | python -m json.tool --json-lines

# Find a specific question
grep "thrust bearing" today.jsonl | python -m json.tool --json-lines

# Just see messages and sources
cat today.jsonl | python -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    print(f\"Q: {r['message'][:100]}\")
    print(f\"Sources: {r.get('source_count', 0)} | Duration: {r.get('duration_ms', 0)}ms\")
    print(f\"Graph nodes: {r.get('graph_starting_names', [])}\")
    print()
"
```

---

## Part 1: Quality Diagnosis

**Trigger**: "The agent gave the wrong answer" or "It didn't mention X"

### Step 1: Find the Conversation in Analytics

Download the JSONL for the relevant date. Search by keyword in the `message` field. Look at:

- **`sources_cited`** — Did the agent cite any relevant documents? If it cited nothing about the topic, it's a search problem. If it cited the right docs but still answered wrong, it's a reasoning problem.
- **`graph_starting_names`** — Did the graph route to relevant nodes? If the graph picked unrelated nodes, the classifier may need updating.
- **`response`** — Read the full answer. Does it address the question at all, or did it go off-track?

### Step 2: Search the Index Directly

Check whether the expected content exists in the search index.

**Option A: Azure Portal** (no code)
1. Go to Azure Portal → `srch-j6lw7vswhnnhw` → Indexes → `davenport-kb-unified`
2. Click "Search explorer"
3. Type the key terms (e.g., `extension pin`, `thrust bearing`)
4. Look at what comes back in the `snippet` field

**Option B: Python snippet** (more flexible)

```python
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

client = SearchClient(
    endpoint="https://srch-j6lw7vswhnnhw.search.windows.net",
    index_name="davenport-kb-unified",
    credential=DefaultAzureCredential()
)

results = client.search("extension pin thrust bearing", top=10)
for r in results:
    print(f"Score: {r['@search.score']:.2f}")
    print(f"Source: {r.get('blob_url', 'N/A')}")
    print(f"Snippet: {r['snippet'][:200]}")
    print()
```

### Step 3: Determine Root Cause

| What You Found | Root Cause | Fix |
|----------------|-----------|-----|
| Search returned 0 results for the key terms | **Knowledge gap** — content isn't in the dataset | Add a document to the appropriate blob container, re-run indexer |
| Search found relevant docs but agent didn't cite them | **Jargon/keyword gap** — user's terms don't match what's in the docs | Add term mapping to jargon glossary in `create_direct_search_agent.py`, redeploy agent |
| Agent cited the right docs but answered incorrectly | **Reasoning issue** — system prompt needs refinement | Update agent instructions in `create_direct_search_agent.py`, redeploy |
| Graph routed to wrong nodes (irrelevant `graph_starting_names`) | **Ontology gap** — graph missing vertices or edges for this topic | Update graph in Cosmos DB, or add aliases to existing vertices |
| Agent answered well but user expected a specific fix not in any docs | **Knowledge gap** — real-world fix isn't documented anywhere | Create documentation for the fix, add to blob storage, re-index |

### Step 4: Fix and Verify

**Knowledge gap** (most common):
1. Write a markdown or text doc covering the missing topic
2. Upload to the right blob container (`maintenance-manuals`, `troubleshooting`, etc.)
3. Re-run the indexer: Azure Portal → `srch-j6lw7vswhnnhw` → Indexers → Run
4. Wait for indexer to complete, then search again to confirm the content appears

**Jargon gap**:
1. Edit `create_direct_search_agent.py` — add entry to GENT JARGON GLOSSARY
2. Run `python create_direct_search_agent.py` to push updated instructions to Foundry
3. Test the original question again

**Reasoning issue**:
1. Edit agent instructions in `create_direct_search_agent.py`
2. Redeploy with `python create_direct_search_agent.py`
3. Test with the original question

---

## Part 2: Performance Diagnosis

**Trigger**: "The agent was too slow" or you notice `duration_ms` creeping up

### Step 1: Check the Numbers

Download the JSONL and look at timing fields:

```bash
# Show timing breakdown for all turns today
cat today.jsonl | python -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    total = r.get('duration_ms', 0)
    agent = r.get('timing_agent_ms', 0)
    graph = r.get('timing_graph_ms', 0)
    tokens = r.get('total_tokens', 0)
    graph_chars = r.get('graph_context_chars', 0)
    print(f\"Total: {total/1000:.1f}s | Agent: {agent/1000:.1f}s | Graph: {graph/1000:.1f}s | Tokens: {tokens} | GraphCtx: {graph_chars} chars\")
    print(f\"  Q: {r['message'][:80]}\")
    print()
"
```

### Step 2: Interpret Where Time Went

| Symptom | Likely Cause | What to Check |
|---------|-------------|---------------|
| `timing_graph_ms` > 15s | Graph classifier or Gremlin slow | Cosmos DB serverless cold start? Too many vertices for classifier? |
| `timing_agent_ms` > 45s | Foundry/search bottleneck | Large context? Many search results? Model latency? |
| `total_tokens` > 30,000 | Large context causing slow LLM | Check `graph_context_chars` and `agent_input_chars` — too much context fed in? |
| `graph_context_chars` > 3,000 | Graph traversal returning too many nodes | Traversal depth too high, or starting nodes too broad |
| Turn 1 slow but turn 2+ fast | Cold start | Cosmos DB serverless spins down after inactivity. First call warms it up. |
| All turns slow today but fast yesterday | Service-side issue | Check Azure status page, or Foundry/AOAI service health |

### Performance Baselines

These are typical numbers for healthy operation (as of March 2026):

| Metric | Turn 1 (cold) | Turn 2+ (warm) | Concern Threshold |
|--------|---------------|----------------|-------------------|
| `duration_ms` | 45-60s | 25-35s | > 75s |
| `timing_agent_ms` | 30-45s | 20-30s | > 50s |
| `timing_graph_ms` | 10-15s | 3-8s | > 20s |
| `total_tokens` | 8,000-15,000 | 20,000-35,000 | > 40,000 |
| `graph_context_chars` | 1,500-2,500 | 1,500-2,500 | > 4,000 |

Turn 1 is slower because of Cosmos DB serverless cold start and world model loading. Multi-turn conversations accumulate message history, increasing `total_tokens` each turn.

### Step 3: Run Benchmarks

For deeper investigation, use the existing scripts:

```bash
# Full benchmark — 5 independent questions + 2 multi-turn conversations
python test_graph_timing.py

# Isolate search vs Foundry overhead (bypasses agent entirely)
python test_mcp_latency.py
```

---

## Part 3: Tools Reference

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `test_graph_timing.py` | Benchmark 5 questions + 2 multi-turn convos with full timing | Performance regression testing |
| `test_mcp_latency.py` | Isolate MCP endpoint latency (bypasses Foundry) | "Is search slow or is Foundry slow?" |
| `view_reasoning.py` | Deep dive into agent reasoning and tool calls for one question | Understanding why the agent gave a specific answer |
| `test_agent.py` | Basic agent smoke test | Quick check that agent is responding |
| `diagnose_skillset.py` | Audit skillset auth configuration | After 401 errors on indexer |

---

## Worked Example: CEO's Thrust Bearing Question

**Report**: "They changed the thrust bearing and the extension pin. The extension pin was worn down. The agent didn't suggest this."

### Quality diagnosis

**Step 1 — Analytics**: Downloaded JSONL for March 24. Found two conversations about thrust bearings.
- Conv 1: Multi-turn, user walked through "step on cutoff" → "one spindle" → "cutoff blade looks good" → "could it be the thrust bearing?"
- Conv 2: Direct question "could the extension pin on the thrust bearing cause a step on the cutoff end?"
- Agent cited: Instruction Book Parts 1 & 3, Operations Training Manual Part 4
- Graph selected: `tip_or_burr_on_part_end`, `work_spindle_bearings` — reasonable routing

**Step 2 — Direct index search**:
- Searched for `thrust bearing` → 5 results found (pages about thrust bearing assembly, end play, troubleshooting)
- Searched for `extension pin` → **0 results**

**Step 3 — Root cause**: Knowledge gap. The term "extension pin" does not appear anywhere in the indexed documents. The agent found thrust bearing content and gave a reasonable answer about axial play, but couldn't recommend the specific fix (replacing the worn extension pin) because that information isn't in the dataset.

**Fix**: Need a document covering extension pin wear as a cause of part length issues, uploaded to blob storage and re-indexed.

### Performance diagnosis

From the same analytics records:
- Conv 1, Turn 4: `duration_ms` = 59,486 | `timing_agent_ms` = 44,736 | `timing_graph_ms` = 14,750 | `total_tokens` = 37,574
- Conv 2, Turn 1: `duration_ms` = 73,823 | `timing_agent_ms` = 58,497 | `timing_graph_ms` = 15,326 | `total_tokens` = 13,048

Conv 2 is slower despite fewer tokens — likely Cosmos DB cold start on the graph call (15.3s) plus a fresh Foundry conversation setup. Both are within normal range for first-turn cold starts but on the high side for agent response. Worth monitoring if `timing_agent_ms` trends above 50s consistently.
