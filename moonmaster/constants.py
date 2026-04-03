# ---------------------------------------------------------------------------
# Metenox passive-harvest constants
# ---------------------------------------------------------------------------

# Volume of moon material harvested per hour by a Metenox (m³)
METENOX_HOURLY_HARVEST_VOLUME = 30_000

# Reprocessing yield applied to Metenox-harvested ore (base, no skills)
METENOX_HARVEST_REPROCESS_YIELD = 0.40

# Fuel blocks consumed per hour
METENOX_FUEL_BLOCKS_PER_HOUR = 5

# Magmatic gas units consumed per hour
METENOX_MAGMATIC_GASES_PER_HOUR = 110

# Moon material bay capacity (m³)
METENOX_MOON_MATERIAL_BAY_CAPACITY = 500_000

# Hours until the moon material bay is full at peak harvest rate
METENOX_HOURS_UNTIL_BAY_FULL = METENOX_MOON_MATERIAL_BAY_CAPACITY // METENOX_HOURLY_HARVEST_VOLUME

# ---------------------------------------------------------------------------
# Athanor / player-mining constants
# ---------------------------------------------------------------------------

# Default reprocessing yield for Athanor (rigs + typical skills + implants)
ATHANOR_REPROCESSING_YIELD_DEFAULT = 0.852

# Approximate ore volume made available per day by a standard drill cycle (m³)
MOONMINING_VOLUME_PER_DAY = 960_400

# Average days per month used for monthly profit projections
MOONMINING_DAYS_PER_MONTH = 30.4

# ---------------------------------------------------------------------------
# Pricing source choices
# ---------------------------------------------------------------------------

PRICE_SOURCE_ESI = "esi"
PRICE_SOURCE_FUZZWORK = "fuzzwork"

PRICE_SOURCE_CHOICES = [
    (PRICE_SOURCE_ESI, "ESI Average Price"),
    (PRICE_SOURCE_FUZZWORK, "Fuzzwork Buy/Sell"),
]

# ---------------------------------------------------------------------------
# Structure type choices
# ---------------------------------------------------------------------------

STRUCTURE_TYPE_ATHANOR = "athanor"
STRUCTURE_TYPE_METENOX = "metenox"

STRUCTURE_TYPE_CHOICES = [
    (STRUCTURE_TYPE_ATHANOR, "Athanor (Drill Extraction)"),
    (STRUCTURE_TYPE_METENOX, "Metenox (Passive Harvest)"),
]

# ---------------------------------------------------------------------------
# Moon rarity classes (matches CCP moon scan output)
# ---------------------------------------------------------------------------

RARITY_UBIQUITOUS = "ubiquitous"
RARITY_COMMON = "common"
RARITY_UNCOMMON = "uncommon"
RARITY_RARE = "rare"
RARITY_EXCEPTIONAL = "exceptional"

RARITY_CHOICES = [
    (RARITY_UBIQUITOUS, "Ubiquitous"),
    (RARITY_COMMON, "Common"),
    (RARITY_UNCOMMON, "Uncommon"),
    (RARITY_RARE, "Rare"),
    (RARITY_EXCEPTIONAL, "Exceptional"),
]

# ---------------------------------------------------------------------------
# ESI type IDs for fuel / gas used by Metenox
# ---------------------------------------------------------------------------

# Nitrogen Fuel Block (most common; others share the same rate)
ESI_TYPE_ID_NITROGEN_FUEL_BLOCK = 4051
ESI_TYPE_ID_HYDROGEN_FUEL_BLOCK = 4246
ESI_TYPE_ID_HELIUM_FUEL_BLOCK   = 4247
ESI_TYPE_ID_OXYGEN_FUEL_BLOCK   = 4312

# Magmatic Gas (used exclusively by Metenox)
ESI_TYPE_ID_MAGMATIC_GAS = 81143

FUEL_BLOCK_TYPE_IDS = [
    ESI_TYPE_ID_NITROGEN_FUEL_BLOCK,
    ESI_TYPE_ID_HYDROGEN_FUEL_BLOCK,
    ESI_TYPE_ID_HELIUM_FUEL_BLOCK,
    ESI_TYPE_ID_OXYGEN_FUEL_BLOCK,
]
