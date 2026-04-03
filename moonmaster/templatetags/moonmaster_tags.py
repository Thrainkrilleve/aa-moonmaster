import re

from django import template

register = template.Library()


@register.filter(name="intcomma")
def intcomma(value):
    """Format a number with thousands-separator commas, e.g. 1234567 → 1,234,567."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return value
    return f"{value:,}"


@register.filter(name="structure_system")
def structure_system(structure):
    """Return system name for a Structure — from linked moon, or parsed from structure name."""
    if structure.moon:
        return structure.moon.solar_system_name
    if structure.name:
        m = re.match(r'^(.+?)\s*-\s*(?:[IVXivx]+|\d+)[\.-]\d+', structure.name)
        if m:
            return m.group(1).strip()
    return "—"
