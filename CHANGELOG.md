# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
