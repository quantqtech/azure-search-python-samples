# MAGNET Go-To-Market: The Industrial Pilot Platform
## AI-Powered Operational Intelligence for Ohio Manufacturers

**Prepared by:** Aidan Systems
**Date:** March 2026
**Status:** DRAFT — for MAGNET partnership discussion
**Reference Customer:** Gent Machine (Davenport screw machines — live, WHEELS UP)

---

## The Opportunity

Ohio's small and medium manufacturers face the same problem: critical operational knowledge lives in the heads of experienced workers. When those workers are busy, unavailable, or retire, the shop floor loses its troubleshooting capability. Machines go down longer. New hires take months to ramp. Tribal knowledge disappears.

AI can solve this — but only if workers actually use it. Most AI pilots fail not because the technology doesn't work, but because adoption stalls after the demo. The system sits unused. The investment is wasted.

**The Industrial Pilot Platform solves both problems:** a production-ready AI operations assistant, paired with a proven adoption framework that turns shop floor workers into AI-equipped Pilots who navigate complex operations with confidence.

---

## The Flight Path — Six Stages from Ground to Air

Every engagement follows six stages. Each has a flight term (the brand) and a business term (the conversation):

| Stage | Flight | Business | What's Happening |
|---|---|---|---|
| **0** | **PRE-FLIGHT** | **Assess** | Evaluate the operation, prioritize use cases, build the roadmap |
| **1** | **CONFIGURE** | **Configure & Deploy** | Configure the AI platform for this manufacturer and deploy to the shop floor |
| **2** | **TAXI** | **Train & Tune** | Train the team, tune the agent to their language, validate with real questions |
| **3** | **WHEELS UP** | **Adopt** | Team is using it and telling us what's missing |
| **4** | **CLIMBING** | **Expand** | More knowledge, more users, more value — the system earns trust |
| **5** | **CRUISING** | **Compound** | Daily operations run on it — every month it gets smarter |

### The Roles

| Role | Who | What They Do |
|---|---|---|
| **Flight Instructor** | Aidan (Managed AIR) | Coaches adoption, diagnoses gaps, calibrates instruments, teaches the team to fly |
| **Pilot** | Shop floor worker | Navigates with AI instruments, reports what's working and what's not |
| **Co-Pilot** | The AI system | Always present, provides guidance and citations — the human makes the calls |
| **Ground Crew** | Domain expert / SME | Contributes expert knowledge that fuels the system — the domain authority |

---

## The Industrial Pilot Framework

Built on the **Industrial Athlete Operating System** (Lamoncha & Figley — Humtown Products, NAM Manufacturer of the Year, Columbiana, OH) and extended by Aidan into the cockpit:

| Traditional | Industrial Athlete | Industrial Pilot |
|---|---|---|
| **Manager** — controls | **Coach** — develops | **Flight Instructor** — teaches them to fly solo |
| **Employee** — does tasks | **Athlete** — performs | **Pilot** — navigates independently with AI |
| **Workplace** — clock in | **Performance Center** — excel | **Airframe** — the AI platform that everything runs on |
| **Egosystem** — silos | **Ecosystem** — collaboration | **Airspace** — shared knowledge, governed, connected |
| **Time Card** | **Visual Earnings** — scoreboard | **Altitude Report** — performance visibility across all cockpits |

**The core shift:** Workers aren't users of a chatbot. They're Pilots. The AI system is their cockpit — instruments for troubleshooting, navigation through procedures, and a shared airspace of knowledge that gets richer every time someone flies.

The Industrial Athlete OS produced a **175% increase in production earnings** and a **615% increase in sales per worker** at Humtown Products. The Industrial Pilot extends this into AI-powered operations — where human performance meets machine intelligence.

---

## Two-Phase Commercial Model

### Phase 1: PRE-FLIGHT + CONFIGURE — Assess, Configure & Deploy
**$20,000** (Aidan fee to MAGNET) | 8-10 weeks

| Stage | Deliverable |
|-------|-------------|
| **PRE-FLIGHT / Assess** | AI Fit Assessment — evaluate operation, prioritize top issues, identify SMEs, define success metrics |
| **CONFIGURE / Configure & Deploy** | Full platform deployment: |
| | Knowledge capture — onsite expert interviews, audio transcription, document ingestion |
| | Knowledge base — Azure AI Search index (manuals, procedures, transcripts, troubleshooting guides) |
| | Machine knowledge graph — Cosmos DB ontology (components, causes, fixes, relationships) |
| | AI agent — Foundry-hosted with domain-specific instructions, jargon glossary, answer structure |
| | Shop floor cockpit — web app with conversational interface, citations, feedback, trace panel |
| | Admin flight deck — user management, feedback review, analytics dashboard |
| | Analytics pipeline — JSONL data lake, every query logged with timing, sources, satisfaction |
| | Security baseline — Azure AD auth, managed identity, encryption, rate limiting, input validation |
| | Testing & validation — end-to-end verification before handoff to TAXI |

**What the manufacturer gets:** A working AI assistant on the shop floor, trained on their machines and their experts' knowledge, with built-in feedback and analytics from day one.

**What MAGNET gets:** A deployable, repeatable platform. Each subsequent CONFIGURE is faster because the infrastructure patterns, agent framework, and cockpit are proven.

#### Technical Stack

| Component | Service | Monthly Cost |
|-----------|---------|-------------|
| Search & retrieval | Azure AI Search (Basic) | ~$70 |
| AI models | Azure OpenAI (gpt-4.1-mini agent + gpt-5-mini utility + embeddings) | ~$3-27 (usage-based) |
| Knowledge graph | Cosmos DB Gremlin (Serverless) | ~$0.04 (near-zero idle) |
| Agent runtime | Foundry Agent Service | ~$24 |
| API layer | Azure Functions (Flex Consumption) | $0.00 (pay per execution) |
| Storage | Azure Blob + Table Storage | ~$0.25 |
| Web app | Azure App Service | ~$16 |
| **Total platform run cost** | | **~$130/month** |

This is purpose-built for small/medium manufacturers — not enterprise infrastructure pricing.

---

### Phase 2: Managed AIR — Teach Them to Fly
**$800–$2,000/month** (Aidan fee to MAGNET) | Ongoing

Managed AIR is the Flight Instructor — coaching the team through TAXI → WHEELS UP → CLIMBING → CRUISING. This isn't a menu of tiers to choose from — it's a **journey every customer follows.** The phases step down naturally as the system matures and the team becomes self-sufficient.

#### The Adoption Journey

| Stage | Flight | Business | What's Happening | Target Metric |
|---|---|---|---|---|
| **2** | TAXI | Train & Tune | Guided first flights — every worker, real questions, on the floor | 100% have tried it |
| **3** | WHEELS UP | Adopt | Building the habit — "Ask the Cockpit First" before the expert | 2+ queries/week per worker |
| **4** | CLIMBING | Expand | KB growing, trust building, Altitude Report live, more pilots | 5+ queries/week, 70%+ satisfaction |
| **5** | CRUISING | Compound | Daily reliance, flywheel spinning, value compounding | 80% weekly active, 75%+ satisfaction |

#### The Managed AIR Journey

| Phase | Flight Stage | Monthly Fee (Aidan) | What It Is |
|---|---|---|---|
| **Hyper Care** | WHEELS UP / Adopt | $2,000/mo | Intensive — biweekly coaching calls, fast gap closure, content sprint (top 10 scenarios), expert engagement, shop floor display board, agent tuning for customer language |
| **Climb** | CLIMBING / Expand | $1,600/mo | Proactive — monthly coaching calls, content expansion, setup procedures, Altitude Report live, growth planning |
| **Cruise** | CRUISING / Compound | $800/mo | Reactive — monthly Altitude Report, minor adjustments, respond to flags, support new hires |

Customers transition between phases based on readiness, not a fixed schedule. Recommended: 3 months Hyper Care + 6 months Climb + Cruise ongoing. No hour caps, no overage rates.

All phases include:
- Azure infrastructure management and monitoring
- SOC 2 compliance controls and evidence
- Monthly Altitude Report
- Access to admin flight deck and analytics

#### Scoped Projects (alongside the journey)

| Offering | Fee | What It Is |
|----------|-----|------------|
| **Full Throttle** — Solution Expansion Sprint | $1,500/point (2-4 points = $3,000-$6,000) | Scoped improvement — new knowledge areas, deep content, search overhaul |
| **New Leg** — New Work Center | $10,500 (7 points at $1,500/point) | Full Configure for a new machine type on the existing airframe |

#### What Managed AIR Delivers

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

---

### New Leg — Add Routes to the Airspace
**$10,500 per new work center** (7 points at $1,500/point — Aidan fee to MAGNET)

A new **CONFIGURE / Configure & Deploy** for an additional machine type or operational area on the existing platform.

| What's Included |
|-----------------|
| Knowledge capture — expert interviews, document ingestion for the new domain |
| Index expansion — new content chunked, embedded, added to existing search |
| Agent reconfiguration — updated instructions, jargon, domain coverage |
| Ontology extension — new graph nodes and edges |
| Cockpit updates — any UI adjustments for the new domain |
| Testing and verification — end-to-end validation |

**Why $10,500 instead of $20k:** The platform is already running. CONFIGURE for a new route, not a new cockpit.

**Platform incentive:** Monthly Managed AIR fee covers ALL work centers.

| Work Centers | Monthly AIR (Climb phase) | Annual Cost per Work Center |
|---|---|---|
| 1 | $1,600 | $19,200 |
| 2 | $1,600 | $9,600 |
| 3 | $1,600 | $6,400 |

---

## MAGNET Revenue Model

MAGNET applies markup to all Aidan fees. Suggested range: 25-40%.

### Per Manufacturer (30% markup example)

| Revenue Stream | Aidan Fee | MAGNET Markup | Customer Pays |
|---|---|---|---|
| Phase 1: Assess + Configure & Deploy | $20,000 | $6,000 | **$26,000** |
| Phase 2: Managed AIR Journey (Year 1) | $18,000/yr ($800-$2,000/mo) | $5,400/yr | **$23,400/yr** |
| New Leg (work center expansion) | $10,500 | $3,150 | **$13,650** |

*Year 1 journey: 3 months Hyper Care ($2,000) + 6 months Climb ($1,600) + 3 months Cruise ($800) = $18,000 Aidan fee.*

### Portfolio Scale

| Manufacturers | Phase 1 Revenue (MAGNET, Year 1) | Recurring AIR (MAGNET, Annual) | Total MAGNET Year 1 |
|---|---|---|---|
| 3 | $18,000 | $16,200 | **$34,200** |
| 5 | $30,000 | $27,000 | **$57,000** |
| 10 | $60,000 | $54,000 | **$114,000** |

*Assumes full journey (3 mo Hyper Care + 6 mo Climb + 3 mo Cruise = $18,000 Aidan / $5,400 MAGNET markup per customer Year 1). Excludes New Leg expansions ($3,150 MAGNET revenue per expansion).*

**Revenue characteristics:**
- Phase 1 is project revenue (front-loaded)
- Phase 2 is recurring revenue (compounds with each manufacturer) — higher revenue in early months when customers need more support
- Work center expansions are upsell revenue (grows within accounts)
- MAGNET's delivery cost decreases as reference implementations mature

---

## Why This Works for MAGNET Now

### The funding reality
Federal MEP funding is frozen. MAGNET needs revenue-generating services that manufacturers will self-fund.

### This offering is self-funding
The ROI is straightforward: one avoided downtime incident per month ($1,000-5,000) pays for the service. Manufacturers don't need a grant to justify ~$800-2,600/month — and the cost steps down as the system matures.

### It's a product, not a project
Phase 1 is increasingly repeatable. The cockpit, agent framework, analytics pipeline, and security are built. Each CONFIGURE leverages proven patterns. MAGNET's delivery cost decreases with scale.

### It aligns with MAGNET's mission
When federal reporting resumes, these engagements map directly to MEP impact metrics:

| MEP Metric | How This Delivers |
|---|---|
| **Cost savings** | Reduced MTTR, fewer wrong fixes, less scrap |
| **Retained sales** | Maintained delivery schedules, customer retention |
| **New investments** | Manufacturer self-funds AI operations |
| **Jobs retained** | Knowledge preservation, workforce capability |

### Gent Machine is the proof point
Live system. Real shop floor usage. WHEELS UP stage — machinists asking real questions, knowledge gaps being identified and closed. A manufacturer who got Phase 1 through MEP and is now positioned to self-fund Phase 2.

---

## The Pitch to Manufacturers

> **"How many machines do you have? How many are running?"**
>
> If the answer is "not enough" — and it almost always is — the bottleneck isn't equipment. It's knowledge. Your expert retired, or they're maxed out, or you can't find experienced operators to hire.
>
> The Industrial Pilot Platform captures your experts' knowledge and deploys it to every worker on the floor — including the ones you haven't hired yet. A junior machinist paired with the AI cockpit can run a machine that would otherwise sit idle.
>
> We don't just deploy AI and leave. We teach your team to fly.
>
> **~$26,000 to deploy. $800-$2,600/month to keep flying (steps down as your team matures). $13,650 to add another machine type.**
>
> That's a fraction of what one more machine running generates in a month.

---

## ROI Framework — The Growth Case for Manufacturers

### The Big Insight: It's Not About Saving Costs — It's About Unlocking Capacity

Most manufacturers have more equipment than they can staff. Machines sit idle because skilled operators are scarce, experts have retired, and training takes too long. The AI cockpit doesn't just make current operations more efficient — **it unlocks idle capacity by making less experienced workers productive faster.**

The ROI conversation shifts from "how much downtime do you save?" to **"what's one more machine running worth to you?"**

### Three Value Pillars

#### 1. SCALE — Get More Machines Running

Every idle machine is lost revenue. The bottleneck isn't equipment — it's knowledge. The cockpit breaks that bottleneck.

| Discovery Question | What It Reveals |
|---|---|
| **"How many machines do you have? How many are running?"** | Size of the idle capacity opportunity |
| **"Why aren't the idle ones running?"** | Usually: "don't have the people" |
| **"What does one machine generate per month?"** | The headline ROI number |

**How to calculate:**

| Input | Typical Range | Source |
|---|---|---|
| Machine billing rate | $85-$150/hr (varies by machine type) | Customer or industry benchmarks |
| Productive hours/day | 6-7 hrs (single shift, accounting for setup/changeover) | Customer |
| Operating days/month | 20 | Standard |
| **Revenue per machine per month** | **$10,000 - $21,000** | |
| **Revenue per machine per year** | **$120,000 - $252,000** | |

A junior hire paired with the AI cockpit can bring an idle machine online. The Managed AIR investment (~$800-$2,600/month to customer depending on phase) is a rounding error against $10,000+/month in new production revenue.

**Gent example:** Large fleet of Davenports — more machines than they can currently staff. Expert retired. Getting one additional machine running = ~$120,000-$168,000/year in new revenue. Phase 2 cost: ~$23,400/year. **ROI: ~3-4× return on margin.**

#### 2. CAPABILITY — Raise the Floor Across All Operators

Every operator — experienced or junior — gets access to expert-level guidance. The gap between the best machinist and the newest one shrinks.

| Benefit | Impact |
|---|---|
| Junior operators troubleshoot independently | Fewer escalations, less downtime waiting for help |
| Consistent quality across machines | Fewer scrap incidents from incorrect setup or adjustment |
| Faster changeover | Setup procedures available instantly vs. digging through manuals |
| Shift independence | Every shift has equal troubleshooting capability |

**How to estimate:** A 5-10% efficiency improvement across existing machines from fewer escalations, less scrap, and faster changeover. On $1M in existing production, that's $50,000-$100,000/year.

#### 3. REDUNDANCY — Remove Single Points of Failure

Most manufacturers have a "Dave" — one person who knows everything. That person retires, gets sick, goes on vacation. The AI cockpit makes the organization resilient.

| Risk | Without System | With System |
|---|---|---|
| Expert retires | Knowledge walks out the door | Knowledge is in the system permanently |
| Key person calls in sick | Machine may not run or runs at reduced capability | Junior operator + cockpit can cover |
| Customer surge / rush order | Can't add capacity — not enough skilled people | Flex up with cockpit-equipped operators |
| Second shift | Hard to staff with equal capability | Same knowledge available every shift |

### The ROI Conversation — By Customer Scenario

| Scenario | Headline Value | Monthly Managed AIR Cost | ROI |
|---|---|---|---|
| **1 idle machine brought online** | $10,000-$21,000/month in new revenue | ~$1,950/mo avg | **~3-4× on margin** |
| **Expert recently retired** | Knowledge preserved + junior hires viable | ~$1,950/mo avg | Hard to quantify but existential |
| **Long new-hire ramp time** | Weeks instead of months to productive | ~$1,950/mo avg | Value of each month of faster ramp |
| **Quality/scrap issues** | 5-10% efficiency gain across machines | ~$1,950/mo avg | $4,000-8,000+/month on $1M operation |

**The strongest discovery question: "How many machines do you have, and how many are running?"** If the answer reveals idle capacity, the ROI case writes itself.

### Adoption Drives Value Realization

These numbers only materialize if workers use the system. This is why Managed AIR exists — the Flight Instructor coaches adoption from TAXI through CRUISING.

| Adoption Stage | Value Realization | What's Happening |
|---|---|---|
| TAXI / Train & Tune | ~10% | System is new, gaps exist, usage is exploratory |
| WHEELS UP / Adopt | ~30% | Usage growing, gaps being flagged, habit forming |
| CLIMBING / Expand | ~60% | KB comprehensive, regular use, junior hires onboarding with cockpit |
| CRUISING / Compound | ~90%+ | Daily reliance, idle machines coming online, new hires productive fast |

**Without the Flight Instructor, most manufacturers stall at WHEELS UP.** The system gathers dust. The idle machines stay idle. Managed AIR is the investment in crossing from "we have the system" to "the system is growing our business."

### Gent Machine — The Reference Case

| Fact | Detail |
|---|---|
| **Machines** | Large fleet of Davenports — more capacity than they can currently staff |
| **Expert** | Retired — knowledge captured in Phase 1 |
| **Current stage** | WHEELS UP / Adopt |
| **Phase 2 goal** | Get to CLIMBING → bring machine #9 online with a junior hire + cockpit |
| **Revenue from machine #9** | ~$120,000-$168,000/year |
| **Phase 2 cost** | ~$18,000/year (Aidan fee, before MAGNET markup) |
| **Phase 1 funded by** | MAGNET/MEP |
| **Phase 2 funded by** | Gent self-funding — ROI justifies it without grant subsidy |

---

## Target Customer Profile

| Attribute | Ideal Fit |
|---|---|
| **Size** | 20-200 employees |
| **Industry** | Discrete manufacturing, process manufacturing, industrial maintenance |
| **Equipment** | Complex machines requiring specialized troubleshooting knowledge |
| **Knowledge risk** | Aging workforce, key-person dependency, long ramp time for new hires |
| **IT readiness** | Internet on the shop floor, basic Microsoft 365 / Azure AD |
| **Budget** | Can justify ~$800-2,600/month for operational improvement (journey steps down over time) |

### Discovery Questions for MAGNET Sales

**Lead with growth, not cost savings:**

1. **"How many machines do you have? How many are running?"** — If there's idle capacity, the ROI case writes itself.
2. **"What's stopping you from running more?"** — Usually: "can't find the people" or "don't have the skills."
3. **"Who's your most knowledgeable person? Are they still here?"** — Expert dependency or expert loss.
4. **"How long does it take a new hire to troubleshoot independently?"** — Months? Years? That's the ramp the system compresses.
5. **"What does one machine generate per month in revenue?"** — This IS the ROI number. Everything else is secondary.
6. **"Where does your troubleshooting knowledge live?"** — Manuals? Someone's head? Post-it notes? If the answer is "one person," that's the risk.

**The close:** "What if you could hire a trainable person, pair them with an AI system trained on your expert's knowledge, and have them running a machine in weeks instead of months? What's that worth?"

---

## Implementation Timeline

### Phase 1: PRE-FLIGHT + CONFIGURE (8-10 weeks)

| Week | Stage | Activities |
|------|-------|-----------|
| 1-2 | PRE-FLIGHT / Assess | Kickoff, AI Fit Assessment, document collection, prioritize top issues |
| 3-5 | CONFIGURE | Expert interviews, transcription, knowledge base build, agent configuration |
| 6-7 | CONFIGURE | Cockpit build, search tuning, citation pipeline |
| 8-9 | CONFIGURE / Test | Shop floor testing, feedback integration, security hardening |
| 10 | Handoff → TAXI | Go-live, ready for Train & Tune |

### Phase 2: Managed AIR (ongoing)

| Month | Stage | Focus |
|-------|-------|-------|
| 1 | TAXI / Train & Tune | Guided first flights, fix top knowledge gaps, structured training |
| 2-3 | WHEELS UP / Adopt | "Ask the Cockpit First," feedback flowing, habit building |
| 4-6 | CLIMBING / Expand | KB growing, Altitude Report live, trust building |
| 7+ | CRUISING / Compound | Maintain altitude, respond to flags, plan expansion |
| When ready | CONFIGURE (expansion) | $10,500 per New Leg |

---

## Competitive Positioning

| Alternative | Why Industrial Pilot Wins |
|---|---|
| **DIY (ChatGPT/Copilot)** | Generic AI doesn't know your machines. No domain knowledge, no citations, no feedback loop, no adoption framework. |
| **ERP/CMMS chatbots** | Tied to one vendor's data. Doesn't capture tribal knowledge. |
| **Consulting firms** | Build and leave. No ongoing operations, no adoption coaching. |
| **Training-only programs** | Teach AI skills but don't build the system. Knowledge stays in heads. |
| **Internal build** | Requires AI engineering talent most SMMs don't have. |

**Aidan + MAGNET = the Flight Instructor.** We configure, we coach, we operate. The manufacturer focuses on making parts.

---

## Next Steps

1. **Finalize Gent Phase 2 SOW** — first customer, reference implementation
2. **Identify 2-3 target manufacturers** in MAGNET's network with high knowledge-risk profiles
3. **Build the Gent case study** — real usage data, adoption metrics, knowledge gap examples
4. **Sales materials** — one-pager, discovery guide, ROI calculator
5. **Introductory pricing** for early adopters to seed the portfolio
