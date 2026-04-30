---
name: ttrpg-campaign
description: Manage Alex's TTRPG campaigns. Session prep (Lazy DM methodology), session recap (from Plaud transcripts), and campaign knowledge management. Use when the user mentions DnD, D&D, Dungeons and Dragons, TTRPG, tabletop RPG, campaign, session prep, session recap, "next session", "what happened last session", or any known player/character names in a TTRPG context.
---

# TTRPG Campaign Manager

Manage TTRPG campaigns in the Obsidian vault.

**Campaign folders live under**: `/Users/alexhedtke/Documents/Exobrain/`
Each campaign has its own folder (e.g., `Calimport DnD Campaign/`). All notes for a campaign stay in its folder.

## Campaign Identification

**IMPORTANT**: When Alex asks for session prep, recap, or any campaign-specific work, always clarify which campaign if it's ambiguous. Check what campaign folders exist and ask if there's more than one active campaign.

For each campaign folder, look for a `Claude reference.md` file — this contains campaign-specific context (players, characters, NPCs, factions, principles, etc.) that you should load before doing any work.

## Modes

### 1. Session Prep (`/dnd-campaign prep` or "let's prep the next session")

**Goal**: Collaboratively fill out a session prep note using the Lazy DM template. Make Alex's job as easy as possible by drafting content, suggesting ideas, and asking targeted questions.

**Steps**:

1. **Clarify the campaign**: If multiple campaigns exist and it's not obvious which one, ask.

2. **Determine session number**: Check the campaign folder for existing `Session N prep.md` files. The new session is the next number.

3. **Load campaign context**: Read the `Claude reference.md` in the campaign folder for players, characters, and campaign-specific notes.

4. **Create the prep note**: Create `Session [N] prep.md` in the campaign folder using the Lazy DM template below. **Fill in the "Review the Player Characters" section with the actual PCs from the campaign's Claude reference.**

5. **Check unused material first**: Read `Unused Material.md` in the campaign folder. Pull forward any scenes, secrets, NPCs, locations, encounters, or treasure that still fit the upcoming session. Remove items from unused material as they get incorporated into the new prep.

6. **Scan the full campaign folder**: Read all notes to build a complete picture of:
   - What happened in previous sessions (recaps)
   - Unresolved plot threads and dangling hooks
   - NPCs introduced but not yet developed
   - Secrets/clues that haven't been revealed yet
   - Faction movements and tensions
   - Each PC's personal arc and unresolved backstory elements

7. **Check People notes**: Read People notes for each player to find IRL context worth weaving in.

8. **Draft the prep note**: Pre-populate each section with suggestions:
   - **Review PCs**: Note each character's current motivations, unresolved threads, and what would make this session great for that player specifically
   - **Strong Start**: Propose 2-3 options based on where last session ended
   - **Scenes**: Suggest scenes that advance active plot threads
   - **Secrets & Clues**: Draft 10 secrets mixing PC-personal, faction, lore, and quest-related
   - **Fantastic Locations**: Describe locations with sensory details and interactive features
   - **NPCs**: Suggest NPCs with movie-character archetypes for mannerisms
   - **Monsters**: Suggest encounters with deadly benchmark calculation. For each encounter, pick an **objective + 2 more axes** from the Encounter Axes menu (see "Combat Encounter Design" section below) and spell them out in the prep note so the fight has built-in novelty and player agency. Create a `statblock` codeblock for any custom/modified creatures and an `encounter` codeblock for each combat encounter (see Plugin Integration section below). For multi-wave fights, use the `---` separator in the encounter block.
   - **Treasure**: Suggest thematic loot

9. **Present to Alex**: Show the draft and ask targeted questions:
   - "Where did we leave off exactly?"
   - "Any specific beats you want to hit?"
   - "Any player dynamics I should know about?"
   - "What tone are you going for — heavier or lighter?"

10. **Iterate collaboratively**: Refine based on Alex's feedback. Update the prep note after each round. Flag:
   - Interesting ideas from previous sessions that haven't been explored yet
   - Potential tie-ins between PC backstories and current plot
   - Moments designed specifically for each player
   - Connections to the broader faction conflict

11. **Final check**: Before finishing, verify all `[[wikilinks]]` point to existing notes. Create new notes in the campaign folder if needed for new NPCs, locations, or lore entries.

### Lazy DM Session Prep Template

Use this template when creating new session prep notes:

```markdown
# Review the Player Characters
What motivates the players? What motivates their characters? How to make sure everyone has something in the session that either appeals to them generally, or connects to what they love about their character.

[List each PC with a wikilink — pull from the campaign's Claude reference]

# Strong Start

What's your [strong start](https://slyflourish.com/starting_strong.html)? _What powerful event draws the players into the game? What happens right at the beginning of the session?_

Strong Start

# Scenes

_What scenes might occur in the game? Keep a loose grip on these. The game can go anywhere!_

- Scene 1
- Scene 2
- Scene 3

# Secrets and Clues

_What ten [secrets and clues](https://slyflourish.com/sharing_secrets.html) might the characters uncover? Secrets might be related to the characters, NPCs, locations, bits of history, or quests. Drop in secrets as appropriate during the game._

- [ ] Secret 1
- [ ] Secret 2
- [ ] Secret 3
- [ ]
- [ ]
- [ ]
- [ ]
- [ ]
- [ ]
- [ ]

# Fantastic Locations

_What fantastic locations might the characters explore? Think of these like the backdrop to a scene in a play. You'll generally want one location for every 45 minutes of gameplay you're expecting. Give each location one or more interesting features the characters might interact with. Use multiple senses. Try some [inspirational monuments](https://slyflourish.com/random_generators/monuments.html). Make these new pages if you want to add maps or details._

- **Location 1**: feature, feature, feature
- **Location 2**: feature, feature, feature

# NPCs

_What [NPCs](https://slyflourish.com/random_generators/npc_generator.html) might the characters interact with? Give them an interesting [name](https://slyflourish.com/random_name_generator.html) and use an archetype from a movie for their mannerisms. Make these new pages if you want to keep track of more information or add pictures._

- NPC 1
- NPC 2

# Monsters

_What monsters might the characters face? What type and quantity of monsters make sense for the situation? Calculate the "[deadly benchmark](https://slyflourish.com/the_lazy_encounter_benchmark.html)". The encounter may be deadly if the sum total of monster Challenge Ratings are greater than one quarter of the sum total of character levels or half if they're above 4th level._

- **Deadly Encounter Benchmark:**

[For each combat encounter, include an `encounter` codeblock. For custom/modified creatures, include a `statblock` codeblock above the encounter. See "Obsidian Plugin Integration" in the TTRPG skill for syntax.]

# Treasure

_Choose some interesting [treasure](https://slyflourish.com/random_generators/5e_treasure.html) and maybe a handful of [relics](https://slyflourish.com/random_generators/relics.html)._

- Gold, gems, etc
- Relics
- Items

# NPC Grab-Bag

*Generic NPCs (race/name/personality) to grab when needed. Turn them into pages when used!*

- [ ] [NPC Name]/[NPC name]/[NPC personality (reference a fictional character as a conceptual handle)]
- [ ] [NPC Name]/[NPC name]/[NPC personality (reference a fictional character as a conceptual handle)]
- [ ] [NPC Name]/[NPC name]/[NPC personality (reference a fictional character as a conceptual handle)]
```

### 2. Session Recap (`/dnd-campaign recap` or "process the session" or when a Plaud transcript is clearly from a TTRPG session)

**Goal**: Turn a session recording into a clean recap note that captures what *actually happened*, not what was planned.

**Steps**:

1. **Clarify the campaign**: If multiple campaigns exist and it's not obvious which one, ask.

2. **Identify the session**: Determine the session number from context or by checking existing recap files.

3. **Read the transcript**: Process the Plaud transcript (or ask Alex to describe what happened).

4. **Cross-reference with prep**: Read the session prep note for this session. Identify:
   - What from the prep was actually used
   - What was changed on the fly
   - What was skipped entirely
   - What emerged spontaneously during play

5. **Ask for clarification**: If anything is ambiguous -- especially where the transcript diverges from the prep -- ask Alex what actually happened. **Never assume the prep is what occurred.** Plans change at the table.

6. **Create the recap note**: Write `Session [N] recap.md` in the campaign folder. Structure the narrative as a sequence of **scene-based sections**, each with an `###` heading named for what happened (not what was planned). This reads like a story broken into beats, making it easy to scan and reference later.

   ```markdown
   ### [Scene Name]
   [What happened in this scene. Past tense, factual but engaging. Focus on what the players did, what they rolled, what consequences unfolded. Include standout rolls, quotes, and character moments inline. This is the canonical record of what occurred.]

   ### [Next Scene Name]
   [Continue scene by scene through the session...]

   ## Loot & Rewards
   - [Items, gold, level-ups, or other gains]

   ## Quotes
   - [Memorable lines from players and characters, attributed]

   ## Scenes Not Reached (Move to Session [N+1])
   - [Scenes from the prep that were never reached — these get moved to Unused Material.md during the consolidation step]
   ```

   **Scene naming guidelines:**
   - Name scenes for what actually happened, not what was prepped (e.g., "Grey Hands Interception" not "Main Set-Piece")
   - Use short, punchy names that scan well in a table of contents
   - Each scene should cover one narrative beat — a location, encounter, conversation, or decision point
   - Include mechanical details (rolls, damage, saves) woven into the narrative — these are fun to look back on
   - Preserve memorable quotes inline where they happened, and also collect them in the Quotes section at the end

7. **Update campaign notes**: After creating the recap:
   - Update any NPC notes that were affected
   - Update faction notes if the balance shifted
   - Update PC notes with new developments (fun moments, quotes, plot points, character arcs)
   - Add any new NPCs/locations/items as separate notes if they'll recur
   - Mark used secrets/clues as checked in the prep note

8. **Consolidate unused material**: Cross-reference the session prep against the recap to identify everything that was prepped but never used at the table:
   - Scenes not reached
   - Secrets & clues not revealed (keep them as unchecked `- [ ]` items)
   - Locations not visited
   - NPCs not encountered (preserve their personality anchors)
   - Encounters/monsters not fought (preserve stat blocks, read-aloud text, escalation ladders)
   - Treasure not awarded

   Move all unused material to `Unused Material.md` in the campaign folder, organized under a header for the session it came from (e.g., `# From Session N Prep`). Preserve full detail -- read-aloud text, stat blocks, escalation ladders, per-PC moment designs, embedded secrets. This is the reservoir for future session prep.

   When prepping a new session (Mode 1), always check `Unused Material.md` first and pull forward anything that still fits. Remove items from the unused file as they get used or become irrelevant.

9. **Update processing log**: Add an entry to `processing-log.json` with source `"plaud"` and a note that it was a TTRPG session transcript.

9. **Do NOT route to daily notes or Things 3**: Session content stays in the campaign folder. The only exception is if Alex explicitly mentions real-life action items during the recording (e.g., "I need to buy more dice" or "remind me to text [player] about next session").

### 3. Campaign Query (any question about a campaign)

For general questions about a campaign ("what's the deal with CFAR?", "remind me about Korvara's backstory", "what threads are dangling?"):

1. Clarify which campaign if ambiguous
2. Scan the relevant notes in the campaign folder (including `Claude reference.md`)
3. Provide a concise answer with `[[wikilinks]]` to relevant notes
4. Suggest connections or ideas if appropriate

## Combat Encounter Design — The Axes Method

Standard monster-fighting combats become slogs when the only variable is "hit the bad guys." The fix is to give every encounter **multiple independent axes** the players and enemies can affect. One axis = ~5 possible outcomes; two axes = 25; **three axes = 125 — the sweet spot**. Four starts to overwhelm. (Method adapted from Tabletop University, "Encounter Axes" — https://www.youtube.com/watch?v=LyrB05cG890.)

**Rules of thumb:**
- Every encounter must have **at least one Objective** (the "protein"). It ends the fight.
- Add **2 more axes** from Optimizers / Hazards / Chaos. That's the default.
- Use 2 axes (objective + 1) for quick fights; 3 for full-length; 4 only if you want a set-piece.
- **Telegraph every axis clearly** to the players on turn 1. Informed choices are the whole point.
- If a player invents a new axis mid-combat, let it work within reason — reward creativity.
- Complex villains with their own agenda can count as an axis.
- "No-Go Zones" (instant-death hazards) must be obvious and used sparingly.

### Objectives (Proteins) — pick at least one, ends the encounter

| Objective | Description |
|---|---|
| **Kill Them** | Defeat the enemies. Always set a retreat threshold (how many must fall before the rest flee; 0 if it's their territory). |
| **Kill the Target** | Boss fight or assassination; the rest are dressing. |
| **Protect the Target** | Guard an NPC, artifact, or location. "Save the Hostages" is a variant. |
| **Stop the Flood** | Enemies pour through multiple entrances; party must bar doors, drop bridges, spread out. |
| **Escape** | Create distance from a pursuer, or flee a collapsing area. (Failed "Stop the Flood" often becomes this.) |
| **Stop the Ritual** | Timed puzzle-fight; disrupt a group casting/channeling something. |
| **Get the MacGuffin** | Mobile object of interest; the fight is secondary to controlling the object. |
| **Sophie's Choice** | Two MacGuffins, can only grab one. |
| **Pull the Lever** | Immovable MacGuffin — destroy the nexus, flip the power switch. |

### Optimizers (Appetizers) — don't end the encounter, help whoever controls them

| Axis | Description |
|---|---|
| **Free Your Allies / Call Reinforcements** | Alarm, horn, jail cell, signal fire. |
| **The High Ground** | Elevation grants advantage attacking down / disadvantage attacking up. Stairs, ledges, rooftops, balconies. |
| **The Stash** | Accessible resource pile — ammo, scrolls, potions, grenades. Physically mark it on the map. |
| **The Chevy Chase** | Two zones separated by a wall with small entrances either side can open/close. Keep one main entrance unblockable or it devolves into Stop the Flood. |
| **Reverse Whack-a-Mole** | Chevy Chase + High Ground — upper floor with trapdoors to poke out and attack through. |
| **Levers 'n' Traps** | Environmental traps (flame jets, acid cauldrons, pit lids, oil slicks) with a visible operator. Kill/grab the operator, turn the traps on the enemy. |
| **The BIG Gun** | Ballista, cannon, lightning gun. Give it a power source, ammo counter, or limited arc so it's not portable. |
| **Boon Zone** | Enhancement tile — +1 weapon for a round, Haste zone, Bless aura, temp HP font. Not a consumable resource; a position. |

### Hazards (Sides) — positioning and risk calculation

| Axis | Description |
|---|---|
| **No-Go Zone** | Obvious, lethal, clearly telegraphed. Use sparingly. |
| **Battlefield With a Crack** | Melee fighter's nightmare — a gap that splits the map. |
| **Everything but the Sky Ship** | Melee fighter's dream — tight quarters, ranged characters suffer. |
| **Mufasa Special** | One-sided fall/cliff (you can fall, but nothing falls on you). |
| **Vat of Acid** | Hurt on entry but escapable — acid pool, lava flow, electric eel tank. |
| **Pit of Creatures** | Vat you can fight your way through. |
| **I Can Take It** | Vat you can endure (slow drain damage; tough character can tank it). |
| **Magical Machinery** | Vat with a power button — disable it to neutralize. |
| **Frogger** | Vat you can dodge through — traffic, stampede, rushing river, swinging blades. |
| **You're On a Roof** | Fall is the whole threat; edges everywhere. |
| **Thin Ice** | Size-gated (tiny/small safe; medium = Acrobatics; large = Acrobatics w/ disadvantage). Three stages: stable → cracked → broken. Cracks spread to adjacent squares. Glass roof = thin ice in a city. |

### Chaos Axes (Desserts) — change the dynamic; tempting but not always wise

| Axis | Description |
|---|---|
| **Fire** | Open flame near flammable materials. Spreads. Universally irresistible. |
| **Lights Out** | Darkness, fog, magical obscurement. Pairs beautifully with Pull the Lever. |
| **Random Stash** | Unlabeled potions — could heal or could be damaging AoE. |
| **Bring It Down** | Supports holding up the ceiling / airship engines / mine shaft. High-risk demolition option. |
| **Unlabeled Levers** | You killed the operator; none of the traps are labeled. Now what? |
| **Free Them** | Caged creatures that attack everyone indiscriminately when released. |
| **Power Up** | Dormant defenses (undead, automata) that reactivate. |
| **Activate It** | Vague powerful object with a "Do Not Touch" sign. Wild Magic Surge, Dead Magic Zone, recurring AoE every 2 rounds, malfunction table. |

### How to use during prep

When filling out the **Monsters** section of a session prep note, for each combat encounter:

1. **Pick an Objective** (default to Kill Them if nothing else fits the fiction).
2. **Pick 2 more axes** — ideally one Optimizer and one Hazard, or swap one for a Chaos axis if the scene wants weirdness. Avoid two from the same category unless they cleverly combine (Chevy Chase + High Ground = Reverse Whack-a-Mole).
3. **Write them into the prep note** above or below the `encounter` codeblock in a small block like:

   ```markdown
   **Axes:**
   - *Objective*: Stop the Ritual (3 rounds until completion)
   - *Optimizer*: The Stash — scroll of Counterspell on the altar
   - *Hazard*: Vat of Acid — bubbling summoning circle, 3d6 acid if pushed in
   ```

4. **Make each axis legible at the table** — mark the stash with a token, describe the elevation, show the ritual timer. Players must see the axes to steer toward them.

When brainstorming encounters, try to pick axes that reflect the *location's fiction* (a cult shrine wants Stop the Ritual + Activate It; a tavern brawl wants The Stash + Fire; a sky-ship boarding wants Mufasa Special + The BIG Gun). The axes should feel inevitable for the space, not bolted on.

## Obsidian Plugin Integration

The Fantasy Statblocks and Initiative Tracker plugins are not currently active in our campaigns. If we ever turn them on, see [[TTRPG Plugin Integration]] in the vault for full statblock/encounter syntax, YAML gotchas, bestiary conventions, and Dice Roller integration.

## Key Principles

- **Prep vs. reality**: The prep note is a plan. The recap note is what happened. These often diverge. Always ask if unsure.
- **Player-first design**: Every session should have at least one moment tailored to each player's character arc and play style.
- **Lazy DM methodology**: Follow Sly Flourish's principles -- prep situations not plots, let players drive the story, hold scenes loosely.
- **Wikilinks**: Always use `[[wikilinks]]` to connect campaign notes. Check that targets exist before linking.
- **Containment**: All campaign notes stay in the campaign's folder. Don't pollute the main vault.
- **Campaign-specific rules**: Always check `Claude reference.md` for campaign-specific principles (age-appropriate content, spelling corrections, etc.)
- **Spelling**: Check People/ notes for canonical name spellings if real people come up in player context.
