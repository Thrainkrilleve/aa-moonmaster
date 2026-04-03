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
    (RARITY_UBIQUITOUS, "R4 — Ubiquitous"),
    (RARITY_COMMON,     "R8 — Common"),
    (RARITY_UNCOMMON,   "R16 — Uncommon"),
    (RARITY_RARE,       "R32 — Rare"),
    (RARITY_EXCEPTIONAL,"R64 — Exceptional"),
]

# Human-readable R-tier label for each rarity class
RARITY_TIER_LABEL: dict = {
    RARITY_UBIQUITOUS:  "R4",
    RARITY_COMMON:      "R8",
    RARITY_UNCOMMON:    "R16",
    RARITY_RARE:        "R32",
    RARITY_EXCEPTIONAL: "R64",
}

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

# ---------------------------------------------------------------------------
# Structure service module fuel consumption
# Source: EVE SDE dogmaAttribute 2109 (serviceModuleFuelAmount)
# Maps the ESI structure service name string → fuel blocks per hour
# ---------------------------------------------------------------------------
ATHANOR_FUEL_BLOCKS_PER_HOUR_DEFAULT = 5  # Standup Moon Drill I baseline

SERVICE_MODULE_FUEL_PER_HOUR: dict = {
    # Moon-mining services
    "moon_drilling":          5,   # Standup Moon Drill I (type 45009)
    "metenox_moon_drill":     5,   # Standup Metenox Moon Drill (type 82941)
    # Manufacturing / science
    "manufacturing":         12,   # Standup Manufacturing Plant I (type 35878)
    "invention":             12,   # Standup Invention Lab I (type 35886)
    "laboratory":            12,   # Standup Research Lab I (type 35891)
    # Reactions
    "composite_reactions":   15,   # Standup Composite Reactor I (type 45537)
    "hybrid_reactions":      15,   # Standup Hybrid Reactor I (type 45538)
    "biochemical_reactions": 15,   # Standup Biochemical Reactor I (type 45539)
    # Refining / compression
    "reprocessing":          10,   # Standup Reprocessing Facility I (type 35899)
    "compression":            5,   # Structure Compression Plant (type 35900)
    # Other services
    "cloning":               10,   # Standup Cloning Center I (type 35894)
    "market":                40,   # Standup Market Hub I (type 35892)
}

# ---------------------------------------------------------------------------
# Moon ore packaged volume (m³/unit) — used to convert ESI ISK/unit → ISK/m³
# Source: EVE SDE / in-game show info.  All standard moon ores are 0.1 m³/unit.
# ---------------------------------------------------------------------------
MOON_ORE_VOLUME_M3: dict = {
    # R4 Ubiquitous
    45490: 0.1,  # Zeolites
    45491: 0.1,  # Sylvite
    45492: 0.1,  # Bitumens
    45493: 0.1,  # Coesite
    # R8 Common
    45494: 0.1,  # Cobaltite
    45495: 0.1,  # Euxenite
    45496: 0.1,  # Titanite
    45497: 0.1,  # Scheelite
    # R16 Uncommon
    45498: 0.1,  # Otavite
    45499: 0.1,  # Sperrylite
    45500: 0.1,  # Vanadinite
    45501: 0.1,  # Chromite
    # R32 Rare
    45502: 0.1,  # Carnotite
    45503: 0.1,  # Zircon
    45504: 0.1,  # Loparite
    45505: 0.1,  # Monazite
    # R64 Exceptional
    45506: 0.1,  # Xenotime
    45507: 0.1,  # Ytterbite
    45508: 0.1,  # Pollucite
    45509: 0.1,  # Cinnabar
}
# Default volume for any ore type not listed above
MOON_ORE_VOLUME_DEFAULT_M3 = 0.1

# ---------------------------------------------------------------------------
# Moon ore type_id → human-readable name
# ---------------------------------------------------------------------------
MOON_ORE_NAMES: dict = {
    # R4 Ubiquitous
    45490: "Zeolites",
    45491: "Sylvite",
    45492: "Bitumens",
    45493: "Coesite",
    # R8 Common
    45494: "Cobaltite",
    45495: "Euxenite",
    45496: "Titanite",
    45497: "Scheelite",
    # R16 Uncommon
    45498: "Otavite",
    45499: "Sperrylite",
    45500: "Vanadinite",
    45501: "Chromite",
    # R32 Rare
    45502: "Carnotite",
    45503: "Zircon",
    45504: "Loparite",
    45505: "Monazite",
    # R64 Exceptional
    45506: "Xenotime",
    45507: "Ytterbite",
    45508: "Pollucite",
    45509: "Cinnabar",
}

# ---------------------------------------------------------------------------
# Moon ore type_id → rarity class (for survey import auto-classification)
# ---------------------------------------------------------------------------
MOON_ORE_RARITY: dict = {
    # R4 Ubiquitous
    45490: RARITY_UBIQUITOUS,  # Zeolites
    45491: RARITY_UBIQUITOUS,  # Sylvite
    45492: RARITY_UBIQUITOUS,  # Bitumens
    45493: RARITY_UBIQUITOUS,  # Coesite
    # R8 Common
    45494: RARITY_COMMON,  # Cobaltite
    45495: RARITY_COMMON,  # Euxenite
    45496: RARITY_COMMON,  # Titanite
    45497: RARITY_COMMON,  # Scheelite
    # R16 Uncommon
    45498: RARITY_UNCOMMON,  # Otavite
    45499: RARITY_UNCOMMON,  # Sperrylite
    45500: RARITY_UNCOMMON,  # Vanadinite
    45501: RARITY_UNCOMMON,  # Chromite
    # R32 Rare
    45502: RARITY_RARE,  # Carnotite
    45503: RARITY_RARE,  # Zircon
    45504: RARITY_RARE,  # Loparite
    45505: RARITY_RARE,  # Monazite
    # R64 Exceptional
    45506: RARITY_EXCEPTIONAL,  # Xenotime
    45507: RARITY_EXCEPTIONAL,  # Ytterbite
    45508: RARITY_EXCEPTIONAL,  # Pollucite
    45509: RARITY_EXCEPTIONAL,  # Cinnabar
}

# ---------------------------------------------------------------------------
# Structure state / reinforce constants
# ---------------------------------------------------------------------------

# States where the structure is actively being reinforced
REINFORCE_STATES = frozenset(["armor_reinforce", "hull_reinforce"])

# ESI state string → (display label, Bootstrap colour class)
STRUCTURE_STATE_LABELS: dict = {
    "shield_vulnerable":    ("Online",          "success"),
    "armor_vulnerable":     ("Online",          "success"),
    "hull_vulnerable":      ("Online",          "success"),
    "online_deprecated":    ("Online",          "success"),
    "onlining_vulnerable":  ("Coming Online",   "warning"),
    "armor_reinforce":      ("Armor Reinforce", "danger"),
    "hull_reinforce":       ("Hull Reinforce",  "danger"),
    "anchor_vulnerable":    ("Anchoring",       "warning"),
    "anchoring":            ("Anchoring",       "warning"),
    "deploy_vulnerable":    ("Deploying",       "warning"),
    "fitting_invulnerable": ("Fitting",         "info"),
    "unanchored":           ("Unanchored",      "secondary"),
    "offline":              ("Offline",         "secondary"),
    "unknown":              ("Unknown",         "secondary"),
}

# Human-readable names for ESI service module name strings
SERVICE_DISPLAY_NAMES: dict = {
    "moon_drilling":         "Moon Drill",
    "metenox_moon_drill":    "Metenox Drill",
    "manufacturing":         "Manufacturing",
    "invention":             "Invention",
    "laboratory":            "Research Lab",
    "composite_reactions":   "Composite Reactions",
    "hybrid_reactions":      "Hybrid Reactions",
    "biochemical_reactions": "Biochemical Reactions",
    "reprocessing":          "Reprocessing",
    "compression":           "Compression",
    "cloning":               "Cloning",
    "market":                "Market Hub",
}
