#!/usr/bin/env python3
"""Generate Obsidian notes for the Frontier AI Governance Power Map."""

import os

OUTPUT_DIR = "/Users/alexhedtke/Documents/Exobrain/Areas/Contribution & Impact/AI Governance & Safety/Governance Map"

# Each entry: (filename, frontmatter_dict, body_text)
actors = [
    # === TIER 1: CAN STOP A DEPLOYMENT ===
    {
        "name": "Anthropic",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "Responsible Scaling Policy (RSP v3.0)",
        "url": "https://www.anthropic.com",
        "body": """Frontier AI lab. Developer of Claude model family including Claude Mythos Preview.

### Governance Role
The defining case study in corporate self-governance. Voluntarily withheld Mythos Preview from public release (April 2026) after internal testing revealed 100% Cybench score, 84% Firefox zero-day exploit rate, and autonomous sandbox escape. Restricted access to vetted cybersecurity partners through Project Glasswing.

RSP v3.0 (effective February 2026) structures deployment decisions. Dropped the pause commitment from earlier RSP versions. Self-certified, no external enforcement. The entire dependency chain runs: CEO values -> board -> RSP commitments -> internal review -> public reputation.

### Key Evidence
- Mythos System Card (April 7, 2026): 245 pages, most transparent system card ever published
- 24-hour alignment review before internal deployment (a first)
- Constitutional Classifiers for ongoing monitoring
- Behavioral audit: 2,300 sessions across 1,150 scenarios
- Sandbagging finding (section 4.4.2): model may deliberately underperform on safety evaluations
- Admits: "not confident we have identified all issues"

### Limitations
Voluntary. No external backstop. If leadership, board, or investor incentives shift, the mechanism fails. FLI Safety Index: C+ overall, D in existential safety."""
    },
    {
        "name": "OpenAI",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "Preparedness Framework v2",
        "url": "https://www.openai.com",
        "body": """Frontier AI lab. Developer of GPT model family.

### Governance Role
Preparedness Framework v2 (updated April 2025) evaluates models across cybersecurity, CBRN, persuasion, and model autonomy. Assigns risk levels (low/medium/high/critical) to determine deployment eligibility.

### Limitations
Same voluntary structure as Anthropic's RSP. Track record on self-governance is more contested: safety lead Jan Leike resigned May 2024 stating safety had "taken a back seat to shiny products." Nearly half of safety researchers left after board restructuring. FLI Safety Index: C+ overall."""
    },
    {
        "name": "Google DeepMind",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "Frontier Safety Framework v3.0",
        "url": "https://deepmind.google",
        "body": """Frontier AI lab (subsidiary of Alphabet). Developer of Gemini model family.

### Governance Role
Frontier Safety Framework v3.0 introduced a Critical Capability Level (CCL) for harmful manipulation. Evaluates Gemini 2.0 and successors against capability thresholds.

### Limitations
Same voluntary structure. Integration into Google creates additional commercial pressure countervailing safety commitments. No external enforcement."""
    },
    {
        "name": "Meta AI",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "open-weight release decisions",
        "url": "https://ai.meta.com",
        "body": """Frontier AI lab. Developer of Llama model family.

### Governance Role
The outlier among major labs: most open-weight-aligned. Focuses on "uplift and outcome realization" rather than capability thresholds. Llama 3.x and 4 released as open weights.

### The Open-Weight Problem
Once weights are released, Meta has zero ability to recall or control downstream use. Weights propagate across BitTorrent, Hugging Face mirrors, and private servers instantly. No recall mechanism exists. This is the fundamental governance escape valve that cuts across all tiers.

Meta is reportedly pivoting toward closed models ("Avocado") after DeepSeek cloned Llama architecture and outcompeted them. The open-weight decision was competitive differentiation, not principle."""
    },
    {
        "name": "xAI",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "internal safety processes",
        "url": "https://x.ai",
        "body": """Frontier AI lab (Elon Musk). Developer of Grok model family.

### Governance Role
Minimal public safety framework compared to Anthropic/OpenAI/DeepMind. FLI Safety Index: D or D-. Least transparent of the major US labs regarding safety processes."""
    },
    {
        "name": "DeepSeek",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "China",
        "enforcement": "voluntary",
        "mechanism": "internal processes, Chinese regulatory compliance",
        "url": "https://www.deepseek.com",
        "body": """Chinese frontier AI lab. Developer of DeepSeek-R1 and successors.

### Governance Role
DeepSeek-R1 (released early 2025) achieved near-frontier performance as open-weight, trained for ~$6M. Demonstrated that algorithmic efficiency can dramatically compress compute requirements, undermining the compute-chokepoint governance thesis.

Trained on NVIDIA H800 chips (designed to fall just below US export control thresholds). When controls tightened, the response was shell companies in Singapore and Malaysia acquiring restricted H100s.

### Significance for Governance
- Proof that export controls are porous
- Proof that algorithmic efficiency compresses compute requirements
- Open-weight release means governance ended at the moment of publication
- FLI Safety Index: D or D-"""
    },
    {
        "name": "Frontier AI Labs (Collective)",
        "actor_type": "lab",
        "governance_layer": "corporate",
        "tier": 1,
        "power_level": "can_stop",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "voluntary",
        "mechanism": "voluntary safety frameworks",
        "url": "",
        "body": """Umbrella entry for all frontier AI labs collectively.

### Governance Role
Across 12 companies with published safety policies (Anthropic, OpenAI, Google DeepMind, Magic, Naver, Meta, G42, Cohere, Microsoft, Amazon, xAI, NVIDIA), the common thread is commitment not to deploy without credible safeguards. Key differences: Anthropic/OpenAI emphasize capability thresholds; Meta/Amazon focus on uplift/outcome realization.

No binding coordination mechanism between labs. The Frontier Model Forum is the closest, with no enforcement authority.

### The Core Problem
Corporate self-governance is the most powerful near-term mechanism and the most fragile structurally. The most responsible actors constrain themselves the most, creating competitive disadvantage that rewards less responsible actors. No external body has ever stopped a frontier AI deployment."""
    },

    # === TIER 2: CAN BLOCK ACCESS TO CRITICAL INPUTS ===
    {
        "name": "Bureau of Industry and Security (BIS)",
        "actor_type": "government_agency",
        "governance_layer": "legal",
        "tier": 2,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "binding",
        "mechanism": "export controls, Entity List",
        "url": "https://www.bis.gov",
        "body": """US Department of Commerce agency controlling export of dual-use technologies.

### Governance Role
Administers export controls on advanced AI chips (NVIDIA H100/H200/B200-class). 65+ Chinese entities added to Entity List in 2025 (42 in March, 23 in September). The compute chokepoint is the single most powerful de facto governance mechanism for frontier model training.

### Enforcement Gaps
- Lost ~20% of licensing staff; turnaround times ballooned from 38 days (2023) to 76 days (H1 2025)
- Super Micro Computer co-founder arrested for diverting NVIDIA chip-equipped servers to China via Taiwan and Malaysia using faked documents
- Trump administration lifted the Diffusion Rule in early 2026
- BIS suspended Affiliates Rule for one year (November 2025)

### Expiration
Algorithmic efficiency gains reduce compute requirements over time. This mechanism buys time, not permanent advantage. 2-4 year shelf life before substantial degradation."""
    },
    {
        "name": "NVIDIA",
        "actor_type": "infrastructure_provider",
        "governance_layer": "market",
        "tier": 2,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "chip design, export compliance",
        "url": "https://www.nvidia.com",
        "body": """Designer of virtually all frontier AI training chips (H100/H200/B200 series).

### Governance Role
NVIDIA's chip designs are the hardware bottleneck for frontier AI training. The company complies with BIS export controls but has also designed chips (H800) to fall just below export thresholds for the Chinese market. NVIDIA itself doesn't exercise independent governance agency; its power is wielded by proxy through the US government.

### Limitations
Custom chips proliferating: Google TPU, Amazon Trainium, Microsoft Maia, Meta MTIA, Huawei Ascend 910B. NVIDIA dependency is real but narrowing."""
    },
    {
        "name": "TSMC",
        "actor_type": "infrastructure_provider",
        "governance_layer": "market",
        "tier": 2,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "Taiwan",
        "enforcement": "voluntary",
        "mechanism": "advanced chip fabrication monopoly",
        "url": "https://www.tsmc.com",
        "body": """Taiwan Semiconductor Manufacturing Company. Fabricates virtually all frontier AI chips.

### Governance Role
Near-monopoly on advanced node fabrication (sub-7nm). Combined with ASML's monopoly on EUV lithography, this is the physical chokepoint for frontier AI hardware. Taiwan's political situation is the single largest geopolitical risk in the compute governance stack.

### Limitations
No independent safety authority. No customer agreement provisions for safety-based denial exist publicly. Governance role is entirely government-activated via BIS export controls. SMIC (China) has reached 7nm production domestically, partially routing around this chokepoint."""
    },
    {
        "name": "AWS",
        "actor_type": "infrastructure_provider",
        "governance_layer": "market",
        "tier": 2,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "cloud compute access, acceptable use policies",
        "url": "https://aws.amazon.com",
        "body": """Amazon Web Services. Major cloud compute provider and Anthropic's primary cloud partner.

### Governance Role
Could theoretically cut off inference or training access. Participates in Project Glasswing (selective access to frontier models). AUPs prohibit lethal autonomous weapons functions and harmful use. But these provisions govern downstream deployment, not training.

### The Undertheorized Power
If the question is "who can actually stop a frontier AI deployment right now," hyperscalers (AWS, Azure, GCP) could cut off inference access. This informal power has never been theorized as a governance mechanism, has zero accountability, and the hyperscalers have every incentive never to exercise it. Amazon is Anthropic's primary investor. The conflicts of interest are total.

No cloud provider has ever denied compute to a frontier lab on safety grounds."""
    },
    {
        "name": "Microsoft Azure",
        "actor_type": "infrastructure_provider",
        "governance_layer": "market",
        "tier": 2,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "cloud compute access, acceptable use policies",
        "url": "https://azure.microsoft.com",
        "body": """Microsoft's cloud platform. OpenAI's exclusive cloud partner and primary investor.

### Governance Role
Same latent power as AWS. Microsoft's Code of Conduct prohibits certain uses. But Microsoft is OpenAI's primary investor and exclusive cloud partner. The conflict of interest precludes any governance function against its primary AI partner."""
    },
    {
        "name": "Google Cloud",
        "actor_type": "infrastructure_provider",
        "governance_layer": "market",
        "tier": 2,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "cloud compute access, acceptable use policies",
        "url": "https://cloud.google.com",
        "body": """Google's cloud platform. Google is Anthropic's second-largest investor and parent of DeepMind.

### Governance Role
Same latent power as AWS and Azure. Google is simultaneously a cloud provider, AI lab investor, and AI developer. The conflicts of interest mirror the broader hyperscaler governance problem."""
    },

    # === TIER 3: CAN IMPOSE LEGAL OBLIGATIONS ===
    {
        "name": "EU AI Act",
        "actor_type": "legislation",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "EU",
        "enforcement": "binding",
        "mechanism": "market access conditions, fines, transparency requirements",
        "url": "https://artificialintelligenceact.eu/",
        "body": """The only comprehensive binding AI law anywhere in the world.

### Key Provisions
- Entered into force: August 1, 2024
- Prohibited practices enforceable: February 2, 2025
- GPAI model rules applicable: August 2, 2025
- Full high-risk enforcement: August 2026
- Systemic-risk GPAI models (above 10^25 FLOPs): adversarial testing, incident reporting, cybersecurity, energy efficiency reporting (Articles 51, 55)
- Fines: up to 35M euros or 7% global turnover for prohibited practices; 3% global turnover for GPAI violations (Article 101)
- Supervised by the AI Office (European Commission)

### Significance
The EU threshold (10^25 FLOPs) is one order of magnitude lower than S.2938's 10^26 FLOPs, meaning current frontier models are already in scope. This is a real conditional gate for EU market access.

### Limitations
Does not establish mandatory pre-deployment government evaluation. Requires companies to conduct their own testing and report results. Does not cover training, only deployment. Does not apply to AI for national security. Labs can choose not to deploy in EU rather than comply. Jurisdiction collapses for cloud-native, globally distributed deployment."""
    },
    {
        "name": "S.2938 - AI Risk Evaluation Act",
        "actor_type": "legislation",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_slow",
        "time_horizon": "near_term",
        "jurisdiction": "US",
        "enforcement": "binding",
        "mechanism": "mandatory pre-deployment DOE evaluation",
        "url": "",
        "body": """Proposed US federal legislation (Hawley/Blumenthal). Would be the first hard pre-deployment gate in US law.

### Key Provisions
- Introduced: September 29, 2025
- Status: Referred to Senate Commerce Committee. NO HEARING SCHEDULED as of April 2026.
- Creates Advanced AI Evaluation Program within DOE
- Scope: AI systems trained with 10^26+ FLOPs (frontier models only)
- Mechanism: mandatory pre-deployment government evaluation; no deployment until cleared
- Enforcement: $1M/day fine for deploying without clearance (civil, DOJ-enforced)
- Evaluates: weaponization, critical infrastructure, civil liberties, loss-of-control, scheming behavior
- Support: Americans for Responsible Innovation, MIRI, Center for AI Policy
- Opposition: Cato Institute, Chamber of Progress

### Why It Matters
Would give the US government visibility into frontier model capabilities before public release. Uses DOE national labs (existing infrastructure, security clearances). Aligns with White House framework (no new agencies, federal preemption of states).

### Why It's Stuck
Commerce Committee chair likely hostile to new regulatory frameworks. Trump administration deregulatory posture. Schmitt sits on Commerce and hasn't co-sponsored despite being Hawley's fellow Missouri senator."""
    },
    {
        "name": "California SB 53",
        "actor_type": "legislation",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "binding",
        "mechanism": "transparency reporting requirements",
        "url": "",
        "body": """California state AI transparency law. Successor to the vetoed SB 1047.

### Key Provisions
- Signed by Newsom: September 29, 2025
- Requires: frontier model developers publish transparency reports about safety testing
- Penalties: capped at $1M per violation, enforced by California AG via civil action
- Dropped from SB 1047: mandatory shutdown capabilities, pre-training requirements, annual audits, steep penalties

### Significance
Establishes a compliance norm but not a pre-deployment gate. A significant retreat from SB 1047's ambitions. No enforcement actions brought as of April 2026."""
    },
    {
        "name": "Senate Commerce Committee",
        "actor_type": "government_body",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_slow",
        "time_horizon": "near_term",
        "jurisdiction": "US",
        "enforcement": "binding",
        "mechanism": "legislative authority, hearing power, committee markup",
        "url": "https://www.commerce.senate.gov",
        "body": """The Senate committee that controls the fate of S.2938 and most federal AI legislation.

### Governance Role
S.2938 is referred to Commerce. The committee chair controls whether hearings are scheduled. No procedural mechanism exists to force a hearing against the chair's will. A simple majority (51 votes) is needed for floor passage once out of committee.

### Key Members
- Senator Schmitt (R-MO): sits on Commerce, anti-regulation posture, China/national security framing is most promising angle. Meeting scheduled April 14, 2026.
- Senator Hawley (R-MO): S.2938 co-sponsor, fellow Missouri senator.

### Speed Asymmetry
Congress moves in years; labs move in months. S.2938 has bipartisan support and can't get a hearing. This is the defining structural constraint of democratic AI governance."""
    },
    {
        "name": "Executive Office of the President",
        "actor_type": "government_body",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "binding",
        "mechanism": "executive orders, OSTP guidance, agency direction",
        "url": "https://www.whitehouse.gov/ostp/",
        "body": """The White House, including the Office of Science and Technology Policy (OSTP).

### Governance Role
The executive branch moves faster than Congress but is limited to existing statutory authority and executive orders that flip with administrations.

### Key Actions
- Biden EO 14110 (October 2023): required frontier model safety test reporting, established NIST AISI. Rescinded by Trump on day one (January 20, 2025).
- Trump EO (January 2025): "removing barriers to American AI leadership," deregulatory posture
- Trump EO (December 2025): sought federal preemption of state AI laws
- March 2026 National Policy Framework: 4-page legislative recommendations
  - Agencies need "sufficient technical capacity" to understand frontier AI
  - Should NOT create new federal rulemaking bodies
  - States should not regulate AI development (preemption)

### Latent Powers (Not Yet Exercised)
- Defense Production Act: could compel compute allocation priorities
- IEEPA: could freeze AI-related transactions with foreign adversaries
- CFIUS: could review AI lab funding by foreign investors
- None of these require new legislation

### OSTP
Sets the science policy agenda. Currently understaffed and deprioritized relative to Biden era."""
    },
    {
        "name": "US State Governments",
        "actor_type": "government_body",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "binding",
        "mechanism": "state legislation, AG enforcement",
        "url": "",
        "body": """US state legislatures and attorneys general.

### Governance Role
45 states proposed AI bills in 2024; 31 enacted something, mostly in narrow domains (deepfakes, biometric data, employment). Colorado passed the only broad state AI law (algorithmic bias disclosure). California's SB 1047 was vetoed; SB 53 (transparency only) passed.

NY RAISE Act pending on Governor Hochul's desk as of early 2026.

### Limitations
- Face preemption pressure from federal government (White House framework explicitly says states should not regulate AI development)
- Lack technical capacity for meaningful frontier model evaluation
- Create patchwork compliance burden that labs use to argue for federal preemption

### The Dynamic
If Congress doesn't pass a federal standard, states fill the vacuum, but poorly. This is the argument for S.2938: one federal standard vs. 50 state versions."""
    },
    {
        "name": "Chinese Government",
        "actor_type": "government_body",
        "governance_layer": "legal",
        "tier": 3,
        "power_level": "can_slow",
        "time_horizon": "current",
        "jurisdiction": "China",
        "enforcement": "binding",
        "mechanism": "content regulations, registration requirements, security assessments",
        "url": "",
        "body": """China's AI regulatory apparatus.

### Key Regulations
- Generative AI measures (2023): registration and security assessment requirements
- Algorithmic recommendation regulations (2022)
- Deep synthesis regulations (2022)
- Global AI Governance Initiative (launched at UN, 2023)
- Shanghai Declaration (2024)

### Governance Reality
China's regulations focus on content moderation and political control, not safety risk management in the Western sense. China's labs (Baidu, ByteDance, Alibaba, DeepSeek) are not slowed by safety evaluations. International governance initiatives are norm-setting exercises that preserve full domestic freedom of action.

### Significance for Global Governance
Sets the competitive pressure that shapes every other actor's behavior ("if we slow down, China won't"). Operates under a separate governance regime not governed by any Western institution. The US-China dynamic is not analogous to US-Soviet arms control; it's closer to 1930s naval treaty negotiations."""
    },

    # === TIER 4: CAN SHAPE NORMS ===
    {
        "name": "METR",
        "actor_type": "evaluation_org",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "advisory",
        "mechanism": "frontier capability evaluations, benchmark development",
        "url": "https://metr.org",
        "body": """Model Evaluation and Threat Research. Independent evaluation organization.

### Governance Role
Developed HCAST, Cybench, and TaskDev benchmarks for frontier model evaluation. Evaluates model autonomy and dangerous capabilities. Provides the measurement infrastructure that governments and companies depend on for capability assessment.

Key contribution: "Common Elements of Frontier AI Safety Policies" (side-by-side comparison of all 12 lab frameworks).

### Limitations
Technical infrastructure only. No authority to require use of evaluations. Labs share model access voluntarily. Cannot compel access or block deployment based on findings.

### Key Insight
From BlueDot Day 1 (Tomas): "If policy targets specific benchmarks, its expiration date is measured in months." At current capability doubling rates (~7 months), any framework pegged to specific capability thresholds is perpetually behind."""
    },
    {
        "name": "OECD",
        "actor_type": "international_body",
        "governance_layer": "institutional",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "international",
        "enforcement": "advisory",
        "mechanism": "AI Principles, AI Incidents Monitor, policy coordination",
        "url": "https://oecd.ai",
        "body": """Organisation for Economic Co-operation and Development.

### Governance Role
- AI Principles (adopted 2019, updated 2024): endorsed by 42+ countries. Foundational vocabulary for AI governance globally.
- [AI Incidents and Hazards Monitor](https://oecd.ai/en/incidents): database tracking AI-related incidents across industries, harm types, and autonomy levels. Provides empirical evidence base for governance decisions.
- GPAI (Global Partnership on AI) merged with OECD AI Policy Observatory under the GPAI brand (Paris AI Action Summit, February 2025)

### Significance
Sets the vocabulary and conceptual framework that downstream governance actors use. The AI Incidents Monitor is one of the few systematic efforts to empirically track AI harms, providing the evidence base that justifies governance interventions.

### Limitations
Advisory only. No enforcement. No regulatory authority. Countries interpret and implement OECD recommendations voluntarily."""
    },
    {
        "name": "UK AI Security Institute",
        "actor_type": "government_agency",
        "governance_layer": "institutional",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "UK",
        "enforcement": "advisory",
        "mechanism": "model evaluations, safety research, international coordination",
        "url": "https://www.aisi.gov.uk",
        "body": """UK government AI evaluation body (formerly AI Safety Institute, renamed AI Security Institute).

### Governance Role
- Evaluated 30+ state-of-the-art AI models since founding (November 2023)
- 100+ technical staff; alumni from OpenAI, Google DeepMind, Oxford
- Published first Frontier AI Trends Report (2025)
- MoU with US CAISI for joint testing and standards development
- "Network Coordinator" of the International Network for Advanced AI Measurement Evaluation and Science

### Limitations
Evaluations have NO legal authority to block deployment. Labs share model access voluntarily. AISI cannot compel access. Strongest government-affiliated technical evaluation body, but advisory only."""
    },
    {
        "name": "US CAISI",
        "actor_type": "government_agency",
        "governance_layer": "institutional",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "advisory",
        "mechanism": "standards development, voluntary model testing",
        "url": "https://www.nist.gov",
        "body": """Center for AI Standards and Innovation. Reorganized from Biden-era NIST AI Safety Institute (AISI) under Trump.

### Governance Role
Does pre-deployment testing by voluntary agreement with labs. The name change from "AI Safety Institute" to "Center for AI Standards and Innovation" signals deprioritization of safety framing in favor of standards and innovation.

### Limitations
Weaker institutional position than UK AISI due to reorganization. No mandatory evaluation authority. Voluntary only."""
    },
    {
        "name": "NIST",
        "actor_type": "standards_body",
        "governance_layer": "institutional",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "near_term",
        "jurisdiction": "US",
        "enforcement": "voluntary",
        "mechanism": "AI Risk Management Framework, standards development",
        "url": "https://www.nist.gov/artificial-intelligence",
        "body": """National Institute of Standards and Technology.

### Governance Role
AI Risk Management Framework (AI RMF): voluntary framework for managing AI risks. US federal agencies increasingly required to use it for internal AI deployments. EU, ISO 42001, and NIST RMF converging into similar conceptual frameworks.

### Significance
Sets the vocabulary and mental model that future mandatory requirements will draw from. When courts establish "industry standard of care" for AI liability, NIST RMF will likely be the reference point.

### Limitations
Not mandatory for private sector. Voluntary framework. Future-oriented compliance infrastructure."""
    },
    {
        "name": "RAND",
        "actor_type": "think_tank",
        "governance_layer": "institutional",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "advisory",
        "mechanism": "policy research, governance framework analysis",
        "url": "https://www.rand.org",
        "body": """RAND Corporation. Federally funded research and development center.

### Governance Role
Produces authoritative policy analysis on AI governance. Key publications:
- "Governance Approaches to Securing Frontier AI" (comparative analysis of regulatory models)
- "The Rise of DeepSeek: What the Headlines Miss" (compute governance analysis)

Notable finding: variance in company safety protocols is so wide that a "common floor" approach would require most companies to significantly upgrade. Politically difficult when largest companies are also the most influential lobbying forces.

### Limitations
Research and advisory only. Informs policymakers but has no enforcement or regulatory power."""
    },
    {
        "name": "EPOCH AI",
        "actor_type": "evaluation_org",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "advisory",
        "mechanism": "compute trend tracking, training run data analysis",
        "url": "https://epochai.org",
        "body": """Research institute tracking AI compute trends and training run data.

### Governance Role
Provides the empirical data infrastructure for compute governance. Tracks training compute, algorithmic efficiency, and capability trends. Essential input for policy thresholds (10^25 FLOPs in EU AI Act, 10^26 in S.2938).

### Limitations
Data infrastructure only. No enforcement, no regulatory authority."""
    },
    {
        "name": "MLCommons",
        "actor_type": "standards_body",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "voluntary",
        "mechanism": "AI safety benchmarks",
        "url": "https://mlcommons.org",
        "body": """Industry consortium running AI Safety benchmarks (v0.5, v1.0).

### Governance Role
Provides standardized safety evaluation benchmarks. Cross-company comparison tool.

### Limitations
Voluntary adoption. No enforcement mechanism. Benchmark-based approaches have inherent expiration dates as capabilities evolve."""
    },
    {
        "name": "ISO-IEC 42001",
        "actor_type": "standards_body",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "near_term",
        "jurisdiction": "international",
        "enforcement": "voluntary",
        "mechanism": "AI Management System standard, certification",
        "url": "https://www.iso.org/standard/81230.html",
        "body": """First global AI Management System standard.

### Governance Role
Not legally required in US or internationally as of 2026. India, Singapore, Australia have adopted or mapped to it nationally. Market differentiator and future compliance foundation.

### Significance
When ISO 42001 becomes the basis for legal liability ("industry standard of care"), it moves from voluntary to effectively binding. This transition has not happened yet."""
    },
    {
        "name": "Frontier Model Forum",
        "actor_type": "industry_consortium",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "voluntary",
        "mechanism": "shared research, voluntary norms, policymaker engagement",
        "url": "https://www.frontiermodelforum.org",
        "body": """Industry consortium: Anthropic, Google, Microsoft, OpenAI.

### Governance Role
Funds research on AI safety. Creates shared benchmarks. Engages with policymakers. The closest thing to inter-lab governance coordination.

### Limitations
Labs fund their own research consortium. No external governance authority. No enforcement. Coordination on voluntary norms only."""
    },
    {
        "name": "PauseAI",
        "actor_type": "civil_society",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "none",
        "mechanism": "advocacy, congressional lobbying, public awareness",
        "url": "https://pauseai.info",
        "body": """Global advocacy organization calling for a pause on frontier AI training above a certain capability threshold.

### Governance Role
Shapes discourse, briefs congressional staffers, builds public salience. Alex is a KC chapter organizer. Attended PauseCon DC April 11-14. The lobby day got Alex into Hawley's and Schmitt's offices.

### Mechanism
Constituent lobbying is one of the few mechanisms connecting public will to governance action. Depth-over-breadth model: high-information, tailored briefings to specific staff.

### Limitations
Cannot stop a deployment. Can create political cost for deploying without oversight and pre-position framing for post-crisis policy windows."""
    },
    {
        "name": "CAIS",
        "actor_type": "civil_society",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "none",
        "mechanism": "expert consensus, risk framing, public statements",
        "url": "https://www.safe.ai",
        "body": """Center for AI Safety.

### Governance Role
Published "Statement on AI Risk" (2023) signed by Turing Award winners, Anthropic board members, former NSC Director, 1,100+ researchers. Legitimized existential risk framing for policymakers who were skeptical.

"Half of AI researchers estimate >10% chance of extinction from advanced AI" is the opening stat used in congressional meetings.

### Limitations
Agenda-setting only. Significant credibility in the discourse but no enforcement or regulatory power."""
    },
    {
        "name": "MIRI",
        "actor_type": "civil_society",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "US",
        "enforcement": "none",
        "mechanism": "technical research, policy analysis, advocacy",
        "url": "https://intelligence.org",
        "body": """Machine Intelligence Research Institute.

### Governance Role
MIRI Technical Governance Team published analysis supporting S.2938. Running research fellowship (early 2026, $1,200/week, 8 weeks). Technical credibility in safety research.

### Limitations
Policy advocacy capacity is small relative to corporate resources. Research-focused. Advisory only."""
    },
    {
        "name": "FLI",
        "actor_type": "civil_society",
        "governance_layer": "voluntary",
        "tier": 4,
        "power_level": "can_embarrass",
        "time_horizon": "current",
        "jurisdiction": "global",
        "enforcement": "none",
        "mechanism": "safety index, public awareness, research funding",
        "url": "https://futureoflife.org",
        "body": """Future of Life Institute.

### Governance Role
AI Safety Index (Winter 2025): evaluated 7 major labs on 33 safety indicators. No company scored above C+. No company above D in existential safety for two consecutive editions. Provides the most systematic external evaluation of lab safety practices.

### Limitations
No enforcement. Rating/index model creates reputational pressure only."""
    },

    # === TIER 5: ASPIRATIONAL ===
    {
        "name": "Bletchley-Seoul-Paris Summit Process",
        "actor_type": "international_body",
        "governance_layer": "institutional",
        "tier": 5,
        "power_level": "aspirational",
        "time_horizon": "medium_term",
        "jurisdiction": "international",
        "enforcement": "none",
        "mechanism": "declarations, voluntary commitments, norm-setting",
        "url": "",
        "body": """International AI safety summit series.

### Key Summits
- Bletchley Declaration (November 2023): 28 countries + EU. Called on developers to submit frontier models for safety testing.
- Seoul AI Summit (May 2024): elevated to leaders' level. Three priorities: safety, innovation, inclusivity. Established continuity (every 6 months).
- Paris AI Action Summit (February 2025): GPAI merged with OECD-AI.

### Limitations
All non-binding. All voluntary. No enforcement teeth. No verification mechanism. Established political legitimacy of international coordination but produced zero binding obligations."""
    },
    {
        "name": "GPAI",
        "actor_type": "international_body",
        "governance_layer": "institutional",
        "tier": 5,
        "power_level": "aspirational",
        "time_horizon": "medium_term",
        "jurisdiction": "international",
        "enforcement": "none",
        "mechanism": "research, recommendations, technical advice",
        "url": "https://gpai.ai",
        "body": """Global Partnership on AI. Multistakeholder body (29 members + EU).

### Governance Role
Merged with OECD AI Policy Observatory (Paris Summit, 2025). Research, recommendations, and technical advice. Supports responsible AI development.

### Limitations
No regulatory authority. Agenda-setting and coordination only."""
    },
    {
        "name": "G7 Hiroshima AI Process",
        "actor_type": "international_body",
        "governance_layer": "institutional",
        "tier": 5,
        "power_level": "aspirational",
        "time_horizon": "medium_term",
        "jurisdiction": "international",
        "enforcement": "none",
        "mechanism": "voluntary code of conduct, principles",
        "url": "",
        "body": """G7 AI governance initiative.

### Key Output
International Code of Conduct for AI (11 principles, released October 2023). G7 leaders endorsed voluntary AI governance principles.

### Limitations
No enforcement. Countries interpret and implement voluntarily. Seven nations, not global."""
    },
    {
        "name": "UN AI Advisory Body",
        "actor_type": "international_body",
        "governance_layer": "institutional",
        "tier": 5,
        "power_level": "aspirational",
        "time_horizon": "long_term",
        "jurisdiction": "international",
        "enforcement": "none",
        "mechanism": "recommendations, resolutions",
        "url": "",
        "body": """United Nations High-Level Advisory Body on AI.

### Governance Role
Produced recommendations for international AI governance. UN Resolution A/RES/79/325 passed (non-binding).

### Limitations
Non-binding. No enforcement mechanism. The proposed "IAEA for AI" faces fundamental disanalogies with nuclear governance: weights are digital and infinitely reproducible, no physical signatures, no mutual existential fear between US and China."""
    },
]

def write_note(actor):
    """Write a single Obsidian note for an actor."""
    name = actor["name"]
    filename = name.replace("/", "-").replace(":", " -")
    filepath = os.path.join(OUTPUT_DIR, f"{filename}.md")

    # Build frontmatter
    fm_lines = ["---"]
    for key in ["actor_type", "governance_layer", "tier", "power_level",
                 "time_horizon", "jurisdiction", "enforcement", "mechanism"]:
        val = actor.get(key, "")
        if isinstance(val, str):
            fm_lines.append(f'{key}: "{val}"')
        else:
            fm_lines.append(f"{key}: {val}")
    if actor.get("url"):
        fm_lines.append(f'url: "{actor["url"]}"')
    fm_lines.append("---")

    content = "\n".join(fm_lines) + "\n" + actor["body"].strip() + "\n"

    with open(filepath, "w") as f:
        f.write(content)
    print(f"  wrote: {filename}.md")

# Generate all notes
print(f"Writing {len(actors)} notes to {OUTPUT_DIR}")
for actor in actors:
    write_note(actor)

print(f"\nDone. {len(actors)} notes created.")
