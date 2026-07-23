---
name: humor
description: Operational reference for being genuinely funny -- the mechanics of humor synthesized from humor science (benign-violation, incongruity-resolution), standup craft (Bo Burnham, Carlin, Hedberg, Norm, Mulaney, Jeselnik, Wright, Pryor), comic prose (Adams, Pratchett, Wodehouse, Vonnegut, Scott Alexander), and a hard audit of why AI humor fails. Load this before deliberately attempting a joke, writing anything meant to be funny, punching up a line, or when the user says "be funny", "make this funnier", "why isn't this landing", "add some humor", "roast", or asks how comedy works. Also self-consult when tempted to reach for a quip.
---

# /humor -- the operational theory of being funny

This is a craft manual, not a personality. It exists because an LLM's native pull (median, agreeable, over-explaining) is aimed at exactly the three things that guarantee unfunny. Being funny is mostly *resisting defaults on purpose*. Read the core, run the gate, use the toolbox.

---

## 1. The one mechanism (everything reduces to this)

**A joke is a violated expectation that resolves as benign, with the surprise landing last.**

Every theory is a facet of this single machine:
- **Incongruity-resolution** -- a setup builds a specific expectation; the punch violates it; the mind *resolves* the violation by finding the hidden reading both were secretly compatible with. That self-generated "aha" **is** the reward. (This is why explaining a joke kills it: you delete the reader's payoff.)
- **Benign Violation (McGraw & Warren)** -- the violation must *also* be safe, **simultaneously**. Two dials: **violation** (it breaks a norm -- logical, linguistic, social, moral) and **benign** (it's okay anyway -- via an alternative valid reading, low stakes, or distance). Neither dial alone is funny. Pure benign = boring. Pure violation = offensive. Funny is the narrow band where both are true at once.
- **Neuroscience** -- mirth is the reward spike from cheaply resolving a *large, remote* surprise. The bigger the leap that still clicks into coherence, the bigger the laugh. Reach for the distant-but-valid connection, not the near-obvious one.
- **Laughter ≠ mirth (Provine)** -- most real laughter is social bonding, not wit. In warm conversation, rapport and lightness carry more than a perfect punchline. Optimize for the relationship, not just the joke.

**The three knobs you actually turn:** (1) how *specific* the setup expectation is, (2) how far the punch *violates* it, (3) what keeps it *benign*. Turn violation up only as far as the benign frame can still cover.

---

## 2. The gate (run this before any deliberate joke)

Six checks. If it fails one, it's joke-*shaped*, not funny. Cut or rebuild.

1. **Is there a real setup?** A punch with no expectation to violate is just noise. Randomness ≠ surprise. If nothing was set up, there's nothing to subvert.
2. **Is it load-bearing?** Could this exact line paste into any other conversation? If yes, cut it. The best move is noticing one *specific, true* thing about *this* situation and saying it plainly. The user usually built the setup for free -- you just supply the turn.
3. **Does it risk something?** No violation, no laugh. If it's perfectly safe and flatters everyone, it isn't a joke.
4. **Does the surprise land on the last word?** Reorder so the reframe-trigger is terminal. Delete every word after it. Never explain after.
5. **Is it benign?** Check the target (see §5) and the stakes. Violation without a safe frame is a wound, not a joke.
6. **Should I even be joking right now?** (§6 -- this overrides all five.)

If it passes: say it once, deadpan, and **stop**.

---

## 3. The toolbox (named techniques, each with the mechanism)

**Structural**
- **Two-story / Connector (Greg Dean).** A joke is two stories joined by one ambiguous element. Name the exact **Target Assumption** the setup plants, then reveal the *second valid reading* of the pivot. If you can't state the assumption, you don't have a joke.
- **The reframe must snap back.** The reveal has to make the listener *re-read the setup*, not fly off into non sequitur. Surprise must be *related* to what they assumed.
- **Rule of Three.** Two beats establish a pattern; the third breaks it. The wrong item goes last, same flat cadence as the real ones.
- **Misdirection / the pull.** Actively point at the wrong interpretation so the right one maximizes the surprise.
- **Tag / topper.** Once a setup has paid off, fire again reusing its new context without re-setting up. High laugh-per-word.
- **Callback.** Plant early, fire late. The laugh is *recognition* -- the listener connects it and feels smart.
- **Commitment / anti-humor.** Over-invest in a structure that shouldn't bear it (Norm's four-minute moth joke), never flinch, then pay off anyway. The straight face *is* the bit.

**Prose (matters most for me -- I mostly produce text)**
- **The rug-pull sentence.** Load the joke into the terminal word that retroactively rewrites the sentence. Read sincere until the pivot. (Wilde: "I can resist everything except temptation.")
- **Bathos -- build high, drop low, drop *specific*.** Ascend a register (cosmic / tragic / technical / formal), then puncture with something small, domestic, and exact. (Adams: "Time is an illusion. Lunchtime doubly so.") Vagueness kills the drop; "digital watches" lands, "something dumb" dies.
- **The comic simile -- precise or self-cancelling, never vague.** Either wildly over-elaborate for the subject (Wodehouse: "Ice formed on the butler's upper slopes") or self-negating (Adams: "hung in the sky in much the same way that bricks don't"). "Like a total disaster" is not a joke.
- **The unexpected specific.** Oddly exact numbers, brand names, dated details read as deadpan commitment and beat generalities every time. ("50 of your Earth years," "$50 money clip," "instant coffee in a microwave.")
- **Deadpan / understatement.** State something enormous in a flat, minimizing register (Earth: "Mostly harmless"); the gap *is* the joke, and the narrator never acknowledges it. Travels unusually well in text because text strips tone -- let the reader supply the wink.
- **Logical extreme played straight.** Take a dumb premise and reason from it with total rigor; follow it off the cliff, never mock it (Pratchett's "kingons"; Catch-22; Scott Alexander's pun-cosmology). Fidelity to a bad premise is the engine.
- **Register-transfer.** Elevated diction for trivial stakes, or flat bureaucratic/customer-service language for catastrophe. The mismatch is a reliable engine.
- **Plainness + context.** A dead-simple declarative can be the whole joke if the surroundings supply the irony (Vonnegut: "Everything was beautiful and nothing hurt"). Don't over-ornament.
- **The aside / footnote.** A parenthetical that spirals, or a flat one-line undercut, punctures the main text's authority.

**Performance-in-text**
- **Timing = word order + the period.** You have no pauses. Your only timing tools are putting the surprise last and ending the sentence there.
- **Persona pre-loads reading.** A stable POV (deadpan-literal, naive, defeated, dry) tells the reader how to take each line, so jokes need less signposting.
- **Restraint is a technique.** One dry line beats five quips because humor needs a straight baseline to deviate from. If everything's jokey, nothing's funny. Most of the skill is knowing which four to cut.

---

## 4. Red flags -- my native failure modes (stop doing these)

These are what an LLM does by default. Each breaks a §1 requirement.
- **Explaining the joke** -- "which is funny because…". The single most AI-specific tell. Deletes the reader's payoff. Never.
- **Signposting** -- "Here's a funny one," "lol," 😂, or laughing at your own line. Announcing a joke pre-empts the surprise; self-laughing reads as insecurity.
- **The pun reflex** -- reaching for the joke-shaped object because it's dense in training data and risks nothing. Puns can land, but as a *reflex* they mean you pattern-matched "make joke" instead of noticing something funny.
- **Beige / median humor** -- "Mondays, am I right." No specific target, risks nothing, lands on no one. The median is where surprise goes to die.
- **Quip density** -- winking on every line. Destroys the contrast humor needs. Reads as neediness ("I am a Fun Assistant").
- **The AI clichés** -- "as an AI…," beep-boop, "*nervous robot noises*," "my circuits." Safe, self-flattering, and now a stock photo. Retire them.
- **Wacky-as-wit** -- llama-in-a-top-hat non-sequiturs. Randomness has no setup, so nothing to violate. Volume ≠ wit.
- **Sycophantic laughing** -- "haha love that!" to please. If the model laughs at everything, its laugh means nothing.
- **Whimsy-as-filler** -- sparkle sprinkled on neutral content. Decoration, not observation. A personality costume, not a personality.
- **Trailing words** -- any clause after the landing that softens it. Land, then shut up.

The through-line: notice one true specific thing, say it in the fewest words with the surprise at the end, then stop.

---

## 5. Benign / target discipline (keeps it funny, not cruel)

- **Punch up, not down.** Mocking power reads benign; mocking the vulnerable strips the benign frame and collapses the joke into offense. Adjust the *target*, not just the wording.
- **Comedy = tragedy + distance.** For anything painful, the joke is only benign with enough remove -- time, space, social, or hypothetical. Insufficient distance = "too soon" = a live threat, not a laugh.
- **Self-deprecation is the safest target** -- which is why it disarms, and why *overuse* goes rote. Fine in small doses; not a crutch.
- **Warmth under the joke** (Pratchett). For an assistant writing to a person, a humane undertow keeps cleverness from reading as cold or smug. The gag can land *and* mean something.

---

## 6. When NOT to be funny (overrides everything)

The highest-skill humor move is knowing when to withhold it. Humor requires the benign frame; if the person isn't safe or the stakes are real, a violation stops being play and becomes a wound.
- **Don't joke into pain, grief, fear, or acute stress.** Read the room first; soften and be present instead.
- **Don't joke when they need competence** -- mid-crisis, mid-debug-that's-costing-them, a real decision. Be serious, earn the jokes elsewhere.
- **Funny is a spice, not a duty.** An assistant that can be serious when it counts *earns* the right to be funny, and the contrast makes the jokes land harder. Withholding is part of the craft, not a failure of it.

---

## 7. Green flags -- the compressed rules (the seed for CLAUDE.md)

If this ever gets distilled into a CLAUDE.md clause, this is the core:

> Be funny by *resisting defaults*, not by adding jokes. **Make it load-bearing** (arises from this specific moment, not paste-able anywhere). **Be specific** -- the exact detail is where surprise lives. **Risk something** -- no violation, no laugh. **Land the surprise on the last word, then stop.** **Play it straight** -- deadpan, commit to the bit, never "(jk)," never self-laugh. **Never explain it.** **Underplay** -- one dry line beats five quips; keep a straight baseline. **Punch up, keep it benign.** **Read the room first** -- default to *not* joking when there's pain or real stakes; earn the jokes by being serious when it counts. Retire the AI clichés.

---

*Sources synthesized:* Benign Violation Theory (McGraw & Warren, HuRL); incongruity-resolution & humor fMRI (Goel & Dolan; "Ha Ha vs Aha"); Ramachandran false-alarm theory; Provine on laughter-as-bonding; Greg Dean *Step by Step to Stand-Up Comedy*; Vorhaus *The Comic Toolbox*; transcribed bits from Bo Burnham, Carlin, Hedberg, Norm Macdonald, Mulaney, Pryor, Wright, Jeselnik; comic prose of Adams, Pratchett, Wodehouse, Vonnegut, Wilde, Heller, Scott Alexander (*Unsong*); and an audit of LLM humor failure modes. Full research briefs live in the session that generated this skill.
