from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from .models import (
    ActionAudit,
    Alquiler,
    CajaDiaria,
    Categoria,
    Cliente,
    EventoDominio,
    HistorialPrecioPelicula,
    LoginAttemptAudit,
    MetodoPago,
    Pelicula,
)


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "descripcion", "is_active"]
    search_fields = ["nombre"]
    list_filter = ["is_active"]
    ordering = ["nombre"]
    list_per_page = 30


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "dni", "email", "telefono", "total_gastado", "is_active"]
    search_fields = ["nombre", "dni", "email", "telefono"]
    list_filter = ["is_active"]
    ordering = ["nombre"]
    list_per_page = 30
    inlines = []

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            total_gastado_calc=Coalesce(
                Sum("alquileres__precio", filter=Q(alquileres__estado="pagado")),
                Value(0),
                output_field=DecimalField(max_digits=10, decimal_places=2),
            )
        )

    @admin.display(description="Total gastado", ordering="total_gastado_calc")
    def total_gastado(self, obj):
        return f"S/ {obj.total_gastado_calc:.2f}"


class AlquilerInline(admin.TabularInline):
    model = Alquiler
    extra = 0
    can_delete = False
    fields = (
        "fecha_alquiler",
        "pelicula",
        "estado",
        "pagado",
        "precio",
        "metodo_pago",
        "fecha_pago",
        "fecha_devolucion",
    )
    readonly_fields = fields
    autocomplete_fields = ("pelicula", "metodo_pago")
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


ClienteAdmin.inlines = [AlquilerInline]


class FechaAlquilerRangoFiltro(admin.SimpleListFilter):
    title = _("Fecha alquiler (rango)")
    parameter_name = "fecha_alquiler_rango"

    def lookups(self, request, model_admin):
        return [
            ("hoy", _("Hoy")),
            ("7d", _("Últimos 7 días")),
            ("30d", _("Últimos 30 días")),
            ("mes", _("Mes actual")),
        ]

    def queryset(self, request, queryset):
        from django.utils import timezone
        import datetime

        today = timezone.localdate()
        value = self.value()
        if value == "hoy":
            return queryset.filter(fecha_alquiler=today)
        if value == "7d":
            return queryset.filter(fecha_alquiler__gte=today - datetime.timedelta(days=7))
        if value == "30d":
            return queryset.filter(fecha_alquiler__gte=today - datetime.timedelta(days=30))
        if value == "mes":
            month_start = today.replace(day=1)
            return queryset.filter(fecha_alquiler__gte=month_start, fecha_alquiler__lte=today)
        return queryset


@admin.register(Pelicula)
class PeliculaAdmin(admin.ModelAdmin):
    list_display = [
        "titulo",
        "slug",
        "director",
        "pais_origen",
        "anio",
        "categoria",
        "precio_alquiler",
        "duracion_minutos",
        "stock",
        "is_active",
    ]
    list_filter = ["is_active", "categoria", "anio", "pais_origen"]
    search_fields = ["titulo", "slug", "director", "pais_origen", "categoria__nombre"]
    autocomplete_fields = ["categoria"]
    ordering = ["titulo", "anio"]
    list_per_page = 30


class AlquilerAdminForm(forms.ModelForm):
    class Meta:
        model = Alquiler
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        estado = cleaned_data.get("estado")
        pagado = cleaned_data.get("pagado")
        fecha_pago = cleaned_data.get("fecha_pago")
        metodo_pago = cleaned_data.get("metodo_pago")

        if estado == Alquiler.ESTADO_PAGADO and not pagado:
            self.add_error("pagado", "Si el estado es pagado, el campo pagado debe estar activo.")

        if estado in {Alquiler.ESTADO_PENDIENTE, Alquiler.ESTADO_ANULADO} and pagado:
            self.add_error("estado", "Estado pendiente/anulado no puede tener pagado activo.")

        if estado != Alquiler.ESTADO_PAGADO and fecha_pago:
            self.add_error("fecha_pago", "Solo debe existir fecha de pago cuando el estado sea pagado.")

        if estado != Alquiler.ESTADO_PAGADO and metodo_pago:
            self.add_error("metodo_pago", "Solo debe seleccionarse método de pago cuando el estado sea pagado.")

        return cleaned_data


@admin.register(Alquiler)
class AlquilerAdmin(admin.ModelAdmin):
    form = AlquilerAdminForm
    list_display = [
        "fecha_alquiler",
        "cliente",
        "pelicula",
        "estado",
        "pagado",
        "metodo_pago",
        "fecha_pago",
        "precio",
        "fecha_devolucion",
    ]
    list_filter = [
        "estado",
        "pagado",
        "metodo_pago",
        "fecha_alquiler",
        "fecha_pago",
        "fecha_devolucion",
        FechaAlquilerRangoFiltro,
    ]
    search_fields = ["cliente__nombre", "cliente__dni", "pelicula__titulo", "metodo_pago__nombre"]
    date_hierarchy = "fecha_alquiler"
    ordering = ["-fecha_alquiler", "-id"]
    list_per_page = 50
    list_select_related = ["cliente", "pelicula", "metodo_pago"]
    autocomplete_fields = ["cliente", "pelicula", "metodo_pago"]
    actions = ["marcar_pagados_en_lote"]
    change_list_template = "admin/tienda/alquiler/change_list.html"

    readonly_base_non_superuser = ("cliente", "pelicula", "precio", "fecha_pago", "pagado", "estado")
    readonly_when_paid_or_void = (
        "cliente",
        "pelicula",
        "fecha_alquiler",
        "precio",
        "estado",
        "pagado",
        "metodo_pago",
        "fecha_pago",
        "fecha_devolucion",
    )

    @admin.action(description="Marcar seleccionados como pagados")
    def marcar_pagados_en_lote(self, request, queryset):
        actualizados = 0
        omitidos = 0
        errores = 0
        for alquiler in queryset:
            if alquiler.estado != alquiler.ESTADO_PENDIENTE:
                omitidos += 1
                continue
            try:
                alquiler.marcar_pagado()
                actualizados += 1
            except ValidationError:
                errores += 1

        parts = [f"Pagados: {actualizados}."]
        if omitidos:
            parts.append(f"Omitidos (no pendientes): {omitidos}.")
        if errores:
            parts.append(f"Con error: {errores}.")
        level = messages.SUCCESS if actualizados else messages.WARNING
        self.message_user(request, " ".join(parts), level=level)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        fecha_desde = request.GET.get("fecha_desde")
        fecha_hasta = request.GET.get("fecha_hasta")
        if fecha_desde:
            qs = qs.filter(fecha_alquiler__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(fecha_alquiler__lte=fecha_hasta)
        return qs

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["fecha_desde"] = request.GET.get("fecha_desde", "")
        extra_context["fecha_hasta"] = request.GET.get("fecha_hasta", "")
        return super().changelist_view(request, extra_context=extra_context)

    def get_readonly_fields(self, request, obj=None):
        readonly = set()
        if not request.user.is_superuser:
            readonly.update(self.readonly_base_non_superuser)
        if obj and obj.estado in {Alquiler.ESTADO_PAGADO, Alquiler.ESTADO_ANULADO}:
            readonly.update(self.readonly_when_paid_or_void)
        return sorted(readonly)


@admin.register(MetodoPago)
class MetodoPagoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "descripcion", "is_active"]
    search_fields = ["nombre", "descripcion"]
    list_filter = ["is_active"]
    ordering = ["nombre"]
    list_per_page = 30


@admin.register(CajaDiaria)
class CajaDiariaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "cerrada_en", "cerrada_por"]
    search_fields = ["cerrada_por"]
    list_filter = ["fecha"]
    ordering = ["-fecha"]
    list_per_page = 30


@admin.register(LoginAttemptAudit)
class LoginAttemptAuditAdmin(admin.ModelAdmin):
    list_display = ["attempted_at", "username", "ip_address", "path"]
    list_filter = ["attempted_at"]
    search_fields = ["username", "ip_address", "path", "user_agent"]
    date_hierarchy = "attempted_at"
    ordering = ["-attempted_at"]
    list_per_page = 50


@admin.register(ActionAudit)
class ActionAuditAdmin(admin.ModelAdmin):
    list_display = ["created_at", "username", "accion", "entidad", "objeto_id", "descripcion"]
    list_filter = ["accion", "entidad", "created_at"]
    search_fields = ["username", "accion", "entidad", "descripcion"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
    list_per_page = 50


@admin.register(HistorialPrecioPelicula)
class HistorialPrecioPeliculaAdmin(admin.ModelAdmin):
    list_display = ["changed_at", "pelicula", "precio_anterior", "precio_nuevo"]
    list_filter = ["changed_at", "pelicula__categoria"]
    search_fields = ["pelicula__titulo"]
    ordering = ["-changed_at"]
    list_select_related = ["pelicula", "pelicula__categoria"]
    list_per_page = 50


@admin.register(EventoDominio)
class EventoDominioAdmin(admin.ModelAdmin):
    list_display = ["created_at", "evento", "entidad", "referencia_id", "descripcion"]
    list_filter = ["evento", "entidad", "created_at"]
    search_fields = ["evento", "entidad", "descripcion"]
    ordering = ["-created_at"]
    list_per_page = 50
