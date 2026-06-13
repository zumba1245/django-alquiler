from __future__ import annotations

from django.urls import NoReverseMatch, reverse


def _safe_reverse(name: str, **kwargs):
    try:
        return reverse(name, kwargs=kwargs if kwargs else None)
    except NoReverseMatch:
        return None


def breadcrumbs(request):
    match = getattr(request, "resolver_match", None)
    if not match:
        return {"breadcrumbs": []}

    view_name = match.view_name or ""
    if not view_name.startswith("tienda:"):
        return {"breadcrumbs": []}

    url_name = view_name.split(":", 1)[1]
    pk = match.kwargs.get("pk")
    crumbs = [{"label": "Inicio", "url": _safe_reverse("tienda:index")}]

    if url_name == "index":
        return {"breadcrumbs": crumbs}
    if url_name == "papelera_list":
        crumbs.append({"label": "Papelera", "url": None})
        return {"breadcrumbs": crumbs}
    if url_name == "auditoria_list":
        crumbs.append({"label": "Auditoría", "url": None})
        return {"breadcrumbs": crumbs}

    resource_map = {
        "categoria": ("Categorías", "tienda:categoria_list"),
        "cliente": ("Clientes", "tienda:cliente_list"),
        "pelicula": ("Películas", "tienda:pelicula_list"),
        "metodo_pago": ("Métodos de pago", "tienda:metodo_pago_list"),
        "alquiler": ("Alquileres", "tienda:alquiler_list"),
        "ventas": ("Ventas", "tienda:ventas_list"),
    }

    for prefix, (label, list_url_name) in resource_map.items():
        if url_name.startswith(prefix):
            if url_name.endswith("_list"):
                crumbs.append({"label": label, "url": None})
                return {"breadcrumbs": crumbs}

            crumbs.append({"label": label, "url": _safe_reverse(list_url_name)})

            if url_name.endswith("_create"):
                crumbs.append({"label": "Crear", "url": None})
            elif url_name.endswith("_detail"):
                crumbs.append({"label": f"Detalle #{pk}", "url": None})
            elif url_name.endswith("_update"):
                crumbs.append({"label": f"Editar #{pk}", "url": None})
            elif url_name.endswith("_delete"):
                crumbs.append({"label": f"Eliminar #{pk}", "url": None})
            elif url_name.endswith("_restore"):
                crumbs = [{"label": "Inicio", "url": _safe_reverse("tienda:index")}]
                crumbs.append({"label": "Papelera", "url": _safe_reverse("tienda:papelera_list")})
                crumbs.append({"label": f"Restaurar #{pk}", "url": None})
            elif url_name == "cliente_import_csv":
                crumbs.append({"label": "Importar CSV", "url": None})
            elif url_name == "pelicula_actualizar_precios_lote":
                crumbs.append({"label": "Actualizar precios en lote", "url": None})
            elif url_name == "alquiler_marcar_pagado":
                crumbs.append({"label": f"Marcar pagado #{pk}", "url": None})
            elif url_name == "alquiler_anular":
                crumbs.append({"label": f"Anular #{pk}", "url": None})
            elif url_name == "ventas_simular":
                crumbs.append({"label": "Simular ventas", "url": None})
            elif url_name == "ventas_cerrar_caja":
                crumbs.append({"label": "Cerrar caja diaria", "url": None})
            return {"breadcrumbs": crumbs}

    return {"breadcrumbs": crumbs}
