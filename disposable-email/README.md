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

## Backends (schemes)

| Scheme | Address shape | Disposability | Setup |
|---|---|---|---|
| `gmail-plus` (default) | `alex.hedtke+<service>@gmail.com` | low (strip `+tag` → real addr) | none — works now |
| `gmail-dot` | dotted username variant | low; for forms that reject `+` | none |
| `addy` | `random@anonaddy.me` (addy.io) | **high** — kill any alias, real-looking | needs `secrets.json` |

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
