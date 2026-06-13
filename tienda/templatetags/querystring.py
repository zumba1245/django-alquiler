from __future__ import annotations

from django import template

register = template.Library()


@register.simple_tag
def querystring(request, **kwargs) -> str:
    """
    Construye querystring preservando los parámetros actuales y reemplazando
    solo los indicados en kwargs.
    """
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


@register.filter
def pretty_field_label(value) -> str:
    if value is None:
        return ""
    return str(value).replace("__", " / ").replace("_", " ").title()
