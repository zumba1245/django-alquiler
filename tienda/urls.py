from django.urls import path

from . import views

app_name = "tienda"

urlpatterns = [
    path("", views.DashboardTemplateView.as_view(), name="index"),
    path(
        "cuenta/cambiar-clave-inicial/",
        views.InitialPasswordChangeView.as_view(),
        name="initial_password_change",
    ),
    path("auditoria/", views.AuditListView.as_view(), name="auditoria_list"),
    path("trash/", views.PapeleraListView.as_view(), name="papelera_list"),
    path("categorias/<int:pk>/restore/", views.RestoreCategoriaView.as_view(), name="categoria_restore"),
    path("clientes/<int:pk>/restore/", views.RestoreClienteView.as_view(), name="cliente_restore"),
    path("peliculas/<int:pk>/restore/", views.RestorePeliculaView.as_view(), name="pelicula_restore"),
    path(
        "metodos-pago/<int:pk>/restore/",
        views.RestoreMetodoPagoView.as_view(),
        name="metodo_pago_restore",
    ),
    # Categorias
    path("categorias/", views.CategoriaListView.as_view(), name="categoria_list"),
    path("categorias/create/", views.CategoriaCreateView.as_view(), name="categoria_create"),
    path("categorias/<int:pk>/edit/", views.CategoriaUpdateView.as_view(), name="categoria_update"),
    path("categorias/<int:pk>/delete/", views.CategoriaDeleteView.as_view(), name="categoria_delete"),
    # Metodos de pago
    path("metodos-pago/", views.MetodoPagoListView.as_view(), name="metodo_pago_list"),
    path("metodos-pago/create/", views.MetodoPagoCreateView.as_view(), name="metodo_pago_create"),
    path("metodos-pago/<int:pk>/edit/", views.MetodoPagoUpdateView.as_view(), name="metodo_pago_update"),
    path("metodos-pago/<int:pk>/delete/", views.MetodoPagoDeleteView.as_view(), name="metodo_pago_delete"),
    # Peliculas
    path("peliculas/", views.PeliculaListView.as_view(), name="pelicula_list"),
    path("peliculas/create/", views.PeliculaCreateView.as_view(), name="pelicula_create"),
    path("peliculas/<int:pk>/", views.PeliculaDetailView.as_view(), name="pelicula_detail"),
    path(
        "peliculas/bulk-update-prices/",
        views.PeliculaActualizarPreciosLoteView.as_view(),
        name="pelicula_actualizar_precios_lote",
    ),
    path("peliculas/<int:pk>/edit/", views.PeliculaUpdateView.as_view(), name="pelicula_update"),
    path("peliculas/<int:pk>/delete/", views.PeliculaDeleteView.as_view(), name="pelicula_delete"),
    # Clientes
    path("clientes/", views.ClienteListView.as_view(), name="cliente_list"),
    path("clientes/create/", views.ClienteCreateView.as_view(), name="cliente_create"),
    path("clientes/export-csv/", views.ClienteExportCSVView.as_view(), name="cliente_export_csv"),
    path("clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="cliente_detail"),
    path(
        "clientes/import-csv/",
        views.ClienteImportCSVView.as_view(),
        name="cliente_import_csv",
    ),
    path("clientes/<int:pk>/edit/", views.ClienteUpdateView.as_view(), name="cliente_update"),
    path("clientes/<int:pk>/delete/", views.ClienteDeleteView.as_view(), name="cliente_delete"),
    # Alquileres
    path("alquileres/", views.AlquilerListView.as_view(), name="alquiler_list"),
    path("alquileres/create/", views.AlquilerCreateView.as_view(), name="alquiler_create"),
    path(
        "alquileres/<int:pk>/mark-paid/",
        views.MarcarPagadoView.as_view(),
        name="alquiler_marcar_pagado",
    ),
    path(
        "alquileres/<int:pk>/cancel/",
        views.AnularAlquilerView.as_view(),
        name="alquiler_anular",
    ),
    # Ventas (en esta versión: alquileres pagados)
    path("ventas/", views.VentasListView.as_view(), name="ventas_list"),
    path("ventas/simulate/", views.SimularVentasFormView.as_view(), name="ventas_simular"),
    path("ventas/close-daily-cash/", views.CerrarCajaDiariaView.as_view(), name="ventas_cerrar_caja"),
]

