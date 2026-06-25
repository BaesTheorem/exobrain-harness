"""Fun grab-bag — a small, offline slice of Fletcher's `swag.py` / text effects.

Five self-contained commands, no API keys, no DB, no network:
  !roll / !dice / !r   dice roller: `2d6+5`, `d20 adv`, `stats` (D&D abilities)
  !pick / !choose      pick one of several options
  !fight               "They Fight Crime!" buddy-cop generator
  !8ball               yes/no oracle
  !mock                sPoNgEbOb mocking text

Each tags its reply with a rolling quip from the shared ctx.quips registry.
"""

from __future__ import annotations

import random
import re

import discord

from handler import Context

MAX_DICE = 100
MAX_SIDES = 1000


# --- dice ---------------------------------------------------------------------

def _roll(n: int, sides: int) -> list[int]:
    return [random.randint(1, sides) for _ in range(n)]


def _parse_roll(expr: str) -> tuple[int, str]:
    """Parse a dice expression like `2d6+5` or `d20-1` into (total, detail)."""
    expr = expr.replace(" ", "")
    terms = re.findall(r"[+-]?[^+-]+", expr)
    if not terms:
        raise ValueError("Give me some dice to roll.")
    total = 0
    detail: list[str] = []
    for term in terms:
        sign = -1 if term.startswith("-") else 1
        body = term.lstrip("+-")
        m = re.fullmatch(r"(\d*)d(\d+)", body, re.I)
        if m:
            n = int(m.group(1)) if m.group(1) else 1
            sides = int(m.group(2))
            if not (1 <= n <= MAX_DICE and 1 <= sides <= MAX_SIDES):
                raise ValueError(f"Keep it to 1-{MAX_DICE} dice with 1-{MAX_SIDES} sides, please.")
            rolls = _roll(n, sides)
            total += sign * sum(rolls)
            piece = str(rolls) if n > 1 else str(rolls[0])
            detail.append(("-" if sign < 0 else ("+ " if detail else "")) + piece)
        elif body.isdigit():
            total += sign * int(body)
            detail.append(("- " if sign < 0 else "+ ") + body)
        else:
            raise ValueError(f"I can't parse `{term}`.")
    return total, " ".join(detail).strip()


# --- They Fight Crime! word lists --------------------------------------------

_FC_ADJ = [
    "shy", "scrappy", "suave", "antisocial", "retired", "world-weary", "hard-bitten",
    "chain-smoking", "addled", "renegade", "soft-spoken", "impetuous", "sharp-dressed",
    "blind", "psychic", "amnesiac", "uptight", "free-wheeling", "bookish", "feral",
]
_FC_NOUN = [
    "detective", "monk", "barista", "librarian", "archaeologist", "lounge singer",
    "ex-con", "nun", "hacker", "cowboy", "cab driver", "samurai", "stage magician",
    "park ranger", "lawyer", "fortune teller", "barbarian", "florist", "astronaut",
]
_FC_QUIRK = [
    "from a doomed timeline", "with a secret", "on her last case", "who can talk to ghosts",
    "haunted by a tragic past", "with nothing left to lose", "who's seen too much",
    "looking for redemption", "allergic to everything", "who plays by their own rules",
]


def _fight() -> str:
    a, b = random.sample(_FC_ADJ, 2)
    n1, n2 = random.sample(_FC_NOUN, 2)
    q1, q2 = random.sample(_FC_QUIRK, 2)
    p1, p2 = random.sample(["He's", "She's", "They're"], 2)
    return (f"{p1} a {a} {n1} {q1}. {p2} a {b} {n2} {q2}. "
            f"**They fight crime!** 🚔")


# --- magic 8-ball -------------------------------------------------------------

_EIGHTBALL = [
    "It is certain.", "Without a doubt.", "Yes, definitely.", "You may rely on it.",
    "As I see it, yes.", "Most likely.", "Outlook good.", "Signs point to yes.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "Cannot predict now.", "Concentrate and ask again.",
    "Don't count on it.", "My reply is no.", "My sources say no.",
    "Outlook not so good.", "Very doubtful.",
]


# --- spongebob mock -----------------------------------------------------------

def _mock(text: str) -> str:
    out, upper = [], False
    for ch in text:
        if ch.isalpha():
            out.append(ch.upper() if upper else ch.lower())
            upper = not upper
        else:
            out.append(ch)
    return "".join(out)


def setup(ctx: Context) -> None:
    h = ctx.handler
    q = ctx.quips

    q.add("fun.roll", ["The dice have spoken 🫡", "No takebacks 👀",
                       "Rolled fair, I swear ✨", "Math is hard, dice are easy ^_^"])
    q.add("fun.pick", ["My final answer 🫡", "Don't overthink it 👀",
                       "Blame me if it's wrong ✨", "Decision outsourced ^_^"])
    q.add("fun.fight", ["Pitch it to Netflix 🫡", "I'd watch it 👀",
                        "Season 2 when ✨", "Box office gold ^_^"])
    q.add("fun.8ball", ["Don't shoot the messenger 🫡", "The orb is never wrong ✨",
                        "I just read it, I don't write it 👀", "Spooky ^_^"])
    q.add("fun.mock", ["cOuLdN'T hAvE sAiD iT bEtTeR 🫡", "you're welcome 👀", "art ✨", "no notes ^_^"])

    @h.command("!roll", "!dice", "!r", description="Roll dice: `2d6+5`, `d20 adv`, or `stats`", cooldown=1.5)
    async def roll_cmd(message: discord.Message, args: list[str], ctx: Context):
        text = " ".join(args).lower().strip()
        words = text.split()
        try:
            if text in ("stats", "dnd"):
                blocks = []
                for _ in range(6):
                    r = sorted(_roll(4, 6), reverse=True)
                    blocks.append(f"**{sum(r[:3])}**  ({', '.join(map(str, r))}, dropped {r[3]})")
                body = "🎲 Ability scores (4d6, drop lowest):\n" + "\n".join(blocks)
            elif "adv" in words or "advantage" in words or "dis" in words or "disadv" in words or "disadvantage" in words:
                r = _roll(2, 20)
                advantage = "adv" in words or "advantage" in words
                keep = max(r) if advantage else min(r)
                label = "advantage" if advantage else "disadvantage"
                body = f"🎲 d20 ({label}) → {r} → **{keep}**"
            else:
                total, detail = _parse_roll(text or "d20")
                body = f"🎲 `{text or 'd20'}` → {detail} = **{total}**"
        except ValueError as e:
            await message.reply(
                f"{e}\nTry `!roll 2d6+5`, `!roll d20 adv`, or `!roll stats`.",
                mention_author=False)
            return
        await message.reply(q.tag(body, "fun.roll"), mention_author=False)

    @h.command("!pick", "!choose", description="Pick one: `!pick tacos, sushi, ramen`", min_args=1)
    async def pick_cmd(message: discord.Message, args: list[str], ctx: Context):
        raw = " ".join(args)
        opts = [o.strip() for o in re.split(r",| or ", raw) if o.strip()]
        if len(opts) < 2:
            await message.reply(
                "Give me at least two options, like `!pick tacos, sushi`.",
                mention_author=False)
            return
        await message.reply(q.tag(f"🤔 I pick **{random.choice(opts)}**.", "fun.pick"), mention_author=False)

    @h.command("!fight", description="They Fight Crime! generator", cooldown=2.0)
    async def fight_cmd(message: discord.Message, args: list[str], ctx: Context):
        await message.reply(q.tag(_fight(), "fun.fight"), mention_author=False)

    @h.command("!8ball", "!8", description="Ask the magic 8-ball a yes/no question", min_args=1, cooldown=1.5)
    async def eightball_cmd(message: discord.Message, args: list[str], ctx: Context):
        await message.reply(q.tag(f"🎱 {random.choice(_EIGHTBALL)}", "fun.8ball"), mention_author=False)

    @h.command("!mock", description="sPoNgEbOb-MoCk some text", min_args=1)
    async def mock_cmd(message: discord.Message, args: list[str], ctx: Context):
        await message.reply(q.tag(f"🧽 {_mock(' '.join(args))}", "fun.mock"), mention_author=False)
