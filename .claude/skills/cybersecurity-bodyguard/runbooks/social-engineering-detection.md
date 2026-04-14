# Social Engineering Detection

Stalkers and doxxers do more than scrape data brokers — they also call, text, and DM you and the people around you. Social engineering is how a casual threat becomes an escalating one.

## Red-flag patterns

### Authority + urgency
> "This is Detective Johnson with KCPD. We need to confirm your address for an active investigation — can you verify it's still [STREET]?"

Real police do not confirm addresses over the phone. Real police do not call from blocked numbers. Real police let you call the precinct back on a number you look up yourself.

**Response pattern**: "I need to call you back. What's your badge number and the main precinct number?" Then hang up, look up the number independently, and call.

### Familiarity + new channel
> "Hey, it's me, I lost my phone — can you text me at this new number? Can you also remind me of [small piece of info that would help the attacker]?"

This is the "I lost my phone" scam and it's how attackers harvest small pieces of context that make the next pivot credible.

**Response pattern**: Verify via a previously established channel (call the old number, DM on a shared platform you both use, ask a mutual friend).

### Impersonation of a known contact
Display name says "Mom" or "Boss", but the underlying email/number is new and doesn't match the contact you have.

**Response pattern**: Never trust display names. Always verify the underlying identifier. In iMessage, tap the contact at the top; if the email/number isn't in your contacts, be suspicious.

### Info-fishing via warm introductions
A mutual friend says "Hey, my friend [X] is new in town and wants to chat about [topic you care about]. Can you send them your number?"

The "friend" may be genuine and simply being a vector. The attacker built rapport with your friend first.

**Response pattern**: Route all new intros through the platform you trust (LinkedIn DM, Bluesky, etc.) before sharing phone/email. Look up the person yourself before accepting.

### Someone in your network asking odd questions
> "Does Alex still live in the [NEIGHBORHOOD]? I ran into someone asking."

Pay attention to the *asking* pattern more than the questioner. Stalkers pump people in your orbit for info. A single question is usually innocent; a cluster of related questions from different people over a short period is a pattern.

**Response pattern**: When a CRM contact relays a question about you — especially about your location, schedule, or relationships — log it in Security Log. Ask the contact for more details ("who asked? how do they know me?"). Often they won't remember; that's still data.

### Manufactured coincidence
Running into someone repeatedly who you "just met" — at coffee shops, gyms, grocery stores you frequent.

**Response pattern**: Real coincidence is once. Pattern is twice in different contexts. Log in pattern-log.md.

### Tech support pretext
> "Hi, this is Google Security. We've detected a login attempt from [city]. Can you confirm by reading us the code we just texted you?"

The code is a 2FA code for an account the attacker is actively taking over.

**Response pattern**: No legitimate provider asks for codes. Hang up immediately. Then check the actual account for security alerts.

### Pity / charity pretext
> "My daughter has [condition] and I saw your post about [related topic]. Can I tell you more?"

Emotional leverage + extended contact surface. Real requests don't require volatile personal info sharing.

**Response pattern**: Direct them to an intermediary (a charity, mutual friend, platform). Never share location, schedule, or family info with someone on this pretext.

## Verification workflow

When a message triggers a flag, the bodyguard skill runs this workflow:

1. **Identify the sender** — email address, phone number, or handle. Record the full raw identifier, not just the display name.
2. **Look up in People/ CRM** — does this match an existing contact? If yes, does the underlying identifier match what's stored in their frontmatter?
3. **If not in CRM** — Obsidian search for prior mentions. Any hit from a prior transcript / email?
4. **Check the signals above** — which ones fire?
5. **Output**:
   - If no CRM hit AND any signal fires → log + Things 3 task
   - If CRM hit BUT identifier mismatch → URGENT notification (mimicry)
   - If clean → pass through normally, let regular processing take over

Never auto-block or auto-reply.

## Verification by side channel

When a message might be from a known contact but something feels off, verify via a channel the attacker is unlikely to have. Ranked by trustworthiness:

1. Meeting in person
2. A previously-established video call
3. Calling a phone number you have from earlier contact
4. Asking a question only the real contact would know (not "what's your address" — something specific to your shared history, like "what was the thing you ordered at the restaurant on Tuesday")
5. DM on a platform you've used with them for > 1 year
6. Email you've corresponded on for > 1 year

Avoid verifying through:
- The channel the suspicious message came in on
- Any channel where identity could be forged (SMS, brand-new email addresses)
- Shared public info questions ("what high school did you go to") — this is LinkedIn-scrapeable

## When in doubt

Do not respond. Silence is a valid response. Legitimate parties will persist through safe channels; attackers usually pivot to a new target rather than escalate a cold lead.

## Family & partner training

Brief the people in your orbit (partner, close friends, parents) with this one-pager:

> If anyone contacts you asking about Alex — their location, schedule, who they're with, where they work, their health, anything — do three things:
>
> 1. Do not answer the question, even if it seems innocuous.
> 2. Say "Let me check with them and get back to you," then end the conversation.
> 3. Tell Alex within the hour.
>
> This is true even if the requester identifies as law enforcement, a journalist, a colleague, or a distant relative. Alex will tell you if any of those are real. If you're not sure, default to silence.

This is the single highest-leverage thing for anyone who might become a stalking target.
