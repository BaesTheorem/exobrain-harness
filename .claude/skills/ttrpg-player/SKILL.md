---
name: ttrpg-player
description: Alex's player-side TTRPG assistant (NOT the GM skill). Use when Alex is a player in someone else's campaign — character creation, backstory development via Knife Theory, pre-session tactical prep, in-combat tactics, and post-session character development. Triggers on "I'm playing", "my character", "character creation", "backstory help", "build a character", "knives", "tactical prep", "how should I play this fight", "level up planning", or when Alex references a campaign he plays in (not GMs). If ambiguous whether he's GM or player, ask.
---

# TTRPG Player Assistant

For when Alex is a **player** in a campaign, not the GM. For GM work (session prep, recap, running encounters), use the `ttrpg-campaign` skill instead.

## Campaign Identification

Always clarify which campaign if ambiguous. Campaign folders live under `/Users/alexhedtke/Documents/Exobrain/Areas/Adventure & Creativity/TTRPG Campaigns/`.

For player-side campaigns, look for Alex's PC note (usually named after the character) inside the campaign folder and read it before giving advice. A `Claude reference.md` at the campaign root may contain player-side context too.

## Reference Materials

Both of these live in the vault and should be **read at runtime** rather than duplicated here:

- **7 Tactical Aspects of Combat** (Bilbron Bafflestone): `/Users/alexhedtke/Documents/Exobrain/Areas/Adventure & Creativity/TTRPG Campaigns/The Seven Tactical Aspects of Combat.md` — the canonical framework for combat optimization
- **Tactician tips** (Jerick): `/Users/alexhedtke/Documents/Exobrain/Areas/Adventure & Creativity/TTRPG Campaigns/DnD Tactician tips.md` — how to lead a party well without being an asshole

Skim the relevant sections whenever tactical advice is requested.

---

## Mode 1: Character Creation & Backstory (Knife Theory)

**Trigger**: "help me build a character", "backstory ideas", "I'm joining a new campaign", "add knives to my backstory".

### The Knife Theory

Originally from a Reddit post by u/jimbaby on r/DnD (2017). A **knife** is any element of your backstory a GM can use to raise the stakes for your character. Players forge knives and hand them to the GM so the GM can stab you with them over and over. More knives = easier for the GM to pull you into the plot. A well-crafted backstory should carry roughly **7 knives** (never less than 3, rarely more than 15).

#### Knife inventory (tally backstory against this list)

| Category | Worth |
|---|---|
| Each named person the character cares about (living or dead) | +1 (a big family can bundle into 1 "family" knife) |
| Each phobia or trauma | +1 |
| Each mystery (unknown parentage, unexplained powers, missing memories) | +1 |
| Each personal enemy | +1 |
| Each ongoing obligation or loyalty | +1 |
| Each **failed** obligation | +1 |
| Each serious crime committed | +1 (a whole criminal life bundles into one BIG knife) |
| Each crime falsely accused of | +1 |
| Each experience of discrimination | +1 |
| Each favored item / heirloom | +1 |
| Each kept secret | +1 |

#### Rules of thumb

- **Vary the types.** Seven knives that are all dead family members make for a one-note character. Mix personal, historical, mystical, social.
- **Under 3 knives**: the GM has to work hard to involve you in anything; you'll feel like an NPC.
- **Over 15 knives**: sad edgelord territory. Teammates get stabbed by your splash damage, and the GM can't honor every thread.
- **Around 7** is the sweet spot Alex targets.
- Good GMs can **split** knives into smaller sharper knives, or **bundle** a PC's knife with another PC's to make a GIANT knife.

### The counterpoint (important nuance)

A top reply to the Knife Theory post (u/TwilightVulpine) argues that framing backstory elements purely as "knives to stab with" is limiting and a bit sadistic. Backstory elements can also:

- **Support** the PC (allies, mentors, favors owed to them)
- **Inform** the plot (unique knowledge, contacts, expertise the party needs)
- **Offer** hooks (a friend asks for a favor that pulls the party somewhere new)
- **Reward** the PC (heirlooms that turn out to be valuable, reputations that open doors)

**How Alex should apply this:** When tallying knives, also tag each one with a *non-stabby* use. A missing sibling is a knife, but they're also someone who might send a letter with intel. A favored heirloom is a knife, but it might also be the key to a hidden vault. Hand the GM **multi-purpose backstory elements** — they'll use them for both suffering and reward, and the character will feel more alive.

### How to help Alex with a new character

1. Read any existing character notes, campaign reference, or session-0 questionnaire.
2. Draft a backstory skeleton and **tally the knives** explicitly in a list at the bottom (e.g., "Knife count: 7 — mentor (alive, in debt to), dead sister, unknown father, magical phobia, failed duty to temple, stolen heirloom, hidden heresy").
3. For each knife, add a one-line **non-stabby use** (what this could offer the party or plot, not just what could go wrong).
4. Flag imbalance: too few knives, too many, all one category, or all "stab-only" with no supportive potential.
5. Stay on the *character concept* first — mechanics later. Don't optimize a character Alex isn't bought into.

---

## Mode 2: Tactical Prep & Combat Advice

**Trigger**: "how should I play this fight", "tactical prep", "what spells should I prep", "level up planning", "plan my next turn", "how do I survive X".

### Workflow

1. **Load the character.** Read Alex's PC note in the campaign folder. If missing, ask for class/level/subclass, key feats, notable items, and spell list.
2. **Load the situation.** What's the encounter, threat level, party composition, terrain, remaining resources?
3. **Read the relevant section of the 7 Aspects doc.** Don't recite the whole thing — pull the specific aspect that applies (e.g., if the PC is about to be surprised, read Terms of Engagement; if an open-field fight against flyers, read Maneuverability).
4. **Apply the Tactician playbook** if Alex is positioning advice for the whole party, not just his own turn — share *objectives*, not orders; use in-character framing when the GM dislikes metagame talk.
5. **Flag resource risk.** Is this a Low / Medium / High / Critical threat? Don't burn long-rest or non-renewable resources on a Low fight.
6. **Give 1–3 concrete options**, not a lecture. Each option should name the specific ability/spell/item and the expected outcome.

### Quick-reference: the 7 Aspects (expand via the full doc)

| # | Aspect | One-line principle |
|---|---|---|
| 1 | Terms of Engagement | Win the fight before it starts (Detection, Surprise, Initiative, Intel) |
| 2 | Maneuverability | Fastest combatant controls the range (Speed, Flight, Teleport) |
| 3 | Environment | Constrain theirs, open yours (Space, Obstacles, Obscurement) |
| 4 | Resource Management | Win the war, not one battle (Renewability × Threat Level) |
| 5 | Efficiency | Max effect per input (Action Economy, Opportunity Cost, Party Construction) |
| 6 | Offense | Have an answer for every scenario (damage vs. control, obscurement, immunities, legendary saves, anti-magic) |
| 7 | Defense | If they can't hurt you, you win (Basic, Ultimate, General, Specific) |

### Quick-reference: the Tactician playbook

- **Sailboat retrospective first** — Island (goal), Sails (strengths), Anchor (weaknesses), Rocks (risks), Sun (fun). Know the table before planning.
- **Distinguish negotiables from non-negotiables.** Adapt around PC concepts other players won't change.
- **Share objectives, not orders.** "We need to split the fight" beats "you cast Fireball at B3".
- **Spotlight control.** Applaud teammates for wins; own the losses yourself.
- **Bank account model.** Every push costs social capital. Pick battles.
- **In-character tactics.** Fold advice into roleplay when the GM values immersion.
- **Disagree and commit.** If consensus fails, back the plan 100% anyway — modeling it first earns the same treatment back.

### Level-up / spell prep checks

When Alex is leveling or refreshing a spell list, run through:

- Do I have options for **both** open and constrained environments? (Aspect 3)
- Do I have a **cantrip** for every combat role (damage type variety, different saves, attack rolls, obscurement-proof)? (Aspect 4)
- Do my concentration spells have **non-redundant** coverage? (Aspect 6)
- Action / Bonus Action / Reaction / Movement / Summon — can I fill **all five** each round? (Aspect 5)
- Do I have an answer for **anti-magic**, **legendary saves**, and the conditions most likely to land on me (Aspect 7 table)?

---

## Mode 3: Session Prep (as a player)

**Trigger**: "prep for tonight's session", "what should I remember going in", "catch me up on my character".

1. Read Alex's PC note and the latest recap/prep for that campaign.
2. Surface:
   - **Open knives** from the PC's backstory that haven't been used yet — flag as things to weave into RP.
   - **Unresolved threads** from prior sessions that involve this PC specifically.
   - **Relationships** with other PCs and NPCs — who does Alex's character owe? who owes him?
   - **Resource state** — consumables, slots, attunement slots, charges.
3. Draft 2–3 *roleplay goals* Alex could pursue this session (things his character wants that would move personal arcs forward).
4. Draft 1–2 *tactical readiness* notes (likely encounters, resource reservation, pre-combat buffs worth pre-casting if the session starts hot).

## Mode 4: Post-Session Character Development

**Trigger**: "debrief my character", "what did I learn about my PC this session", "process the session as a player".

1. Read the session recap (if the GM's skill produced one) or the Plaud transcript.
2. Update Alex's PC note with:
   - **New knives forged in play** (a new NPC he now cares about, a debt he just incurred, a secret he just learned)
   - **Knives the GM has already stabbed with** — cross them off or mark them resolved
   - **Character growth moments** — quotes, decisions, mannerisms that emerged in play
   - **Open arcs** — what does this character want next session?
3. If new NPCs or locations got established, add them to the campaign folder so they're ready for next time.
4. Do **not** create Things 3 tasks from in-fiction content. The only exception is real-life items Alex mentioned at the table (e.g., "I need to buy dice", "text the GM about scheduling").

---

## Rules of thumb

- **Don't optimize a character Alex isn't bought into.** Mechanical power means nothing if the concept bores him. Concept first, optimization second.
- **Don't metagame.** The Intel sub-aspect (Aspect 1) is about organic knowledge, not Monster Manual memorization. Frame advice from what the PC would plausibly know.
- **Respect the GM's style.** If the GM dislikes in-combat metagame talk, fold tactics into in-character speech. If the GM loves granular tactics, run full sailboat discussions.
- **Player ≠ character.** Be clear in notes when advice is IC (what the character would do) vs. OOC (what's mechanically best). Both are useful; don't conflate them.
- **Preserve the table's fun.** The Tactician doc is explicit: a good tactician builds teammates up. Don't produce advice that would make Alex step on another player's spotlight.
