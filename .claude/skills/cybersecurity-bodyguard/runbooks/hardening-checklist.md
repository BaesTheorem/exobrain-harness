# Hardening Checklist

Proactive measures to reduce attack surface *before* an incident. Most of these are one-time setups; a few need quarterly review.

## Tier 1: Do today (2 hours total)

### Identity foundation
- [ ] Password manager installed (1Password, Bitwarden) with a long passphrase + 2FA
- [ ] Import all existing credentials; run the password manager's "weak / reused / breached" audit
- [ ] 2FA enabled on: email, password manager, Apple ID, Google, GitHub, financial accounts
- [ ] 2FA uses authenticator app (1Password, Authy, Google Authenticator), NOT SMS
- [ ] Port-out PIN set on phone carrier (prevents SIM swap) — call your carrier, ask for the SIM lock / number transfer PIN
- [ ] Recovery codes for every account saved in password manager (not in email)
- [ ] Primary email uses app-specific passwords where supported (Apple Mail, Fastmail, Proton)

### Account hygiene
- [ ] One "public" email for accounts that might leak (newsletters, shopping, forums)
- [ ] One "private" email for banking, legal, doctor, taxes — never posted anywhere
- [ ] Email aliases: use SimpleLogin, Apple Hide My Email, or Proton aliases for low-trust signups
- [ ] HIBP monitoring: subscribe each email at https://haveibeenpwned.com/NotifyMe
- [ ] Google account: https://myaccount.google.com/security-checkup — walk through every recommendation
- [ ] Apple ID: https://appleid.apple.com/ → Security → enable advanced data protection (end-to-end for iCloud)
- [ ] Review OAuth / connected apps for every platform; revoke anything unused in the past 6 months

### Location / schedule leaks
- [ ] Strava: privacy zones around home, work, and any regular stops
- [ ] Google Maps: delete location history older than 3 months (Auto-delete: 3 months)
- [ ] Instagram / Facebook / Twitter: no location tagging; scrub historical location tags
- [ ] Home Wi-Fi SSID doesn't include your name or address
- [ ] Venmo / CashApp: all transactions private
- [ ] LinkedIn: remove specific neighborhood / gym / meetup info

## Tier 2: Do this week (4 hours total)

### Data broker sweep
- [ ] Run the full opt-out sequence in `data-broker-removal.md` (~2 hours)
- [ ] Subscribe to DeleteMe or Optery for ongoing broker monitoring (~$100/yr)
- [ ] Add broker sweep to quarterly calendar

### Credential reduction
- [ ] Delete accounts you haven't used in a year — https://justdelete.me/ has links for each major site
- [ ] For sites you can't delete: change email to an alias, scrub profile, change name to "deleted user" variants
- [ ] Cancel financial accounts you don't use (each is an attack surface + breach risk)

### Phone / identity layer
- [ ] Get a Google Voice number or Cloaked number for public-facing use (forum signups, Craigslist, contractor intake forms)
- [ ] Never share your primary number outside family + essential services
- [ ] Credit freeze at all 3 bureaus: Equifax, Experian, TransUnion. Free, takes 10 minutes each.
  - Equifax: https://www.equifax.com/personal/credit-report-services/credit-freeze/
  - Experian: https://www.experian.com/freeze/center.html
  - TransUnion: https://www.transunion.com/credit-freeze
  - Unfreeze temporarily when applying for credit
- [ ] IRS IP PIN enrolled: https://www.irs.gov/identity-theft-fraud-scams/get-an-identity-protection-pin (prevents tax return fraud)

## Tier 3: Do this quarter

### Physical layer
- [ ] PO Box or mail forwarding service for shipping address — keeps home address off shipping labels, online orders, return labels
- [ ] Consider a registered agent service if you own a business — hides your home from LLC public filings
- [ ] If you own property, check if your county records allow address suppression for harassed individuals (many do — called "address confidentiality programs")
- [ ] Home security: smart lock, Ring / comparable camera, motion lights
- [ ] Vary routine: commute routes, gym times, grocery days

### Digital layer
- [ ] VPN for public Wi-Fi (Mullvad, ProtonVPN, IVPN — avoid logging services)
- [ ] Browser hardening: Firefox / Brave / Safari with tracker blocking on by default
- [ ] Separate browser profile for "banking + medical" vs "general browsing"
- [ ] Social media: quarterly audit of friends/followers, remove dormant + unknown accounts
- [ ] GitHub: ensure no `.env` files ever committed; scan history with gitleaks
- [ ] Review Google Photos / iCloud Photos for location metadata leaks

### Family layer
- [ ] Partner goes through this same checklist (attackers pivot through partners constantly)
- [ ] Kids / parents in household briefed on social engineering patterns (runbook: `social-engineering-detection.md#family--partner-training`)
- [ ] Shared family password manager for joint accounts
- [ ] Emergency contact tree — who calls whom in what order if something happens

## Tier 4: Sustain (monthly / quarterly)

### Monthly (15 min)
- [ ] HIBP check — any new breaches?
- [ ] Password manager: any new weak / reused credentials?
- [ ] Skim the Security Log.md in vault — any unresolved threads?

### Quarterly (1-2 hours)
- [ ] Full bodyguard passive scan (Mode 1 of the skill)
- [ ] Re-submit to any data broker you've been re-listed on
- [ ] Review OAuth / connected apps
- [ ] Review social media privacy settings (they change often, usually in the platform's favor)
- [ ] Review password manager's security score

### Annually
- [ ] Re-read this checklist — new threats, new tools
- [ ] Renew DeleteMe / Optery if using
- [ ] Audit: which new accounts from the past year are attack surface?
- [ ] Partner/family layer refresh

## Scoring

After Tier 1: basic hygiene. Blocks 80% of opportunistic attackers.
After Tier 2: serious hardening. Blocks most targeted attackers who aren't willing to invest heavily.
After Tier 3: high hardening. Reserved for people with a specific threat. Overkill otherwise.
After Tier 4: sustained. The point is not the initial setup, it's the maintenance.

No hardening is perfect. The goal is: make yourself a less-efficient target than the next person. Most attackers move on to easier targets.
