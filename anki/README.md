# AZ-900 Anki Deck

Cloze-format deck covering the Microsoft AZ-900 (Azure Fundamentals) skills outline dated **January 14, 2026**. Source: https://learn.microsoft.com/en-us/credentials/certifications/resources/study-guides/az-900

## Import into Anki

1. Open Anki desktop
2. File → Import
3. Select `az-900-cloze.tsv`
4. Confirm note type is **Cloze** and deck is **AZ-900** (both declared in header)
5. Field mapping: `Text`, `Extra` (Back Extra / hint), `Tags`

## Coverage

- **Describe cloud concepts (25–30%)** — cloud definition, shared responsibility, public/private/hybrid, consumption/serverless, benefits, IaaS/PaaS/SaaS
- **Describe Azure architecture and services (35–40%)** — regions/AZs/datacenters, resource hierarchy, compute (VMs, scale sets, VMSS, AVD, Functions, ACI, AKS, App Service), networking (VNet, peering, DNS, VPN Gateway, ExpressRoute, endpoints), storage (blob/files/queue/table/disk, tiers, LRS/ZRS/GRS/GZRS, AzCopy, Storage Explorer, File Sync, Migrate, Data Box), identity & security (Entra ID, Entra Domain Services, SSO, MFA, passwordless, external identities, Conditional Access, RBAC, Zero Trust, defense-in-depth, Defender for Cloud)
- **Describe Azure management and governance (30–35%)** — cost (calculator, Cost Management, tags), governance (Purview, Policy, resource locks), tools (portal, Cloud Shell, CLI, PowerShell, Arc, IaC, ARM, templates), monitoring (Advisor, Service Health, Monitor, Log Analytics, alerts, Application Insights)

## Notes

- Generated 2026-04-21; verified against the Jan 14, 2026 skills outline
- If Microsoft refreshes the outline, diff against the Change Log section and regenerate affected cards
