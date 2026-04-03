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


@register.filter(name="fuel_urgency_class")
def fuel_urgency_class(fuel_expires):
    """
    Return a Bootstrap colour class (success/warning/danger/secondary)
    based on how much time remains until the fuel_expires datetime.
    """
    if not fuel_expires:
        return "secondary"
    from django.utils import timezone
    hours = (fuel_expires - timezone.now()).total_seconds() / 3600
    if hours < 0:
        return "danger"
    if hours < 48:
        return "danger"
    if hours < 168:  # 7 days
        return "warning"
    return "success"


@register.filter(name="time_until_short")
def time_until_short(future_dt):
    """
    Return a compact countdown string: '14h', '3d', 'Expired'.
    Used for fuel expiry display.
    """
    if not future_dt:
        return "—"
    from django.utils import timezone
    total_seconds = (future_dt - timezone.now()).total_seconds()
    if total_seconds <= 0:
        return "Expired"
    hours = int(total_seconds // 3600)
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"
