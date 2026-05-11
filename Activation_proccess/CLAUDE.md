# Activation_proccess

Python automation for Latitude.sh's bare metal server activation pipeline on Rundeck. Four jobs in the pipeline: **spreadsheet generator (new)** → NetBox onboarding → switch config → DHCP/IPMI. This repo owns the generator and onboarding refactor; switch config lives elsewhere; DHCP is deferred to a later milestone.

See `.planning/PROJECT.md` for full context, `.planning/ROADMAP.md` for phase structure, `.planning/REQUIREMENTS.md` for scope.

## Code style — hard rules

- **Procedural Python only.** if/else, simple loops, plain functions. Dataclasses where they clarify shape.
- **No frameworks, class hierarchies, plugin systems, decorators for clever tricks, metaclasses, dependency injection.** Three similar lines beats a premature abstraction.
- Keep modules small, one responsibility each.

## Environment

- **Runtime:** Rundeck. Inputs arrive via `RD_OPTION_*` / `RD_FILE_*` env vars. Secrets come from Rundeck's secret store.
- **NetBox:** sandbox only — `https://netbox.latitude.co`. Constants live in `Onboarding_Automation/netbox_onboarding/config.py`:
  - `ONBOARDING_TENANT_ID = 18458`
  - `SEGMENTATION_TAG_ID = 61`
  - `IP_TAG_IDS = {"ip_eth0": 24, "ipv6_eth0": 25, "ip_ipmi": 26}`
  - `VID_RANGE = [[3738, 3831]]`
- Never duplicate these IDs elsewhere. Import from `config.py`.

## Security

- Never log, print, or expose tokens or credentials (NetBox token, Google creds). All secrets are env-var only.
- SSL verification is **intentionally disabled** for the internal NetBox cert chain (`session.verify = False`). Do not re-enable without testing.
- Sub-project rules (honor when editing that code):
  - `Onboarding_Automation/.claude/rules/security.md`
  - `Onboarding_Automation/.claude/rules/testing.md`

## Existing code

- `Onboarding_Automation/netbox_onboarding/` — Python package. Entry points: `run_onboarding.py`, `run_activate.py`, `run_connections.py`. The canonical row shape the sheet must match is in `spreadsheet.py` (`ChassisInfo`, `DeviceInfo`, `SpreadsheetData`).
- `DHCP_Automation/` — out of scope for v1. Leave it alone.
- No switch configuration code lives here.

## Testing

- No automated test suite. Validation is manual against live sandbox NetBox and real switches.
- When touching NetBox lookup logic, verify against a known server label before committing.

## Current status

Phase 1 of 3 — Sheet Generator. Next step: `/gsd-plan-phase 1` (or `/gsd-discuss-phase 1` if you want to lock open decisions first — GSheets auth method and master template ID).
