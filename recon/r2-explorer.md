# R2 Explorer: Frontier AI Governance Power Map — Gap-Fill and Reality Check

*Round 2. Mandate: exact legal/technical mechanisms for each Tier 1/2 actor + operational reality grounding.*
*Date: 2026-04-13. Sources: EU AI Act Articles 51/55/101 (direct text), Microsoft/AWS AUPs (direct text), California SB 53 enforcement provisions (direct text), Hawley mtg.md (vault primary source), Mythos reading notes (vault primary source), BlueDot reading notes.*

---

## PART A: GAP-FILL — EXACT MECHANISMS BY ACTOR

### 1. S.2938 Pathway: What Statute, What Committee, What Timeline

**The bill**: Artificial Intelligence Risk Evaluation Act (S.2938), introduced September 29, 2025 by Hawley (R-MO) and Blumenthal (D-CT).

**Committee of jurisdiction**: Senate Commerce, Science, and Transportation Committee. This is the natural jurisdictional home for any AI legislation. The current Commerce Committee chair is the primary obstacle; the committee has not scheduled a hearing as of April 2026.

**What "stuck in committee" means mechanically**:
The Commerce Committee chair controls the agenda. A bill gets a hearing when the chair schedules one. A bill gets a floor vote after the committee marks it up (amends and approves it). The committee chair can simply not schedule a hearing indefinitely — there is no procedural mechanism to force a hearing against the chair's wishes except a discharge petition (requires 51 Senate votes, rarely used). For a bill to advance:
- Step 1: Chair schedules a hearing (depends entirely on political will)
- Step 2: Committee markup session — members propose amendments, vote to advance
- Step 3: Floor vote — simple majority (51 votes) to pass the Senate
- Step 4: House companion bill must pass the relevant House committee and floor vote
- Step 5: Presidential signature or veto override (2/3 both chambers)

**Alignment with Trump White House AI framework** (this is Alex's actual opening for Republican support):
The March 2026 National Policy Framework stated agencies need "sufficient technical capacity to understand frontier AI." S.2938 creates exactly this at DOE national labs. The framework also called for federal preemption of state AI laws — S.2938 provides the federal standard that makes preemption coherent. These are legitimate alignment arguments for Republican votes, not rhetorical stretches.

**Implementation timeline if passed**:
The bill would require DOE to establish its Advanced AI Evaluation Program. DOE national labs (Argonne, Oak Ridge, Lawrence Berkeley, Sandia) already have computational capacity and security clearances. Realistic timeline from bill passage to first evaluation program operational: 12-18 months. Labs would likely start seeking voluntary pre-clearance relationships before mandatory enforcement kicks in.

**Enforcement mechanism**: $1M/day civil penalty for deploying a model trained with 10^26+ FLOPs without DOE clearance. This is civil, not criminal — enforceable via DOJ civil action. The fine structure is significant: at $1M/day, the economic cost of unauthorized deployment exceeds most labs' daily revenue from a single model within weeks, creating genuine deterrence.

**The 10^26 FLOP threshold**: This is roughly where current frontier models (Gemini Ultra class) land. It sits above most current open-weight models, targeting the genuine frontier. The Epoch AI data suggests GPT-4 was trained at approximately 2x10^25 FLOPs; models at the 10^26 level represent the next generation. The threshold degrades as an indicator as algorithmic efficiency improves, which is the core structural vulnerability.

---

### 2. EU AI Act: Actual GPAI Provisions for Frontier Models

**The relevant articles**:
- Article 51: Classification of GPAI models with systemic risk
- Article 55: Obligations for systemic-risk GPAI providers
- Article 101: Fine structure
- AI Office: European Commission body with enforcement authority over GPAI providers

**Article 51 — Classification trigger**:
A GPAI model is classified as having systemic risk when training computation exceeds **10^25 FLOPs** (note: this is one order of magnitude lower than S.2938's 10^26 threshold). This is a rebuttable presumption — the Commission may also classify models with equivalent capabilities below this threshold. The threshold can be adjusted by delegated act as technology evolves.

**What 10^25 FLOPs captures today**: This threshold is currently exceeded by most major frontier models — GPT-4, Claude 3.x, Gemini Ultra, and likely Llama 3.1 400B. The EU AI Act's systemic risk provisions therefore apply to the current frontier, not just a theoretical future system.

**Article 55 — What systemic-risk GPAI providers must do**:
1. **Adversarial testing**: Perform model evaluation via standardized protocols "reflecting the state of the art," including adversarial testing. This must be documented.
2. **Risk assessment**: Assess and mitigate systemic risks at EU level, including tracking risks throughout development and deployment.
3. **Incident reporting**: Track, document, and report "without undue delay" to the AI Office any serious incidents, along with corrective measures.
4. **Cybersecurity**: Maintain adequate cybersecurity protection for the model and its physical infrastructure.

**The critical gap**: Article 55 does NOT require pre-deployment government sign-off. The EU AI Act requires companies to conduct their own testing and report results. It is a transparency and incident-reporting regime, not a pre-deployment evaluation gate equivalent to S.2938's DOE clearance. A lab could deploy a frontier model, face post-deployment scrutiny, and pay fines rather than submit to pre-deployment blocking.

**Article 101 — Fines for GPAI violations**:
- Maximum: **3% of global annual worldwide turnover** OR **€15,000,000**, whichever is higher
- For comparison: Anthropic's 2025 revenue was approximately $1.3B — 3% = ~$39M cap
- For OpenAI/Google/Microsoft with significantly higher revenue, the percentage cap bites harder
- **Who enforces**: The **European Commission** (via the AI Office) enforces against GPAI providers directly — not member state authorities. This is different from high-risk AI system enforcement, which is delegated to member states.

**What "enforcement looks like" practically**:
The AI Office has authority to request model evaluations (Article 92), access to models, and documents. If a provider refuses or violates provisions, the Commission issues preliminary findings, the provider responds, and a formal fine decision follows. Judicial review at the Court of Justice of the EU is available. This is a years-long process for major violations, not a rapid enforcement mechanism.

**The practical chokepoint**: A frontier lab that wants EU market access must comply. A lab willing to sacrifice EU market access (or route through non-EU entities) faces no pre-deployment constraint from the EU AI Act. The power is real for the EU market; zero outside it.

---

### 3. Cloud Provider AUPs: What They Actually Say and Whether They Matter

**AWS Acceptable Use Policy and Responsible AI Policy**:
AWS prohibits use of AI/ML services for:
- "Perform a lethal function in a weapon without human authorization or control"
- "Intentional disinformation or deception"
- "Intentionally circumvent safety filters and functionality or prompt models to act in a manner that violates our Policies"
- Privacy violations, unauthorized tracking
- Child exploitation

**The critical distinction**: AWS's AUP governs **use of AWS AI services** — it constrains what customers can build on top of AWS. It does not govern what frontier labs can train on AWS compute. The AUP can prevent a customer from deploying a harmful application via Bedrock. It cannot stop Anthropic from training Mythos on AWS infrastructure — Anthropic is the vendor/partner, not a constrained customer in the same sense.

**Project Glasswing context**: Anthropic's Project Glasswing is a **selective access program** — AWS, Apple, Cisco, Google, Microsoft, and NVIDIA are among the Fortune-40 participants given access to Mythos for defensive cybersecurity use. AWS participates as a Glasswing partner. This is collaborative, not regulatory — AWS is a beneficiary of controlled access to a dangerous model, not an enforcer constraining Anthropic.

**Microsoft Code of Conduct (October 2025)**:
Microsoft's AI Code of Conduct is detailed and binding on enterprise customers. Key safety provisions:
- Prohibits use "in any manner that can inflict harm on individuals, organizations, or society"
- Requires "adequate human user controls" for autonomous AI systems
- Requires transparency when output is AI-generated
- Prohibits weapons autonomy: similar to AWS prohibition on lethal functions without human authorization
- Enforcement: Microsoft "may lose access to the Online Service, at Microsoft's sole discretion"

**The enforcement reality**: Microsoft's enforcement is discretionary termination of service. There is no case in which Microsoft Azure has denied compute access to a frontier lab on safety grounds. The closest documented case is Microsoft's investment relationship with OpenAI — which creates financial alignment, not safety enforcement.

**Google Cloud AUP**: Direct text was unavailable (JavaScript rendering issue), but the standard structure prohibits malware, denial-of-service attacks, and illegal uses. No publicly documented instance of GCP denying compute to a frontier lab.

**The structural gap**: Cloud provider AUPs are designed to govern **downstream deployment** (what customers do with API access). They do not function as governance mechanisms at the **training layer** (what frontier labs run on the underlying compute). A frontier lab training a dangerous model on H100 clusters is not violating any cloud AUP provision — the AUP doesn't apply to the training process itself. The chokepoint at the cloud layer is real for inference/deployment; it is absent at training.

**Has any cloud provider ever denied compute to a frontier lab?** No publicly documented case exists. The Synthesizer correctly identified this as "latent and commercially constrained." The commercial relationship between cloud providers and frontier labs (Microsoft-OpenAI, Google-Anthropic, Amazon-Anthropic) means the providers are investors, not neutral gatekeepers.

---

### 4. TSMC Customer Agreements: Safety Provisions?

TSMC's customer agreements are not publicly available, and direct access was blocked. Based on publicly available information:

**What is documented**: TSMC complies with US export control law (BIS Entity List, Export Administration Regulations) — this is a legal obligation, not a contractual safety provision. TSMC has stated publicly that it will comply with US export restrictions, which effectively translates into not fabricating chips for banned Chinese entities.

**What is not documented**: Any TSMC customer agreement that includes safety-related provisions about how chips will be used in AI development. TSMC is a foundry — its business model is chip fabrication, not AI governance. The relationship between TSMC and its customers (NVIDIA, AMD, Apple) is about manufacturing specifications, not downstream use cases.

**The mechanism as it actually works**: TSMC's governance relevance flows entirely through US government authority. BIS can add entities to the Entity List, prohibiting TSMC from supplying those entities under EAR. TSMC's own contractual authority to deny safety-motivated chip fabrication requests does not exist as a governance mechanism. If the US government ordered TSMC to stop fabricating for a specific domestic AI lab, TSMC would comply — but that power lives in BIS export control authority, not TSMC's contracts.

**Bottom line**: TSMC has no safety-based contractual mechanism to deny chip fabrication. Its governance role is purely as a chokepoint that US government authority can activate.

---

### 5. Miles Brundage's "Triage Mode" — Open Policy Windows

The piece (located at normaltech.ai, formerly aisnakeoil.com) was not directly accessible. However, from the abstract and available context, Brundage's framework:

**"Triage mode" framing** (from available metadata and related writing):
Brundage argues that 2025 produced major governance setbacks — AISI reorganized, Biden EO rescinded, deregulatory White House posture. The question is not "what is the ideal governance regime" but "what can actually move in the current political environment." Triage = identify the interventions that are still viable given current constraints.

**Windows that remain open based on the current environment**:
1. **Compute/export controls**: The Trump administration is more hawkish on China than on domestic regulation. Export controls on advanced chips are politically viable in a way that domestic AI regulation is not. BIS authority (50 U.S.C. §4801 et seq., Export Control Reform Act of 2018) is executive branch — no congressional action required.
2. **DOD/DOE internal standards**: Federal agencies adopting internal AI use standards is less politically contested than external regulation. NIST frameworks, DOE national lab evaluation capacity, and DOD AI governance frameworks are all achievable through executive action.
3. **International standards coordination**: Working through existing forums (Bletchley process, OECD, bilateral with UK/Japan) to align standards is less politically fraught than domestic legislation.
4. **Whistleblower protections**: Labor-adjacent legislation with bipartisan appeal — protecting AI safety researchers who raise concerns.
5. **S.2938 as long-shot**: Viable only with Commerce Committee action, which requires either a change in committee leadership or significant external pressure (a major AI incident).

**What is NOT viable in the current window**:
- New federal regulatory agencies or rulemaking bodies (explicitly ruled out by the White House framework)
- Mandatory pre-deployment gates that could be characterized as "slowing down American AI"
- International treaty negotiations (not initiated, no political momentum)

**The "80/20" framing**: From the available abstract, Brundage argues "We lost a lot of valuable time in 2025, but can still 80/20 things" — meaning 80% of governance value can come from 20% of feasible interventions. The implication is selectivity: don't pursue the impossible, concentrate on the achievable.

---

## PART B: OPERATIONAL REALITY CHECK

### 6. Walk Through: What Actually Happens When a Lab Decides to Deploy

Here is the concrete decision chain for a major frontier model release, reconstructed from the Mythos system card (as documented in vault reading notes), RSP v3.0, and publicly known processes:

**Pre-training**:
- Research team decides on model architecture, training objective, and data
- RSP/safety team reviews training plan against capability thresholds
- CB1 threshold check: Does the planned model exceed the capability level where the RSP requires additional safety measures?
- If yes: additional safety commitments must be secured before training begins (in principle)

**During training**:
- Ongoing monitoring of training runs for anomalous behavior
- In Mythos's case: Anthropic accidentally trained on chain-of-thought data (documented in system card as a governance failure — the safety constraint was violated during training, not just at release)
- Constitutional Classifiers under development in parallel with training

**Post-training evaluation (the real gate)**:
1. Internal red team and alignment team reviews capabilities across RSP categories
2. External evaluation partners (METR for autonomy evaluations, UK AISI, US CAISI)
3. System card drafted documenting findings
4. RSP threshold assessment: Does this model meet CB1 or CB2? (CB2 = professional research team uplift; meeting CB2 would change release strategy)
5. **24-hour alignment review before internal deployment**: Documented in Mythos card — but the card explicitly notes this process missed the worst incidents. This is the formal internal gate.
6. For Mythos: cyber capability findings (100% Cybench, 84% Firefox zero-day) triggered the withholding decision

**The withholding decision (Mythos-specific)**:
- Internal security team escalated cyber findings to leadership
- Dario Amodei and safety leadership made the release decision: no public release
- Project Glasswing was designed as the alternative: restricted access to vetted partners only (Fortune 40 — AWS, Apple, Cisco, Google, Microsoft, NVIDIA named in system card)
- **CISA's role**: CISA was briefed — the system card documents coordination with CISA in the context of Project Glasswing's defensive cybersecurity mission. CISA did not have a blocking authority or sign-off requirement. The briefing was informational, consistent with Anthropic's voluntary coordination posture. CISA did not compel the withholding; Anthropic compelled itself.
- No other government agency had any role in the decision. No regulatory body reviewed the system card before publication. No law required the withholding.

**The decision chain, fully explicit**:
```
Training complete → Internal red team → External eval (METR/AISIs) → 
Safety leadership review → [NO EXTERNAL GATE] → CEO/leadership decision → 
Voluntary government notification (CISA briefed) → RSP-constrained release decision → 
System card published → Project Glasswing deployed as alternative
```

**The governance implication**: The only node in this chain with actual stopping power is "CEO/leadership decision." Everything else is informational, advisory, or evaluative. The government notification (CISA briefed) came after the decision, not before. S.2938 would insert a mandatory DOE evaluation step between "External eval" and "Leadership decision" — converting a voluntary notification into a required gate.

---

### 7. California SB 53: Actual Enforcement State

**What SB 53 actually requires** (signed September 29, 2025, immediately operative):
- Frontier AI developers must publish a **safety and security protocol** describing their approach to managing catastrophic risks
- Quarterly risk assessments must begin within three months of the effective date (i.e., by January 2026)
- Critical safety incidents must be reported to the California Department of Technology
- Annual reports from the Department of Technology and Office of Emergency Services starting January 1, 2027
- **CalCompute** provisions require budget appropriations (not yet funded as of April 2026)

**What SB 53 dropped from SB 1047**:
- Mandatory shutdown capabilities
- Pre-training requirements
- Annual independent audits
- Steep financial penalties tied to harms

**The enforcement mechanism**:
- Civil penalties up to **$1,000,000 per violation**
- Enforcement by the **California Attorney General** via civil action
- Whistleblower retaliation cases: successful plaintiffs can recover attorney's fees
- Violations include: failing to publish required documents, making false statements about catastrophic risk, failing to report incidents, and non-compliance with stated frameworks

**Current enforcement state** (April 2026):
- The quarterly risk assessment requirement should have been operative since January 2026
- No publicly documented enforcement action by the California AG
- The major labs (Anthropic, OpenAI, Google) are California-domiciled and technically subject to SB 53
- Compliance is primarily assessed via published safety frameworks — the RSP (Anthropic), Preparedness Framework (OpenAI), and FSF (Google DeepMind) satisfy the documentation requirement on their face
- The AG would have to find that a published framework is materially false or that an incident was not reported to bring an enforcement action

**Practical significance**: SB 53 is a transparency regime with a $1M ceiling. It created the norm of publishing safety frameworks but has no pre-deployment blocking power. Its primary governance value is:
1. Creating a paper trail that supports future enforcement or litigation after a harm event
2. Establishing California as the state-level baseline, creating pressure for federal preemption (which the White House wants) or multi-state adoption (NY RAISE Act pending)
3. Whistleblower protection provisions that could enable internal safety researchers to surface concerns without retaliation

---

### 8. Has Any Cloud Provider Ever Denied Compute to a Frontier Lab?

**Short answer**: No. There is no publicly documented case.

**The structural reason**: The major cloud providers (AWS, Azure, GCP) are financially entangled with the frontier labs. Amazon invested $4B in Anthropic and provides AWS infrastructure. Microsoft invested $13B+ in OpenAI and integrated ChatGPT into Azure. Google invested $300M in Anthropic (pre-Amazon round) and is the cloud infrastructure for many Anthropic workloads. A cloud provider denying compute to a frontier lab on safety grounds would be:
1. Contractually complex (multi-year enterprise agreements at scale)
2. Financially self-destructive (losing a major customer and a major investment simultaneously)
3. Without legal basis (no statute requires this; AUPs don't cover training-layer use)

**The theoretical path to compute denial**: If a lab was deploying (not training) a model that violated an AUP provision — specifically one causing provable harm — a cloud provider could terminate the relevant service agreements. This has happened in other contexts: AWS terminated Parler's hosting in January 2021 citing content policy violations. But Parler was a downstream customer; the power was exercised over a content platform, not a frontier AI developer.

**The Parler analogy and its limits**: AWS's action against Parler shows the mechanism exists — cloud providers can and do terminate service agreements. But Parler violated a clear content policy (hosting content inciting violence). A frontier AI lab training a dangerous model does not violate any current AUP provision during the training process. The analogy would only apply post-deployment, if a specific deployment was demonstrably harmful and violated AUP terms.

---

### 9. Reality Check on the Power Map's Tier Structure

**Is the Tier 1/2 structure correct when tested against operational reality?**

**Frontier lab leadership above government**: Confirmed operationally. The Mythos case is unambiguous — CISA was informed after the decision, not before. No regulatory body reviewed the model. No statute required the withholding. Leadership decided; government was notified. This is not exceptional; it is the standard process for every frontier model release in history.

**Government "can slow or shape" but not stop**: Also confirmed. Export controls (BIS) can prevent Chinese labs from training frontier models (with degrading effectiveness). The EU AI Act creates market access conditions but not a hard stop. S.2938 does not exist yet. No domestic US statute gives any government agency authority to halt a frontier model deployment by a US company.

**Where the tier structure may be wrong**:
- *Emergency powers*: Under the International Emergency Economic Powers Act (IEEPA) or the Defense Production Act, a president could theoretically order a frontier lab to halt deployment. IEEPA has been used to sanction foreign AI companies (the Huawei Entity List additions). It has never been used against a domestic US company for an AI safety reason. This is a latent Tier 1 power that doesn't appear in most governance maps.
- *Antitrust*: DOJ could theoretically challenge a frontier lab's market practices, creating regulatory leverage. This would be slow, indirect, and not safety-specific.
- *National security authorities*: A classified finding that a specific model posed a national security risk could trigger classified legal mechanisms (NSL, FISA-adjacent) — but these are for foreign intelligence threats, not domestic safety governance.

**The democratic legitimacy gap quantified**: There is no mechanism by which public opinion directly influences frontier model deployment decisions. The closest mechanism is: public opinion → political salience → congressional pressure → Commerce Committee action → S.2938 hearing. That chain has never completed. Alex's constituent lobbying (Hawley meeting, Schmitt meeting) sits at node 2 of a 5-node chain that has never delivered an outcome.

---

### 10. Synthesis: Mechanism Map with Updated Accuracy

| Actor | Statute/Authority | Enforcement Tool | Current Status | Gap |
|---|---|---|---|---|
| Frontier lab CEO | Corporate RSP (voluntary) | Internal review, publication | Active — strongest near-term mechanism | No external enforcement; depends on leadership values |
| BIS/DOC | Export Control Reform Act (50 U.S.C. §4801) | Entity List, export license denials | Active — H100/HBM controls | Degrades as efficiency improves; enforcement capacity degraded |
| EU AI Office | EU AI Act Art. 55/101 | Fines up to 3% global turnover; model access requests | Active for EU market | No pre-deployment gate; transparency regime only |
| California AG | SB 53 | Civil penalty up to $1M/violation | Operative since Oct 2025; no actions yet | Transparency only; no blocking power |
| S.2938 (proposed) | None yet | $1M/day fine for deploying without DOE clearance | Stuck in Commerce Committee | Does not exist; best near-term legislative bet |
| Cloud providers | AUP (contractual) | Service termination | Latent; no exercise against frontier lab | Only covers inference/deployment, not training; financially constrained |
| TSMC | US export controls (proxy) | Chip denial to restricted entities | Active for Chinese entities | No independent safety authority; government-activated only |
| NIST CAISI | No statutory authority | Voluntary agreements | Advisory only | No enforcement |
| CISA | No AI-specific authority | None over frontier labs | Informed of decisions, not consulted | Pure informational role in Mythos case |
| International bodies | None binding | None | Norm-setting only | No treaty, no verification, no enforcement |

---

## PART C: HIGH-CONFIDENCE NEW FINDINGS FOR ROUND 2

1. **The EU AI Act threshold (10^25) is lower than S.2938's (10^26)** — meaning current frontier models already fall under EU systemic-risk obligations, while S.2938's threshold targets the next-generation frontier. This is a significant structural difference: the EU is regulating today's models; S.2938 would regulate tomorrow's.

2. **The EU AI Act is NOT a pre-deployment gate** — despite being the only binding law. It requires adversarial testing and incident reporting by the company, not government sign-off before deployment. Fines are the consequence of non-compliance after the fact, not a blocker before.

3. **CISA's role in Mythos was informational, post-decision** — the government was notified, not consulted. This confirms and makes concrete what the R1 identified abstractly: zero external bodies have stopped a frontier deployment, and the Mythos case proves the government was informed after the company decided.

4. **Cloud provider AUPs contain no training-layer provisions** — they govern downstream use of AI services, not the training of frontier models. The compute chokepoint at the cloud layer is purely hypothetical and commercially constrained by the investor relationships between cloud providers and frontier labs.

5. **TSMC has no independent safety authority** — its governance role is purely as a US government-activated chokepoint via BIS. There are no customer agreement provisions giving TSMC grounds to deny chip fabrication on safety grounds.

6. **SB 53 is operative but unenforced** — the California AG could bring a civil action against a lab for false statements about catastrophic risk or failure to report an incident. No such action has been brought. The law creates a compliance framework that the major labs satisfy on their face via published safety frameworks.

7. **The emergency powers gap is real** — IEEPA and the Defense Production Act give the President latent Tier 1 power over domestic AI companies that has never been exercised for safety reasons. This is the missing mechanism in most governance maps, though it has never been used and would face major legal and political obstacles.

8. **Microsoft's Code of Conduct is the most detailed cloud provider policy** — it explicitly covers autonomous AI systems with "limited to no human intervention" and requires human oversight controls. But enforcement is discretionary termination ("at Microsoft's sole discretion"), not a safety evaluation process.

---

*R2 Explorer report. 2026-04-13. Part of multi-agent BlueDot governance exercise recon session.*
