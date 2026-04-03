"""
Profitability calculator for Moon Master.

Usage
-----
    calc = MoonProfitCalculator(moon, tax_config)
    result = calc.comparison_table()

All ISK values are Decimal, all per-month projections use MOONMINING_DAYS_PER_MONTH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional

from .constants import (
    ATHANOR_FUEL_BLOCKS_PER_HOUR_DEFAULT,
    ATHANOR_REPROCESSING_YIELD_DEFAULT,
    METENOX_FUEL_BLOCKS_PER_HOUR,
    METENOX_HARVEST_REPROCESS_YIELD,
    METENOX_HOURLY_HARVEST_VOLUME,
    METENOX_MAGMATIC_GASES_PER_HOUR,
    MOONMINING_DAYS_PER_MONTH,
    MOONMINING_VOLUME_PER_DAY,
    ESI_TYPE_ID_NITROGEN_FUEL_BLOCK,
    ESI_TYPE_ID_MAGMATIC_GAS,
    MOON_ORE_VOLUME_M3,
    MOON_ORE_VOLUME_DEFAULT_M3,
)
from .pricing import get_prices

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_HOURS_PER_DAY = Decimal("24")
_DAYS_PER_MONTH = Decimal(str(MOONMINING_DAYS_PER_MONTH))


def _ore_gross_value(
    ore_composition: Dict[str, float],
    total_volume_m3: Decimal,
    prices: Dict[int, Decimal],
    reprocess_yield: float = 1.0,
) -> Decimal:
    """
    Calculate the gross ISK value of ore from a given composition.

    :param ore_composition: {type_id_str: fraction} (fractions sum to 1.0)
    :param total_volume_m3: Total ore volume in m³
    :param prices: {type_id: price_per_UNIT} from ESI/Fuzzwork
    :param reprocess_yield: Multiplier applied to price (1.0 = sell raw, <1 = after reprocessing loss)

    ESI prices are ISK/unit.  We divide by the ore's packaged volume (m³/unit)
    to get ISK/m³, then multiply by the m³ of that ore in the chunk.
    """
    total = _ZERO
    for type_id_str, fraction in ore_composition.items():
        type_id = int(type_id_str)
        ore_volume_m3 = Decimal(str(
            MOON_ORE_VOLUME_M3.get(type_id, MOON_ORE_VOLUME_DEFAULT_M3)
        ))
        price_per_unit = prices.get(type_id, _ZERO)
        if ore_volume_m3 == _ZERO:
            continue
        price_per_m3 = price_per_unit / ore_volume_m3
        volume = total_volume_m3 * Decimal(str(fraction))
        total += volume * price_per_m3 * Decimal(str(reprocess_yield))
    return total


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class DrillResult:
    """Results for Athanor drill-cycle player mining."""

    gross_isk_per_month: Decimal = _ZERO
    # Breakdown of deductions
    fuel_cost_per_month: Decimal = _ZERO
    alliance_tax_isk: Decimal = _ZERO
    corp_tax_isk: Decimal = _ZERO
    reprocess_tax_isk: Decimal = _ZERO
    sov_upkeep_isk: Decimal = _ZERO
    net_isk_per_month: Decimal = _ZERO
    # Corp's share when running a fleet (fleet_share_pct of gross before taxes)
    corp_fleet_share_isk: Decimal = _ZERO


@dataclass
class MetenoxResult:
    """Results for Metenox passive harvest."""

    gross_isk_per_month: Decimal = _ZERO
    fuel_cost_per_month: Decimal = _ZERO
    gas_cost_per_month: Decimal = _ZERO
    alliance_tax_isk: Decimal = _ZERO
    corp_tax_isk: Decimal = _ZERO
    reprocess_tax_isk: Decimal = _ZERO
    sov_upkeep_isk: Decimal = _ZERO
    net_isk_per_month: Decimal = _ZERO


@dataclass
class ComparisonTable:
    drill: Optional[DrillResult] = None
    metenox: Optional[MetenoxResult] = None
    price_source: str = ""
    moon_name: str = ""


# ---------------------------------------------------------------------------
# Calculator class
# ---------------------------------------------------------------------------

class MoonProfitCalculator:
    """
    Calculate monthly profitability for a moon under different scenarios.

    :param moon: ``Moon`` model instance.
    :param tax_config: ``TaxConfig`` model instance (or None for zero taxes).
    :param reprocess_yield: Athanor reprocessing yield (default 85.2%).
    :param price_source: ``"esi"`` or ``"fuzzwork"`` — used only for labelling;
                         prices are pulled from the ``OrePrice`` cache table.
    :param fleet_share_pct: Fraction of gross mined value the corp retains when
                            running a fleet op (e.g. 0.10 = 10%).
    """

    def __init__(
        self,
        moon,
        tax_config=None,
        reprocess_yield: float = ATHANOR_REPROCESSING_YIELD_DEFAULT,
        price_source: str = "esi",
        fleet_share_pct: float = 0.0,
        athanor_fuel_blocks_per_hour: float = ATHANOR_FUEL_BLOCKS_PER_HOUR_DEFAULT,
    ):
        self.moon = moon
        self.tax_config = tax_config
        self.reprocess_yield = Decimal(str(reprocess_yield))
        self.price_source = price_source
        self.fleet_share_pct = Decimal(str(fleet_share_pct))
        self._athanor_fuel_blocks_per_hour = Decimal(str(athanor_fuel_blocks_per_hour))

        # Tax rates as Decimal fractions
        if tax_config:
            self._alliance_tax = Decimal(str(tax_config.alliance_tax))
            self._corp_tax = Decimal(str(tax_config.corp_tax))
            self._reprocess_tax = Decimal(str(tax_config.reprocess_tax))
            self._sov_upkeep_monthly = Decimal(str(tax_config.sov_upkeep_daily_isk)) * _DAYS_PER_MONTH
        else:
            self._alliance_tax = _ZERO
            self._corp_tax = _ZERO
            self._reprocess_tax = _ZERO
            self._sov_upkeep_monthly = _ZERO

        # Collect all needed type_ids (ores + fuel types)
        ore_ids = [int(k) for k in moon.ore_composition.keys()]
        fuel_ids = [ESI_TYPE_ID_NITROGEN_FUEL_BLOCK, ESI_TYPE_ID_MAGMATIC_GAS]
        self._prices = get_prices(ore_ids + fuel_ids)

    # ------------------------------------------------------------------
    # Public scenario methods
    # ------------------------------------------------------------------

    def drill_profit_per_month(self) -> DrillResult:
        """
        Athanor drill extraction, all ore mined by players (or sold as raw).

        Gross value = full ore volume per month × raw ore price.
        Fuel cost = fuel blocks/hr (from fitted service modules) × hours/month × price.
        """
        total_volume = Decimal(str(MOONMINING_VOLUME_PER_DAY)) * _DAYS_PER_MONTH

        gross = _ore_gross_value(
            self.moon.ore_composition,
            total_volume,
            self._prices,
            reprocess_yield=float(self.reprocess_yield),
        )

        hours_per_month = _HOURS_PER_DAY * _DAYS_PER_MONTH
        fuel_price = self._prices.get(ESI_TYPE_ID_NITROGEN_FUEL_BLOCK, _ZERO)
        fuel_cost = self._athanor_fuel_blocks_per_hour * hours_per_month * fuel_price

        alliance_tax = gross * self._alliance_tax
        corp_tax = gross * self._corp_tax
        reprocess_tax = gross * self._reprocess_tax
        sov = self._sov_upkeep_monthly
        corp_fleet_share = gross * self.fleet_share_pct

        net = gross - fuel_cost - alliance_tax - corp_tax - reprocess_tax - sov

        return DrillResult(
            gross_isk_per_month=gross,
            fuel_cost_per_month=fuel_cost,
            alliance_tax_isk=alliance_tax,
            corp_tax_isk=corp_tax,
            reprocess_tax_isk=reprocess_tax,
            sov_upkeep_isk=sov,
            net_isk_per_month=net,
            corp_fleet_share_isk=corp_fleet_share,
        )

    def metenox_profit_per_month(self) -> MetenoxResult:
        """
        Metenox passive harvest.

        Gross value = 30,000 m³/hr × 40% reprocess yield × price,
        averaged over the ore composition.
        Costs = fuel blocks + magmatic gas at current market prices.
        """
        hours_per_month = _HOURS_PER_DAY * _DAYS_PER_MONTH
        harvest_volume_per_month = Decimal(str(METENOX_HOURLY_HARVEST_VOLUME)) * hours_per_month

        gross = _ore_gross_value(
            self.moon.ore_composition,
            harvest_volume_per_month,
            self._prices,
            reprocess_yield=METENOX_HARVEST_REPROCESS_YIELD,
        )

        # Fuel costs
        fuel_blocks_per_month = Decimal(str(METENOX_FUEL_BLOCKS_PER_HOUR)) * hours_per_month
        gas_per_month = Decimal(str(METENOX_MAGMATIC_GASES_PER_HOUR)) * hours_per_month

        fuel_price = self._prices.get(ESI_TYPE_ID_NITROGEN_FUEL_BLOCK, _ZERO)
        gas_price = self._prices.get(ESI_TYPE_ID_MAGMATIC_GAS, _ZERO)

        fuel_cost = fuel_blocks_per_month * fuel_price
        gas_cost = gas_per_month * gas_price

        alliance_tax = gross * self._alliance_tax
        corp_tax = gross * self._corp_tax
        reprocess_tax = gross * self._reprocess_tax
        sov = self._sov_upkeep_monthly

        net = gross - fuel_cost - gas_cost - alliance_tax - corp_tax - reprocess_tax - sov

        return MetenoxResult(
            gross_isk_per_month=gross,
            fuel_cost_per_month=fuel_cost,
            gas_cost_per_month=gas_cost,
            alliance_tax_isk=alliance_tax,
            corp_tax_isk=corp_tax,
            reprocess_tax_isk=reprocess_tax,
            sov_upkeep_isk=sov,
            net_isk_per_month=net,
        )

    def comparison_table(self) -> ComparisonTable:
        """Return a ComparisonTable with both scenarios filled in."""
        return ComparisonTable(
            drill=self.drill_profit_per_month(),
            metenox=self.metenox_profit_per_month(),
            price_source=self.price_source,
            moon_name=str(self.moon),
        )

    # ------------------------------------------------------------------
    # Serialisation helper (for JSON API views)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        table = self.comparison_table()

        def _dec(val: Decimal) -> str:
            return f"{val:,.2f}" if val is not None else "0.00"

        return {
            "moon": table.moon_name,
            "price_source": table.price_source,
            "drill": {
                "gross_isk_per_month": _dec(table.drill.gross_isk_per_month),
                "fuel_cost_per_month": _dec(table.drill.fuel_cost_per_month),
                "alliance_tax_isk": _dec(table.drill.alliance_tax_isk),
                "corp_tax_isk": _dec(table.drill.corp_tax_isk),
                "reprocess_tax_isk": _dec(table.drill.reprocess_tax_isk),
                "sov_upkeep_isk": _dec(table.drill.sov_upkeep_isk),
                "net_isk_per_month": _dec(table.drill.net_isk_per_month),
                "corp_fleet_share_isk": _dec(table.drill.corp_fleet_share_isk),
            } if table.drill else None,
            "metenox": {
                "gross_isk_per_month": _dec(table.metenox.gross_isk_per_month),
                "fuel_cost_per_month": _dec(table.metenox.fuel_cost_per_month),
                "gas_cost_per_month": _dec(table.metenox.gas_cost_per_month),
                "alliance_tax_isk": _dec(table.metenox.alliance_tax_isk),
                "corp_tax_isk": _dec(table.metenox.corp_tax_isk),
                "reprocess_tax_isk": _dec(table.metenox.reprocess_tax_isk),
                "sov_upkeep_isk": _dec(table.metenox.sov_upkeep_isk),
                "net_isk_per_month": _dec(table.metenox.net_isk_per_month),
            } if table.metenox else None,
        }
