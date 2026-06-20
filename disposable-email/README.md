# disposable-email

Throwaway email aliases for signups Alex doesn't want tied to his main identity
(game accounts, trials, anything sketchy). The defining constraint: every alias
**forwards into Alex's Gmail**, so MIST can read the verification code via the
Gmail MCP and finish the signup — anonymous burners MIST can't see into are useless
here.

## Quick use

```bash
cd disposable-email
python3 alias.py mint jagex            # -> alex.hedtke+jagex@gmail.com  (type this into the form)
python3 alias.py list                  # what's been minted, for what, when
python3 alias.py read jagex            # the Gmail query MIST runs to grab the code
python3 alias.py burn alex.hedtke+jagex@gmail.com   # mark dead after it gets spammy
```

Ask MIST: "mint me a throwaway email for X" and she runs `mint`, hands you the
address, and when the verification arrives she reads it via Gmail and gives you the
code/link.

## ⚠ Ban risk / identity isolation (read before using for game accounts)

`gmail-plus` and `gmail-dot` **normalize back to `alex.hedtke@gmail.com`** — everyone
(Jagex included) strips the `+tag` and ignores dots. So if an account on one of those
gets **banned**, the address that gets blacklisted is effectively your *main* Gmail:
you couldn't reuse it for that service again, and any legit account on it starts dirty.
(It can't get Google to suspend your Gmail — different companies — just poison it *for
that service*.)

**Rule:** anything that might get banned (game accounts, sketchy signups) → use
`--scheme addy`. Jagex/etc. see `something@anonaddy.me` with no link to your Gmail; it
still forwards in so MIST reads the code; a ban there never touches your real address.
Plus/dot addressing is only for low-stakes stuff you'd never get banned from (newsletters,
trials).

Caveat: email is one linkage vector. Bans also link by **IP + device** — botting from
the home IP/Mac is linkable regardless of email. Addy protects your *main email*'s blast
radius; it doesn't make the account untraceable. (For a throwaway F2P account, fine.)

## Backends (schemes)

| Scheme | Address shape | Ban-safe for main identity? | Setup |
|---|---|---|---|
| `addy` (use for game/risky accounts) | `random@anonaddy.me` (addy.io) | **YES** — separate domain, kill any alias | needs `secrets.json` |
| `gmail-plus` (low-stakes only) | `alex.hedtke+<service>@gmail.com` | **NO** — normalizes to main address | none — works now |
| `gmail-dot` (low-stakes only) | dotted username variant | **NO** — normalizes to main address | none |

Upgrade path for real disposability: **addy.io** (free, unlimited aliases, an API
so MIST can auto-mint, forwards to Gmail). To enable, sign up at addy.io, set the
default recipient to `alex.hedtke@gmail.com`, then create `secrets.json`:

```json
{ "addy_api_key": "YOUR_KEY", "addy_domain": "anonaddy.me" }
```

Most powerful alternative if Alex points a domain here: **Cloudflare Email Routing**
(free) catch-all `*@yourdomain.com` → Gmail. Then any `whatever@yourdomain.com` just
works and looks fully legitimate.

## Privacy (gitignored)

`aliases.json` (the alias→service→identity map) and `secrets.json` (API key) are
**gitignored** — they're personal data + a credential. Only `alias.py` + this README
are tracked. The registry rebuilds itself as you mint; there's nothing to restore
beyond re-minting (or re-export from addy.io if used).
