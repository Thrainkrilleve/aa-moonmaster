# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.36] - 2026-04-13

### Fixed
- Janice price source now uses **sell price** (top-5% average) instead of buy
  price. Sell price reflects what players actually pay to purchase fuel blocks
  and magmatic gas off the market, giving accurate operating cost estimates.
  Previously buy prices understated Metenox monthly costs by ~35–80M ISK.

## [0.1.18] - 2026-04-03

### Fixed
- Moon auto-linking now works even when the `Moon` DB record doesn't exist yet.
  Name-parsing derives planet/moon numbers from the structure name, then uses
  public ESI (`/universe/systems/{id}/`) to resolve the correct `moon_id` and
  calls `get_or_create_moon()` — no auth scope required.
- Only Metenox/Athanor structures attempt auto-linking (skips irrelevant types).

### Added
- `find_moon_by_number(system_id, planet_num, moon_num)` helper in `providers.py`
  resolves a moon by its in-game numbered position using only public ESI.
- `python manage.py moonmaster_relink` management command to manually re-link
  any existing unlinked structures without waiting for a scheduled sync.

## [0.1.17] - 2026-04-03

### Added
- Unified **Structures** page (`/structures/`) replacing the old Metenox list,
  showing all Athanors and Metenoxes in one table with:
  - State badge (Online / Armor Reinforce / Hull Reinforce / Offline / etc.)
  - State timer countdown when a structure is in reinforce
  - Fuel countdown badge colour-coded by urgency (red <2 d, orange <7 d, green)
  - Service module badges (green = online, grey = offline) from ESI
  - Goo bay fill % progress bar (Metenox only)
  - Reinforce schedule (e.g. "Fri 14:00 UTC")
  - Client-side filter buttons: All / Athanor / Metenox / In Reinforce / Low Fuel
  - Row highlights: danger for reinforced, warning for <48 h fuel
- Dashboard alert banners for reinforced structures and critical fuel (<48 h).
- Dashboard "In Reinforce" count badge card (shown when count > 0).
- `fuel_urgency_class` and `time_until_short` template filters in `moonmaster_tags`.

### Changed
- `Structure` model gains six new ESI-backed fields: `state`, `state_timer_end`,
  `reinforce_hour`, `reinforce_weekday`, `services_raw`, `unanchors_at`
  (migration 0004).
- Structure sync (`_sync_owner_structures`) stores all new reinforce and services
  fields on every run.
- Navigation "Metenox" link replaced with "Structures".

## [0.1.16] - 2026-03-31

### Added
- `Structure.fuel_blocks_per_hour` field (migration 0003) stores the summed fuel
  consumption of all online service modules read from ESI.
- `SERVICE_MODULE_FUEL_PER_HOUR` map in `constants.py` covering 12 service types.
- Athanor fuel cost deducted from net profitability in the drill calculator
  (`DrillResult.fuel_cost_per_month`).
- Fuel Blocks cost row in the Athanor drill table on the moon detail page.

### Fixed
- `REQUIRED_SCOPES` now includes `esi-universe.read_structures.v1` and
  `esi-assets.read_corporation_assets.v1`, which are required for auto
  moon-linking and goo-bay sync respectively. Existing owners must re-authenticate
  to obtain the new scopes.
- `reports.html` now loads `moonmaster_tags` so ISK values format correctly with
  `intcomma`.

## [0.1.15] - 2026-03-28

### Added
- Custom `intcomma` and `structure_system` template filters shipped directly in
  `moonmaster_tags` — removes the `django.contrib.humanize` dependency.
- Structure type badges (Athanor / Metenox) in the moon list Structures column.

### Fixed
- Moon auto-linking extended to handle decimal planet notation in structure names
  (e.g. `N-8YET - 7-12` → `N-8YET VII - Moon 12`).
- "System" column on the Metenox list now parses the system name from the
  structure name when the moon is not yet linked.
- Moon detail and profitability views pass `price_source='fuzzwork'` so the badge
  displays `FUZZWORK` instead of `ESI`.
- All templates migrated from `humanize` to `moonmaster_tags` load tag.

## [0.1.14] - 2026-03-26

### Added
- Moon list now shows **Athanor Net/mo** and **Metenox Net/mo** columns, sortable
  and colour-coded green/red by profitability.
- Detail link column on Metenox list navigates to the moon detail page when linked.
- `intcomma` formatting on all ISK values throughout moon detail and reports.

### Fixed
- Switched price source from ESI adjusted price to **Fuzzwork Jita buy** price,
  fixing inflated profitability figures.
- Name-parse fallback in `_try_link_structure_to_moon` now handles Roman-numeral
  planet notation (e.g. `NOL-M9 - VIII.7` → `NOL-M9 VIII - Moon 7`).
- `update_tax_config` view no longer errors when tax form fields are submitted empty.

## [0.1.13] - 2026-03-24

### Fixed
- ESI 404 responses (e.g. no active extractions) are now treated as empty results
  rather than raising an error, preventing sync failures on new owners.

## [0.1.12] - 2026-03-24

### Fixed
- Added missing migration `0002` that was omitted from the v0.1.11 release.

## [0.1.11] - 2026-03-23

### Added
- Five Celery Beat schedules registered in `AppConfig.ready()`:
  `update_prices` (12 h), `update_all_structures` (30 min),
  `update_extractions` (10 min), `send_alerts` (10 min), `sync_mining_ledger` (1 h).
- `sync_mining_ledger` task: pulls ESI mining observer data and creates
  `MiningLedgerEntry` records linked to matching `Extraction` by date window.
- Extraction history table on the moon detail page (last 20 extractions)
  with status badges.
- `FIRED` / `CANCELLED` extraction status: extractions absent from ESI are now
  automatically marked `FIRED` (chunk arrival in the past) or `CANCELLED` (future).
- Goo bay fill % synced from ESI assets (`MoonMaterialBay` flag) when
  `esi-assets.read_corporation_assets.v1` scope is available.

### Fixed
- ISK/unit → ISK/m³ calculation corrected (all moon ores are 0.1 m³/unit;
  prices were previously inflated by 10×).
- Low-fuel dashboard filter now only shows structures expiring within 7 days.

## [0.1.10] - 2026-03-21

### Added
- Ore names and R-tier rarity labels displayed throughout the UI.

## [0.1.9] - 2026-03-20

### Fixed
- Guarded moon detail URL reversals against unlinked structures to prevent
  500 errors.

## [0.1.8] - 2026-03-19

### Fixed
- Moon survey import dispatched to a Celery task to avoid 504 gateway timeouts
  on large scan dumps.

## [0.1.7] - 2026-03-18

### Fixed
- Corrected EVE moon scan column indices in the survey parser.

## [0.1.6] - 2026-03-17

### Added
- Auto-discover structure moons via ESI position lookup.
- Full dashboard structure management view.

## [0.1.5] - 2026-03-16

### Fixed
- Patched `user_has_main_character` in `ready()` to allow superusers through.

## [0.1.4] - 2026-03-16

### Fixed
- Excluded all views from `main_character_required`; menu now visible to
  superusers without a linked main character.

## [0.1.3] - 2026-03-15

### Fixed
- Bust stale menu sync cache on startup so the app appears in the sidebar.

## [0.1.2] - 2026-03-15

### Fixed
- Import hooks in `AppConfig.ready()` so the menu item registers correctly.

## [0.1.1] - 2026-03-15

### Fixed
- Corrected `eveonline` migration dependency name.

## [0.1.0] - Initial Release

### Added
- Unified moon database (ore composition, rarity, solar system/region)
- Athanor drill extraction tracking with status management
- Metenox passive harvest tracking (fuel expiry, goo-bay fill %)
- Real-time pricing via ESI average price or Fuzzwork Jita buy price
- Profitability calculator:
  - Athanor drill mode with configurable fleet-share percentage
  - Metenox mode with fuel block + magmatic gas cost deduction
  - Tax engine: alliance tax, corp tax, structure reprocessing tax, sov upkeep
- Moon profitability reports ranked by net ISK/month
- Discord webhook alerts for low fuel, full goo bay, and imminent extraction
- Mining ledger per extraction cycle
- Django admin integration
- Initial migration
