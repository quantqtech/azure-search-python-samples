# Phase 2: Managed AIR — Statement of Work
## Gent Machine — Davenport Maintenance Assistant

**Prepared by:** Aidan Systems (subcontractor to MAGNET)
**Date:** March 2026
**Status:** DRAFT

---

## Background

Phase 1 delivered a production AI maintenance assistant for Davenport Model B screw machines at Gent Machine's Cleveland facility. The system is live — 1,241 indexed documents, a 570-vertex machine knowledge graph, and a shop floor web application with built-in feedback and analytics.

On March 18, 2026, a Gent machinist used the system for real troubleshooting — asking about flat thread peaks, thrust bearing replacement, cutoff steps, and short parts. The system delivered cited, step-by-step guidance. It also revealed knowledge gaps: questions about extension pins and specific brand comparisons weren't in the knowledge base.

**The system works. It needs more knowledge and more pilots.**

Phase 2 transitions from **Configure & Deploy** to **Train & Tune** — getting every machinist into the cockpit, expanding the knowledge base, and coaching the team through adoption into daily reliance.

---

## The Flight Path — Where Gent Is Now

Aidan's engagement model follows six stages. Each has a flight term (the brand) and a business term (the conversation):

| Stage | Flight | Business | What's Happening |
|---|---|---|---|
| 0 | **PRE-FLIGHT** | **Assess** | Evaluate the operation, build the roadmap |
| 1 | **CONFIGURE** | **Configure & Deploy** | Configure the AI platform for this operation and deploy to the shop floor |
| 2 | **TAXI** | **Train & Tune** | Train the team, tune the agent to their language, validate with real questions |
| 3 | **WHEELS UP** | **Adopt** | Team is using it and telling us what's missing |
| 4 | **CLIMBING** | **Expand** | More knowledge, more users, more value |
| 5 | **CRUISING** | **Compound** | Daily operations run on it — every month it gets smarter |

### Gent's Current Position

| Stage | Status |
|---|---|
| PRE-FLIGHT / Assess | Complete (Phase 1 scoping) |
| CONFIGURE / Configure & Deploy | Complete (Phase 1 delivery) |
| TAXI / Train & Tune | **Complete** — Aidan conducted onsite training with the team. Machinists have used the system for real troubleshooting (3/18 session: thread peaks, thrust bearings, cutoff steps, short parts). |
| WHEELS UP / Adopt | **In progress** — System is being used but not yet a daily habit. Knowledge gaps being identified. Dave (retired expert) knowledge captured but team needs more content to build trust. |
| CLIMBING / Expand | Future |
| CRUISING / Compound | Future |

**Phase 2 picks up at WHEELS UP** — driving adoption from occasional use to daily habit, expanding the knowledge base, and building toward the growth goal: enabling Gent to staff and run more Davenports.

---

## The Industrial Pilot Framework

Drawing on the **Industrial Athlete Operating System** (Lamoncha & Figley, NAM Manufacturer of the Year — Ohio manufacturing), extended by Aidan into the cockpit:

| Traditional | Industrial Athlete | Industrial Pilot (Aidan) |
|---|---|---|
| **Manager** — controls | **Coach** — develops | **Flight Instructor** — teaches them to fly solo |
| **Employee** — does tasks | **Athlete** — performs | **Pilot** — navigates independently with AI |
| **Workplace** — clock in | **Performance Center** — excel | **Airframe** — the AI platform that everything runs on |
| **Egosystem** — silos | **Ecosystem** — collaboration | **Airspace** — shared knowledge, governed, connected |
| **Time Card** | **Visual Earnings** — scoreboard | **Altitude Report** — performance visibility across all cockpits |

### Roles

| Role | Who | What They Do |
|---|---|---|
| **Flight Instructor** | Aidan (Managed AIR) | Coaches adoption, diagnoses gaps, calibrates instruments, teaches the team to fly |
| **Pilot** | Machinist | Navigates with AI instruments, reports what's working and what's not |
| **Co-Pilot** | The AI system | Always present, provides guidance and citations — but the human makes the calls |
| **Ground Crew** | Senior machinists / Rich | Contribute operational knowledge, validate content, identify what's missing |

*Note: Dave (Gent's longtime expert) has retired. His knowledge was captured in Phase 1. The system now carries that expertise — the Ground Crew role shifts to Gent's current senior operators and leadership.*

---

## Phase 2 Plan — Stage by Stage

### Completed: TAXI / Train & Tune ✓

Aidan conducted onsite training with Gent's team. Machinists used the system for real troubleshooting. Knowledge gaps were identified (extension pin, brand comparisons, oil specifications). The team knows how to use the cockpit.

---

### Months 1-3: WHEELS UP / Adopt
*"It's where they go first — not last."*

The system works. The team has been trained. The challenge now is **habit formation** — moving from "I'll try it when I remember" to "I check the cockpit before I do anything else." This requires three things: the system needs to answer well enough that it earns trust, the team needs visibility into how it's helping, and leadership needs to set the expectation.

#### Making the Cockpit Unavoidable

| Activity | Description | Who |
|----------|-------------|-----|
| **"Ask the Cockpit First" — as a team expectation** | Rich tells his team: before you escalate, check the system. If it helps, great. If it doesn't, flag it — that's how we make it better. This isn't a suggestion; it's how we work now. | Rich (with Aidan coaching) |
| **Shop floor display board** | Printed weekly — posted where everyone sees it. Shows: queries this week, best Q&A, knowledge gap closed, team stats. Makes the system visible even when nobody's at the terminal. | Aidan prepares, Gent posts |
| **Fix the known gaps — fast** | Extension pin, oil specifications, thrust bearing brands, and any other gaps from the 3/18 session. If a machinist tries the system and hits a gap they already reported, trust erodes. Close these first. | Aidan (Flight Instructor) |

#### Building Trust Through Quality

| Activity | Description | Who |
|----------|-------------|-----|
| **Content sprint — top 10 scenarios** | Work with Rich and senior machinists to identify the 10 most common troubleshooting scenarios. Verify the system handles each one well. Fill gaps. | Aidan + Gent senior operators |
| **Agent tuning for Gent's language** | Real machinists misspell things ("thrush bearim"), use shorthand, and describe problems differently than manuals do. Tune the agent to handle how Gent's team actually talks. | Aidan (Flight Instructor) |
| **"Did this help?" follow-up** | When a machinist uses the system, check in casually: "Did that answer work?" This isn't surveillance — it's coaching. Their feedback identifies gaps faster than the thumbs-up button. | Rich / shift leads |

#### Making Contribution Easy

| Activity | Description | Who |
|----------|-------------|-----|
| **Flag + notes — type what the system missed** | When a machinist gets a bad or incomplete answer, flag it and type a short note: "extension pin was the real fix" or "wrong torque spec." Even a few words helps Aidan close the gap. | All machinists |
| **Dave reviews on his phone** | Dave is retired but still accessible. He can use the app on his phone to review answers, flag what's wrong, and add corrections. Aidan also conducts periodic interviews with Dave to capture specific knowledge areas. | Dave (remote, on his schedule) |
| **"What would Dave have said?"** | Show senior machinists the system's answer to a real question. Ask: "Is this right? What's missing?" Their corrections go straight into the knowledge base. | Aidan + senior machinists |
| **Flag = contribution, not complaint** | Reframe flagging a bad answer as helping the team, not criticizing the system. Every flag makes the cockpit smarter for everyone. Recognize it. | Rich reinforces the culture |

#### Coaching Cadence

| Activity | Frequency | Description |
|----------|-----------|-------------|
| **Biweekly check-in with Rich** | Every 2 weeks | 15 minutes. "Here's what your team asked. Here's what worked. Here's what we fixed. Here's what's still missing." Not a status call — a coaching session. |
| **Monthly Altitude Report** | Monthly | Posted on the shop floor AND sent to Rich. Adoption progress, satisfaction, gaps closed, team contributions. Framed as team achievement. |
| **Knowledge gap triage** | Weekly | Aidan reviews flags, thumbs-down, and typed notes. Prioritizes and closes gaps. The faster gaps close, the faster trust builds. |

**Targets:**
- 2+ queries per machinist per week by end of month 2
- 70%+ of the top 10 troubleshooting scenarios well-covered in the KB
- Feedback flowing regularly (flags, thumbs, typed notes)
- Rich actively reinforcing "Ask the Cockpit First"

**What success looks like at the end of WHEELS UP:** A machinist has a problem → they walk to the terminal first → they get a useful answer most of the time → when they don't, they flag it and it gets fixed within days. The cockpit is becoming the default, not the afterthought.

---

### Months 4-6: CLIMBING / Expand
*"The system is earning trust — and enabling growth."*

By now the knowledge base covers common scenarios, usage is regular, and the team trusts the cockpit. This is where the growth story begins.

| Activity | Description | Who |
|----------|-------------|-----|
| **Add setup procedures to the KB** | Not just troubleshooting — setup, changeover, and adjustment procedures. This is what enables a less experienced operator to set up a machine. | Aidan + Gent senior operators |
| **Altitude Report live** | Leaderboard, personal stats, team progress — visible in the system. Points for queries (1), feedback (2), flags that become content (5). | Aidan builds, team uses |
| **Content sprint — deep areas** | Systematic expansion into areas the top 10 didn't cover. Driven by what machinists are actually asking and flagging. | Aidan (Flight Instructor) |
| **Graph ontology expansion** | New knowledge graph nodes and edges for areas machinists are asking about — improves search relevance. | Aidan (Flight Instructor) |
| **Monthly Altitude Report** | Team achievement focus — adoption curve, knowledge growth, "the system answered X more questions this month than last." | Aidan prepares, posted on floor |
| **Growth planning** | Begin the conversation: which additional Davenport jobs could a junior hire handle with cockpit support? What setup content would they need? | Rich + Aidan |
| **Expansion scoping** | If the growth path is clear, scope a New Leg ($10,500) to add new job types or machine configurations. | Aidan + MAGNET |

**Targets:**
- 5+ queries per week per machinist
- 70%+ satisfaction rate
- Setup procedures indexed for top job types
- Growth conversation underway — path to additional Davenport(s) identified

---

### Month 7+: CRUISING / Compound
*"It runs. It compounds. It grows the business."*

The system is comprehensive for Davenport operations. Usage is daily. The team trusts it. Now it's about maintaining altitude and enabling growth.

| Activity | Description |
|----------|-------------|
| **Monthly Altitude Report** | Usage trends, satisfaction, cost, recommendations |
| **Infrastructure health** | Azure monitoring, security, SOC 2 compliance |
| **Minor adjustments** | Jargon additions, instruction tweaks, content updates |
| **New hire onboarding** | When Gent hires a junior machinist, the cockpit is part of their day-one toolkit. Flight Instructor monitors their query patterns to identify gaps. |
| **Expansion execution** | Configure New Legs ($10,500 each) as Gent grows into additional capacity |

**Targets:**
- 80%+ weekly active machinists
- 75%+ satisfaction rate
- New hires productive on basic jobs within weeks, not months
- Additional Davenport(s) running with cockpit-supported operators

---

## The Managed AIR Journey

These aren't tiers you choose from — they're a **journey every customer follows.** The phases step down naturally as the system matures and the team becomes self-sufficient. All phases include Azure infrastructure management and SOC 2 compliance.

| Phase | Flight Stage | Monthly Fee (Aidan) | What It Is |
|---|---|---|---|
| **Hyper Care** | WHEELS UP / Adopt | $2,000/mo | Intensive — biweekly coaching calls, fast gap closure, content sprint (top 10 scenarios), Dave engagement, shop floor display board, agent tuning for customer language |
| **Climb** | CLIMBING / Expand | $1,600/mo | Proactive — monthly coaching calls, content expansion, setup procedures, Altitude Report live, growth planning |
| **Cruise** | CRUISING / Compound | $800/mo | Reactive — monthly Altitude Report, minor adjustments, respond to flags, support new hires |

Customers transition between phases based on readiness, not a fixed schedule. No hour caps, no overage rates.

#### What Each Phase Delivers

| Activity | Cruise | Climb | Hyper Care |
|---|---|---|---|
| Azure Infrastructure | ✓ | ✓ | ✓ |
| SOC 2 Compliance | ✓ | ✓ | ✓ |
| Monthly Altitude Report | ✓ | ✓ | ✓ |
| Minor Adjustments | ✓ | ✓ | ✓ |
| Proactive Gap Analysis | — | ✓ | ✓ |
| Content Creation | — | ✓ | ✓ (intensive) |
| Agent Tuning | — | ✓ | ✓ (intensive) |
| Coaching Call | — | Monthly | Biweekly |
| Shop Floor Visibility Program | — | — | ✓ |
| Dave/Expert Engagement | — | — | ✓ |

### Scoped Projects (alongside the journey)

#### Full Throttle — Solution Expansion Sprint
**$1,500/point** (2-4 points = $3,000-$6,000)

A scoped improvement project — new knowledge areas, deep content buildout, search quality overhaul. Not a monthly subscription; priced per engagement.

#### New Leg — New Work Center
**$10,500** (7 points at $1,500/point)

Full Configure for a new machine type on the existing airframe. See Work Center Expansion below.

---

## Work Center Expansion — New Leg

| Item | Fee |
|------|-----|
| **New Leg** (new machine type or operational area) | **$10,500** (7 points at $1,500/point) |

This is a **CONFIGURE / Configure & Deploy** for a new route on the existing platform. Includes knowledge capture, index expansion, agent reconfiguration, ontology extension, and verification.

**Platform incentive:** Monthly Managed AIR fee covers ALL work centers. More routes in the airspace, more value per dollar.

| Work Centers | Monthly (Climb phase) | Annual Cost per Work Center |
|---|---|---|
| 1 | $1,600 | $19,200 |
| 2 | $1,600 | $9,600 |
| 3 | $1,600 | $6,400 |

---

## Altitude Report & Analytics

### Always-On Analytics
- Query volume and user activity (JSONL analytics lake)
- Satisfaction signals (feedback table — thumbs up/down/flag)
- Response performance (timing breakdowns)
- Knowledge graph utilization (edge hit counters)
- Admin dashboard with real-time stats and conversation viewer

### Monthly Altitude Report (all phases)
1. Adoption stage progress — where are we on the flight path?
2. Query volume trend vs. prior month
3. Active pilots and new pilots this month
4. Satisfaction breakdown and knowledge gap inventory
5. Content improvements delivered
6. Azure cost actuals
7. Recommendations for next month

---

## Azure Infrastructure

Current monthly cost: **~$130/month**

| Service | Cost | Purpose |
|---------|------|---------|
| Azure Cognitive Search (Basic) | ~$70 | Unified index, 1,241 docs |
| Azure Container Apps | ~$24 | Foundry agent runtime |
| Azure App Service | ~$16 | Web app hosting |
| Container Registry | ~$5 | Container images |
| Foundry Models (AOAI) | ~$3-27 | gpt-4.1-mini (agent) + gpt-5-mini (utility) + embeddings (usage-based) |
| Storage + Tables | ~$0.25 | Blobs, feedback, analytics, verification ledger |
| Cosmos DB (Serverless) | ~$0.04 | Graph ontology |
| Functions (Flex Consumption) | $0.00 | API layer |

Included in all phases. Covers management, monitoring, security, SOC 2 compliance.

---

## Recommended Plan & Investment

| Period | Phase | Stage | Monthly (Aidan) | Focus |
|--------|-------|-------|-----------------|-------|
| Months 1-3 | Hyper Care | WHEELS UP / Adopt | $2,000 | Intensive — biweekly coaching, content sprint, Dave engagement, shop floor display board, fast gap closure |
| Months 4-9 | Climb | CLIMBING / Expand | $1,600 | Proactive — monthly coaching, content expansion, setup procedures, Altitude Report live, growth planning |
| Month 10+ | Cruise | CRUISING / Compound | $800 | Reactive — monthly Altitude Report, minor adjustments, respond to flags, support new hires |

**Year 1 estimate (Aidan fees):** $18,000 (3 × $2,000 + 6 × $1,600 + 3 × $800)
**Year 1 estimate (to Gent after MAGNET markup):** ~$23,400

*Note: All fees are Aidan's rates to MAGNET. MAGNET applies their own markup to Gent (currently 30%).*

---

## Term and Invoicing

- **Initial term:** 3 months (Hyper Care phase)
- **After initial term:** Month-to-month, 15-day notice to change phase or cancel
- **Invoicing:** Monthly in advance (phase fee)
- **New Leg expansions:** 50% at kickoff / 50% at completion
- **Full Throttle sprints:** Invoiced at completion
- **Azure costs:** Included in all phases

---

## What This Does NOT Include

- Net-new application development beyond cockpit enhancements
- Migration to a different Azure tenant
- Teams or Copilot integration
- Image/drawing recognition
- Advanced enterprise security (Private Link, complex RBAC)

These can be scoped as expansion projects or a future phase.

---

## Summary

| Item | Aidan Fee |
|------|-----------|
| **Hyper Care** — WHEELS UP / Adopt | $2,000/month |
| **Climb** — CLIMBING / Expand | $1,600/month |
| **Cruise** — CRUISING / Compound | $800/month |
| **Full Throttle** — Solution Expansion Sprint | $1,500/point (2-4 points) |
| **New Leg** — New Work Center | $10,500 (7 points) |
| Recommended Gent journey | 3 mo Hyper Care + 6 mo Climb + Cruise ongoing |
| Year 1 estimate (Aidan) | $18,000 |
| Initial commitment | 3 months (Hyper Care) |
