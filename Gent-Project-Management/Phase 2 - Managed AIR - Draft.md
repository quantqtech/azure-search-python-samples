# Managed AI Readiness (Managed AIR) — Phase 2
## Gent Machine — Davenport Maintenance Assistant

**Prepared by:** Aidan Systems (subcontractor to MAGNET)
**Date:** March 2026
**Status:** DRAFT — for internal review before MAGNET submission

---

## Context

Phase 1 delivered a production RAG-based maintenance assistant for Davenport machines at Gent Machine's Cleveland facility. The system is live on the shop floor, serving maintenance personnel with source-cited troubleshooting guidance across 1,241 indexed documents.

Phase 2 transitions from **build** to **operate** — ensuring the system continues to improve, knowledge gaps are closed, and the foundation is in place to expand to additional machines and operational areas.

### Current State — Adoption Is Early

The system went live in early March 2026. Usage data from the analytics pipeline shows:

- **154 total queries in March** — the majority from Aidan (development, testing, security hardening)
- **~8 real shop floor queries on 3/18** — one Gent user session asking about thread peaks, thrust bearings, cutoff steps, and short parts
- **Real questions, real misspellings** ("thrush bearim", "differnt brands") — exactly the shop floor use case working as designed
- **Knowledge gaps surfaced immediately** — the extension pin question proved the system works but needs more content

**This is pre-adoption.** The system answers well when content exists, but the knowledge base needs expansion to cover more scenarios before daily shop floor use becomes natural. Phase 2 is about closing that gap — making the system good enough that machinists reach for it first.

## Why Managed AIR (Not Self-Service)

The maintenance assistant is only as good as its knowledge base. Keeping it healthy requires:

- **Diagnosing knowledge gaps** — When a user gets an incomplete answer, determining whether the issue is missing content, missing jargon mapping, a retrieval problem, or an agent behavior issue. Users can flag problems; they cannot diagnose root cause.
- **Curating content** — New documents must be structured for optimal chunking, indexed correctly, and verified against real queries. Uploading a PDF is 10% of the work.
- **Maintaining the agent** — Jargon glossary updates, instruction tuning, and answer quality monitoring require expertise in the system's architecture.
- **Protecting answer quality** — Unvetted or outdated content on a shop floor is a liability, not a feature.

**Real example:** A user asked about part length issues. The system correctly cited thrust bearing content but couldn't recommend the extension pin replacement — that fix wasn't in the knowledge base. Diagnosing this required checking the search index (1,241 chunks), the graph ontology (570 vertices), and the agent instructions. The resolution: create new content covering extension pins, update the jargon glossary, re-index, and verify. This is skilled operations work, not a self-service upload.

---

## Service Tiers — Small / Medium / Large

All tiers include Azure infrastructure management and SOC 2 compliance overhead. The difference is the amount of proactive knowledge operations and adoption support.

### Small — Keep the Lights On
**$800/month** (Aidan fee to MAGNET)

For months when the system is running well and Gent needs minimal support.

| What's Included | Hours |
|-----------------|-------|
| Azure infrastructure management, monitoring, security, patching | — |
| SOC 2 compliance controls and evidence collection | — |
| Feedback triage — review flags/thumbs-down from admin dashboard | 0.5 hr |
| Monthly usage summary (query volume, trends, gaps) | 0.5 hr |
| Minor agent adjustments (small jargon additions, instruction tweaks) | 1 hr |
| **Total included support** | **2 hrs** |

**Additional support:** $200/hr as needed

**Best for:** Quiet months with low feedback volume, no new content needs.

### Medium — Build Adoption
**$1,500/month** (Aidan fee to MAGNET)

For months focused on expanding the knowledge base and driving shop floor adoption. **This is the recommended starting tier** — the system needs content investment to reach daily-use quality.

| What's Included | Hours |
|-----------------|-------|
| Everything in Small | 2 hrs |
| Proactive knowledge gap analysis — identify what's missing before users hit it | 1.5 hrs |
| Content creation — write or co-author 1-2 new KB articles with Dave/SME | 2 hrs |
| Agent tuning — jargon glossary, instruction refinement, answer quality review | 1 hr |
| Re-indexing, verification, and regression testing after changes | 0.5 hr |
| Monthly adoption check-in call with Gent stakeholders | 1 hr |
| **Total included support** | **8 hrs** |

**Additional support:** $200/hr as needed

**Best for:** Active improvement months. The first 3-6 months should be Medium to build the knowledge base to the point where adoption takes off.

### Large — Deep Investment
**$2,500/month** (Aidan fee to MAGNET)

For months with major content expansion, search quality optimization, or preparing for a new machine type.

| What's Included | Hours |
|-----------------|-------|
| Everything in Medium | 8 hrs |
| Intensive content sprint — 3-5 new KB articles or major knowledge area buildout | 3 hrs |
| Search quality audit — systematic query testing, retrieval tuning, citation accuracy | 1.5 hr |
| Graph ontology expansion (V3) — new nodes, edges, confidence calibration | 1.5 hrs |
| Quarterly roadmap review — prioritize next areas, plan expansion | 1 hr |
| **Total included support** | **15 hrs** |

**Additional support:** $200/hr as needed

**Best for:** Months with a specific improvement initiative (e.g., "this month we're adding all the tooling content Dave has in his head").

---

## Tier Summary

| | Small | Medium | Large |
|---|---|---|---|
| **Monthly fee** | $800 | $1,500 | $2,500 |
| **Included hours** | 2 | 8 | 15 |
| **Effective rate** | $200/hr* | $137/hr | $140/hr |
| **Infrastructure** | Included | Included | Included |
| **SOC 2 compliance** | Included | Included | Included |
| **Proactive improvement** | No | Yes | Yes + deep |
| **Adoption check-in call** | No | Monthly | Monthly |

*Small tier: $400 infra + $400 for 2 hrs. Medium/Large tiers discount the hourly rate as commitment increases.*

**Tier flexibility:** Gent can move between tiers month-to-month with 15-day notice. Recommended pattern: start Medium for 3-6 months to build the knowledge base, then drop to Small once adoption is self-sustaining and knowledge gaps are rare.

*Note: All fees are Aidan's rates to MAGNET. MAGNET applies their own markup to Gent.*

---

## System Expansion — New Machines or Operational Areas

Adding new machine types (beyond Davenport) or new operational domains (quality, scheduling, inventory) to the platform.

| Expansion Type | Fee | What's Included |
|----------------|-----|-----------------|
| **New machine type or system** | **$10,000** | Knowledge capture (interviews, document ingestion), index build/update, agent configuration, jargon mapping, ontology extension, testing and verification |

Expansion projects leverage the existing Azure infrastructure — Search, Foundry, Storage, Functions are already provisioned and running. The $10,000 covers the **knowledge engineering and agent work**, not new infrastructure. Each additional system added to the platform has a lower marginal cost than building from scratch.

**Incentive structure:** The monthly base fee covers ALL systems on the platform. One machine type at $1,500/month Medium = $18,000/year. Three machine types at the same $1,500/month = $6,000/year per system. The infrastructure scales; the base doesn't.

---

## Azure Infrastructure — What's Running

Current Azure actual cost: **~$130/month** ($1,560/year)

| Service | Monthly Cost | Purpose |
|---------|-------------|---------|
| Azure Cognitive Search | ~$70 | Unified search index (1,241 docs), Basic tier |
| Azure Container Apps | ~$24 | Foundry agent runtime |
| Azure App Service | ~$16 | Static Web App hosting |
| Container Registry | ~$5 | Container images |
| Foundry Models (AOAI) | ~$3-27* | gpt-4.1-mini (agent) + gpt-5-mini (utility) + embeddings (usage-based) |
| Storage | ~$0.25 | Blob storage, Table Storage, analytics lake |
| Cosmos DB | ~$0.04 | Graph ontology (serverless — near-zero when idle) |
| Functions | $0.00 | API layer (Flex Consumption — pay per execution) |

*Foundry Models cost scales with usage. $3/month at current low adoption; will increase as usage grows but remains modest — both models are inexpensive per query.*

Infrastructure fee ($400/month in all tiers) covers: hosting, monitoring, security patching, SOC 2 compliance controls, SLA accountability, and cost management. Not a pass-through — reflects the operational overhead of maintaining a production AI system in a compliant environment.

---

## Analytics & Metrics — How We Measure

The system has a built-in analytics pipeline that captures every interaction:

| Data Store | What's Captured | Location |
|------------|----------------|----------|
| **JSONL analytics lake** | Every query: message, response, timing, sources cited, token usage, graph context | `stj6lw7vswhnnhw` / `analytics/conversations/YYYY/MM/DD.jsonl` |
| **Table Storage: `feedback`** | User ratings (thumbs up/down/flag), notes, conversation history | `stj6lw7vswhnnhw` |
| **Table Storage: `graph-usage`** | Edge hit counters — which knowledge paths get used most | `stj6lw7vswhnnhw` |
| **Table Storage: `graph-verifications`** | Expert verification decisions — permanent record of human knowledge | `stj6lw7vswhnnhw` |

### Key Metrics Tracked

| Metric | Source | What It Tells Us |
|--------|--------|-----------------|
| **Query volume** (daily/weekly/monthly) | JSONL analytics | Adoption trend — are more people using it more often? |
| **Unique users** (by initials) | JSONL analytics | Breadth of adoption across the shop floor |
| **Satisfaction rate** (thumbs up vs. down vs. flag) | Feedback table | Answer quality — are responses useful? |
| **Knowledge gaps flagged** | Feedback table (flagged + thumbs-down) | Content investment needed |
| **Response time** (duration_ms) | JSONL analytics | Performance — is the system fast enough for shop floor use? |
| **Sources cited per response** | JSONL analytics | Retrieval quality — is the search finding relevant content? |
| **Graph hit counters** | graph-usage table | Which knowledge paths are most valuable; where to invest next |
| **Token usage** (input + output) | JSONL analytics | Cost forecasting as usage scales |

### Monthly Report (included in all tiers)

Each month's usage summary includes:
1. Query volume and trend (up/down/flat vs. prior month)
2. Unique users and session patterns
3. Satisfaction breakdown (thumbs up / down / flagged)
4. Top knowledge gaps identified (from flags and failed queries)
5. Response time averages and any performance issues
6. Azure cost actuals vs. budget
7. Recommendations for next month (content priorities, agent tuning, adoption actions)

---

## Adoption-First Approach

This pricing is designed to **minimize the barrier to continued operation** while driving adoption:

- **Start Medium, drop to Small** — invest in content quality first, reduce support once adoption is self-sustaining
- **No long-term lock-in** — 3-month initial commitment, then month-to-month
- **Tier flexibility** — move between Small/Medium/Large monthly based on need
- **Expansion is incremental** — $10k to add a new machine type, not a new platform build
- **Value compounds** — every knowledge gap closed makes the system permanently better; every new system added reduces per-system cost
- **$800/month floor** is less than 2 hours of unplanned downtime on a Davenport machine

---

## Expected Cost by Phase

| Phase | Duration | Recommended Tier | Monthly (Aidan) | Purpose |
|-------|----------|-----------------|-----------------|---------|
| **Adoption sprint** | Months 1-3 | Medium ($1,500) | $1,500 | Build knowledge base, drive first-use adoption, close top gaps |
| **Steady improvement** | Months 4-6 | Medium ($1,500) | $1,500 | Continue content expansion, establish usage patterns |
| **Sustain** | Month 7+ | Small ($800) | $800 | Maintain, monitor, respond to occasional gaps |
| **Expansion** (when ready) | As needed | Large ($2,500) + $10k project | $2,500 + project | Add new machine type or operational area |

**Year 1 estimate (Aidan fees):** ~$13,800 (6 months Medium + 6 months Small)

---

## Term and Invoicing

- **Initial term:** 3 months at Medium tier (recommended to establish adoption momentum)
- **After initial term:** Month-to-month, 15-day notice to change tier or cancel
- **Invoicing:** Monthly in advance (tier fee) + monthly in arrears (any overage hours at $200/hr)
- **Expansion projects:** Scoped and invoiced separately, 50% at kickoff / 50% at completion
- **Azure costs:** Included in all tiers (not billed separately)

---

## What This Does NOT Include

- Net-new application development (new UIs, integrations, APIs)
- Migration to a different Azure tenant
- Teams or Copilot integration (Phase 3 backlog)
- Image/drawing recognition capabilities (Phase 3 backlog)
- Advanced enterprise security (Private Link, complex RBAC) beyond current pilot controls

These items can be scoped as expansion projects or a future Phase 3 SOW.

---

## Summary for MAGNET Discussion

| Item | Aidan Fee |
|------|-----------|
| **Small** — infrastructure + 2 hrs support | $800/month |
| **Medium** — infrastructure + 8 hrs proactive improvement | $1,500/month |
| **Large** — infrastructure + 15 hrs deep investment | $2,500/month |
| Additional support (any tier) | $200/hour |
| New machine/system expansion | $10,000 per system |
| Initial commitment | 3 months (Medium recommended) |

**Key message to Gent:** The system is built and working — real machinists asked real questions and got useful, cited answers on day one. But it's early. The knowledge base needs investment to cover more scenarios before it becomes the first thing a machinist reaches for. This phase makes the system smarter every month, with a clear path to expand to other machines when you're ready. The more you put in, the more it compounds.
