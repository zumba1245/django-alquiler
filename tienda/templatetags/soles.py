from __future__ import annotations

from decimal import Decimal

from django import template

register = template.Library()


@register.filter(name="soles")
def soles(value) -> str:
    """
    Formatea importes como `S/ 3,50` (coma decimal).
    """
    if value is None:
        return ""

    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        # Fallback: no rompemos la plantilla.
        return f"S/ {value}"

    importe = f"{d:.2f}".replace(".", ",")
    return f"S/ {importe}"

