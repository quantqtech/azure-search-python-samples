# INTERNAL — Aidan Cost Model
## DO NOT SHARE WITH MAGNET OR GENT

**Date:** March 2026
**Purpose:** Real cost-to-serve for pricing decisions and margin analysis

---

## Per-Customer Azure Run Cost (Gent baseline)

Actual Azure spend on Gent Manufacturing subscription (`09d43e37-e7dc-4869-9db4-768d8937df2e`):

| Service | Jan 2026 | Feb 2026 | Mar 2026 (proj.) | Notes |
|---------|----------|----------|-----------------|-------|
| Azure Cognitive Search (Basic) | $84.85 | $69.83 | ~$74 | Fixed — Basic tier, always on |
| Azure Container Apps | $8.80 | $23.71 | ~$24 | Foundry agent runtime |
| Azure App Service | $1.60 | $11.02 | ~$20 | Web app hosting |
| Container Registry | $5.47 | $4.66 | ~$5 | Container images |
| Foundry Models (AOAI) | $1.14 | $26.72 | ~$3 | Usage-based — Feb spike was dev/testing |
| Foundry Tools | $12.74 | $0.70 | ~$0 | Minimal after build phase |
| Cosmos DB | $22.84 | $0.02 | ~$0.04 | Serverless — near-zero at idle |
| Storage | $0.01 | $0.18 | ~$0.25 | Blobs, tables, analytics |
| Functions | $0.00 | $0.00 | $0.00 | Flex Consumption — pay per execution |
| Bandwidth | $0.00 | $0.03 | ~$0.00 | Negligible |
| **Total** | **$137.46** | **$136.87** | **~$127** | |

**Steady-state Azure cost: ~$125-135/month per customer** (at Gent's scale — Basic search tier, low usage).

### Azure Cost Scaling Notes

| If usage grows... | Impact |
|---|---|
| More queries (adoption increases) | Foundry Models goes up — but GPT-5-mini is cheap. 10× queries ≈ +$20-30/month |
| More documents indexed | Search stays Basic tier up to ~15,000 docs. Beyond that: Standard tier = ~$250/month |
| More work centers on same platform | Minimal — same search index, same infrastructure. Maybe +$5-10/month storage |
| Second customer on separate subscription | Same ~$125-135/month baseline per customer |

---

## Aidan Overhead Allocation

### SOC 2 Compliance

| Item | Annual Cost | Monthly |
|------|------------|---------|
| Drata platform | $8,400 | $700 |
| Annual audit | $5,000 | $417 |
| **Total SOC 2** | **$13,400** | **$1,117** |

**Per-customer allocation** depends on portfolio size:

| Customers | SOC 2 per customer/month |
|-----------|-------------------------|
| 1 (Gent only) | $1,117 |
| 3 | $372 |
| 5 | $223 |
| 10 | $112 |

*SOC 2 is fixed cost — more customers = lower per-customer burden. At 1 customer, it's painful. At 5+, it's manageable.*

### Tooling & Infrastructure (Aidan internal)

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| Claude Code / AI development tools | ~$200 | Estimate — development tooling |
| GitHub / Azure DevOps | ~$50 | Source control, CI/CD |
| Domain, email, misc SaaS | ~$50 | Business operations |
| **Total tooling** | **~$300** | |

### Quentin's Time (Opportunity Cost)

This is the biggest real cost. Pricing is now point-based ($1,500/story point), but Quentin's time opportunity cost is still roughly $200/hr equivalent:

| Phase | Monthly Fee |
|-------|------------|
| Hyper Care — WHEELS UP / Adopt | $2,000 |
| Climb — CLIMBING / Expand | $1,600 |
| Cruise — CRUISING / Compound | $800 |

*No hour caps, no overage rates. These are a journey, not tiers — every customer follows Hyper Care → Climb → Cruise as the system matures. Time spent on a customer is opportunity cost — hours spent on Gent are hours not spent on other revenue or business development.*

---

## Margin Analysis — Per Customer

### Gent — Journey-Based Margin Analysis

Year 1 journey: 3 months Hyper Care ($2,000/mo) + 6 months Climb ($1,600/mo) + 3 months Cruise ($800/mo) = **$18,000/year** ($1,500/mo average).

#### Hyper Care Phase ($2,000/month from MAGNET) — Months 1-3

| Line Item | Monthly Cost | Notes |
|-----------|-------------|-------|
| Azure infrastructure | $130 | Actual cloud spend |
| SOC 2 allocation (1 customer) | $1,117 | Drops fast with more customers |
| Tooling allocation | $150 | Half of $300 (shared across business) |
| **Total hard cost** | **$1,397** | |
| **Revenue from MAGNET** | **$2,000** | |
| **Margin (hard costs only)** | **+$603 (30%)** | **Positive from month 1** |

#### Climb Phase ($1,600/month from MAGNET) — Months 4-9

| Line Item | Monthly Cost | Notes |
|-----------|-------------|-------|
| Azure infrastructure | $130 | |
| SOC 2 allocation (1 customer) | $1,117 | |
| Tooling allocation | $150 | |
| **Total hard cost** | **$1,397** | |
| **Revenue from MAGNET** | **$1,600** | |
| **Margin (hard costs only)** | **+$203 (13%)** | **Thin at 1 customer** |

#### Cruise Phase ($800/month from MAGNET) — Month 10+

| Line Item | Monthly Cost | Notes |
|-----------|-------------|-------|
| Azure infrastructure | $130 | |
| SOC 2 allocation (1 customer) | $1,117 | |
| Tooling allocation | $150 | |
| **Total hard cost** | **$1,397** | |
| **Revenue from MAGNET** | **$800** | |
| **Margin (hard costs only)** | **-$597** | **Negative at 1 customer — must scale** |

#### Year 1 Blended (1 customer)

| Metric | Value |
|--------|-------|
| Total revenue | $18,000 ($1,500/mo avg) |
| Total hard costs | $16,764 ($1,397/mo × 12) |
| **Year 1 margin** | **+$1,236** |

*Better than old model ($14,400 revenue vs same $16,764 costs = -$2,364). The Hyper Care phase front-loads revenue when Aidan effort is highest.*

**With 3 customers (Year 1 avg $1,500/mo each):**

| Line Item | Monthly Cost (per customer) |
|-----------|----------------------------|
| Azure | $130 |
| SOC 2 allocation (3 customers) | $372 |
| Tooling allocation (3 customers) | $100 |
| **Total hard cost** | **$602** |
| **Average revenue** | **$1,500** |
| **Margin** | **+$898 (60%)** |

**With 5 customers (Year 1 avg $1,500/mo each):**

| Line Item | Monthly Cost (per customer) |
|-----------|----------------------------|
| Azure | $130 |
| SOC 2 allocation (5 customers) | $223 |
| Tooling allocation (5 customers) | $60 |
| **Total hard cost** | **$413** |
| **Average revenue** | **$1,500** |
| **Margin** | **+$1,087 (72%)** |

### Key Insight: Journey Model Improves Early Economics

The old model (6 × $1,600 + 6 × $800 = $14,400) was negative at 1 customer. The journey model (3 × $2,000 + 6 × $1,600 + 3 × $800 = $18,000) is marginally positive at 1 customer and front-loads revenue when Aidan effort is highest. Margins still improve significantly at scale — the business model really works at 3+ customers where SOC 2 is spread across the portfolio and margins hit 60%+.

**Gent's strategic value isn't the monthly margin — it's:**
1. Reference implementation for MAGNET to sell to others
2. Proving the Managed AIR model works
3. Building reusable patterns that make customer #2-5 cheaper to deliver
4. Case study and portfolio credibility

---

## Phase 1 Economics (for future deployments)

### Build Cost to Aidan (Gent — actual)

Phase 1 was scoped at 24 story points × 6 hrs/point = **144 hours**.
MAGNET paid $36,000 ($1,500/story point). Aidan's effective rate: **$250/hr**.

| Category | Est. Hours | Notes |
|----------|-----------|-------|
| Knowledge capture & interviews | 18 | Onsite with Dave, document collection |
| Azure provisioning & configuration | 12 | Search, Foundry, Storage, Functions, Cosmos DB |
| Knowledge base build & indexing | 24 | Chunking, embedding, unified index (1,241 docs) |
| Agent configuration & tuning | 18 | Instructions, jargon glossary, answer structure |
| Cockpit UI & admin | 30 | Shop floor app, admin page, user management |
| Analytics pipeline | 16 | JSONL lake, feedback table, analytics API, admin charts |
| Security hardening | 12 | Auth, XSS, OData injection, rate limiting, input validation |
| Testing & go-live | 14 | End-to-end testing, deployment, onsite training |
| **Total Phase 1 effort** | **~144 hrs** | |

**Phase 1 price to MAGNET: $36,000** (actual — MEP funded)
**Future Phase 1 price to MAGNET: $20,000** (reduced because platform is built)

### Future Phase 1 Deployments (with reusable platform)

Template backlog created in Azure DevOps: **Epic #7206 — "Template: Shop Floor Knowledge Base - Phase 1"**

The cockpit, analytics pipeline, security hardening, auth, and admin UI are built. Future deployments reuse ~60% of the codebase. What's always custom: knowledge capture, KB build, graph, agent tuning.

**CONFIGURE / Configure & Deploy (5 pts / ~30 hrs)**

| Story | Pts | Hrs | Reuse |
|-------|-----|-----|-------|
| Provision Azure infrastructure | 1 | 6 | High — scripted from Gent |
| Conduct expert interviews & transcription | 2 | 12 | Low — always custom |
| Ingest & process customer documents | 2 | 12 | Partial — pipeline exists, but customer docs always have surprises |

**TAXI / Train & Tune (6 pts / ~36 hrs)**

| Story | Pts | Hrs | Reuse |
|-------|-----|-----|-------|
| Configure & deploy cockpit and admin | 1 | 6 | High — deploy existing codebase |
| Security hardening & production readiness | 1 | 6 | High — patterns established |
| Build knowledge graph for customer domain | 2 | 12 | Low — schema reusable, content is domain-specific |
| Tune search & agent for customer language | 1 | 6 | Partial — framework reusable, jargon is custom |
| Test with customer team on shop floor | 1 | 6 | None — always custom |

**Total: 11 story points × 6 hrs = 66 hours**

| Metric | Gent (first) | Customer #2+ (template) |
|--------|-------------|------------------------|
| Story points | 24 | 11 |
| Hours | 144 | 66 |
| Price to MAGNET | $36,000 | $20,000 |
| Effective rate | $250/hr | $303/hr |
| Reduction | — | 54% fewer hours |

**Customer #2+ Phase 1 cost to Aidan: 66 hrs × $200/hr = ~$13,200**
**Price to MAGNET: $20,000**
**Margin on Phase 1 (customer #2+): ~$6,800 (34%)**

*This is where "configure, not build" pays off. The platform IS built. Each new customer is configuration + knowledge engineering.*

---

## New Leg (Work Center Expansion) Economics

| Item | Points | Cost (at $1,500/pt) |
|------|--------|---------------------|
| Knowledge capture | 2 | $3,000 |
| Index expansion & agent reconfig | 2 | $3,000 |
| Ontology extension | 1.5 | $2,250 |
| Testing & verification | 1.5 | $2,250 |
| **Total** | **7 pts** | **$10,500** |

**Price to MAGNET: $10,500**
**Estimated delivery cost: ~$4,400** (based on Gent baseline ~22 hrs)
**Margin: ~$6,100 (58%)**

---

## Portfolio Scenario — Year 1

| Scenario | Revenue (Aidan) | Hard Costs | Quentin's Hours | Margin (pre-labor) |
|----------|----------------|------------|----------------|-------------------|
| **Gent only (current)** | $18,000 | $16,764 | ~96 hrs (Phase 2 only) | **+$1,236** |
| **Gent + 2 new customers** | $18,000 + $40,000 + $36,000 = $94,000 | ~$35,000 | ~336 hrs (Gent 96 + 2×(70 Phase 1 + 50 Phase 2)) | **+$59,000** |
| **Gent + 4 new customers** | $18,000 + $80,000 + $72,000 = $170,000 | ~$55,000 | ~576 hrs | **+$115,000** |

*Assumes new customers: $20k Phase 1 (~70 hrs) + 12 months journey ($18,000/year = 3 mo Hyper Care + 6 mo Climb + 3 mo Cruise, ~50 hrs/year). Gent: 3 mo Hyper Care + 6 mo Climb + 3 mo Cruise (~96 hrs/year).*

**Breakeven: ~2 customers** (where SOC 2 and overhead are covered and Quentin's time starts generating real margin).

### The Hours Reality Check

At 1 customer (Gent), Phase 2 is ~96 hrs/year — very manageable.

Adding 2 customers means ~336 hours/year total — roughly 7 hrs/week. Still solo-feasible.

At 5 customers, you're at ~550+ hours/year (~11 hrs/week on delivery). That's where you start thinking about a contractor or part-time hire for the routine work (feedback triage, reports, content creation) while you focus on sales, architecture, and customer relationships.

**Phase 1 is the bottleneck.** At 70 hrs per new customer deployment, taking on 2 simultaneously means 140 hrs in an 8-10 week window (~15-18 hrs/week on builds alone). Stagger deployments or bring in help.

---

## Pricing Guardrails

| Rule | Rationale |
|------|-----------|
| **All pricing at $1,500/story point** | Consistent unit of work across all offerings. The point is the brand. |
| **$800/month minimum (Cruise phase)** | Below this, Azure + SOC 2 allocation makes it unprofitable |
| **Phase 1 minimum $20k** | Even with reuse, knowledge capture is always custom labor |
| **New Leg minimum $10,500** (7 pts) | 22+ hours of skilled work; below this is underpriced |
| **Azure costs included, never broken out** | Customers don't need to see $130/month — it invites "why am I paying $400 for infrastructure?" |
| **SOC 2 never shown as line item** | Baked into infrastructure fee — it's a cost of doing business, not a billable |

---

## When to Revisit This Model

- When Azure costs change materially (e.g., Search tier upgrade, higher usage)
- When adding customer #3 (SOC 2 allocation drops significantly)
- When Quentin is no longer the sole delivery resource (need to model employee/contractor costs)
- Annually — to verify SOC 2 and tooling costs haven't drifted
