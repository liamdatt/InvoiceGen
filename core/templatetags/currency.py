from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@register.filter(name="money")
def money(value):
    """Render a currency amount with commas and two decimal places."""
    number = _to_decimal(value)
    if number is None:
        return ""
    return f"${number:,.2f}"
