import datetime
import random
import csv
import io
import sys

from django.contrib import messages
from django.contrib.auth.views import PasswordChangeView
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db.models import Avg, Count, F, Q, Sum
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from .forms import (
    AlquilerAdvancedSearchForm,
    AlquilerCreateForm,
    CategoriaPrecioLoteForm,
    ClienteCSVImportForm,
    CobroMasivoForm,
    CategoriaForm,
    ClienteForm,
    MarcarPagadoForm,
    MetodoPagoForm,
    PeliculaFilterForm,
    PeliculaForm,
    SimularVentasForm,
    VentasFilterForm,
)
from .models import ActionAudit, Alquiler, CajaDiaria, Categoria, Cliente, MetodoPago, Pelicula, UserSecurityProfile
from .mixins import (
    NextUrlRedirectMixin,
    PaginatedOrderedListMixin,
    PrivateViewMixin,
    RateLimitedFormMixin,
    SupervisorRequiredMixin,
    WriteLoginRequiredMixin,
)


def get_safe_next_url(request: HttpRequest) -> str | None:
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def registrar_accion(
    request: HttpRequest,
    *,
    accion: str,
    entidad: str,
    objeto_id: int | None = None,
    descripcion: str = "",
) -> None:
    username = ""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        username = user.get_username() or ""
    ActionAudit.objects.create(
        accion=accion,
        entidad=entidad,
        objeto_id=objeto_id,
        descripcion=descripcion,
        username=username,
    )


def user_is_supervisor(user) -> bool:
    return bool(user.is_authenticated and (user.is_superuser or user.groups.filter(name="supervisor").exists()))


class InitialPasswordChangeView(PrivateViewMixin, PasswordChangeView):
    template_name = "tienda/initial_password_change.html"
    success_url = reverse_lazy("tienda:index")

    def dispatch(self, request, *args, **kwargs):
        profile, _ = UserSecurityProfile.objects.get_or_create(
            user=request.user,
            defaults={"must_change_password": not request.user.is_superuser},
        )
        if not profile.must_change_password:
            return redirect("tienda:index")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        profile, _ = UserSecurityProfile.objects.get_or_create(
            user=self.request.user,
            defaults={"must_change_password": False},
        )
        profile.must_change_password = False
        profile.password_changed_at = timezone.now()
        profile.save(update_fields=["must_change_password", "password_changed_at"])
        messages.success(self.request, "Contraseña actualizada correctamente.")
        return response


class DashboardTemplateView(TemplateView):
    template_name = "tienda/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        cache_key = f"dashboard_metrics:{today.isoformat()}"
        use_cache = "test" not in sys.argv and not settings.DEBUG
        if use_cache:
            cached_metrics = cache.get(cache_key)
            if cached_metrics:
                context.update(cached_metrics)
                return context

        month_start = today.replace(day=1)
        next_month_start = (
            month_start.replace(year=month_start.year + 1, month=1)
            if month_start.month == 12
            else month_start.replace(month=month_start.month + 1)
        )

        metrics = {}
        metrics["total_peliculas"] = Pelicula.objects.filter(is_active=True).count()
        metrics["total_clientes"] = Cliente.objects.filter(is_active=True).count()
        metrics["alquileres_pendientes"] = Alquiler.objects.filter(estado=Alquiler.ESTADO_PENDIENTE).count()
        metrics["ingresos"] = (
            Alquiler.objects.filter(estado=Alquiler.ESTADO_PAGADO).aggregate(total=Sum("precio")).get("total")
            or 0
        )
        metrics["ticket_promedio"] = (
            Alquiler.objects.filter(estado=Alquiler.ESTADO_PAGADO)
            .aggregate(promedio=Avg("precio"))
            .get("promedio")
            or 0
        )
        metrics["top_peliculas"] = (
            Pelicula.objects.filter(is_active=True)
            .annotate(total_alquileres=Count("alquileres"))
            .order_by("-total_alquileres", "titulo")[
                :10
            ]
        )
        metrics["ingresos_por_categoria"] = (
            Alquiler.objects.filter(estado=Alquiler.ESTADO_PAGADO)
            .values("pelicula__categoria__nombre")
            .annotate(total=Sum("precio"))
            .order_by("-total", "pelicula__categoria__nombre")
        )
        metrics["clientes_sin_alquileres"] = (
            Cliente.objects.filter(is_active=True)
            .annotate(total_alquileres=Count("alquileres"))
            .filter(total_alquileres=0)
            .order_by("nombre")
        )
        metrics["alquileres_vencidos"] = (
            Alquiler.objects.filter(
                estado=Alquiler.ESTADO_PENDIENTE,
                fecha_alquiler__lt=timezone.localdate(),
            )
            .select_related("cliente", "pelicula")
            .order_by("fecha_alquiler", "id")
        )
        metrics["ranking_mensual_clientes"] = (
            Alquiler.objects.filter(
                estado=Alquiler.ESTADO_PAGADO,
                fecha_alquiler__gte=month_start,
                fecha_alquiler__lt=next_month_start,
            )
            .values("cliente__nombre")
            .annotate(total_gastado=Sum("precio"))
            .order_by("-total_gastado", "cliente__nombre")
        )
        metrics["ranking_mensual_mes"] = month_start
        metrics["caja_cerrada_hoy"] = CajaDiaria.esta_cerrada(today)
        metrics["caja_fecha_hoy"] = today
        metrics["can_simular_ventas"] = user_is_supervisor(self.request.user)
        if use_cache:
            cache.set(cache_key, metrics, 60)
        context.update(metrics)
        return context


class AuditListView(PrivateViewMixin, PaginatedOrderedListMixin, ListView):
    model = ActionAudit
    template_name = "tienda/auditoria_list.html"
    context_object_name = "auditorias"
    ordering_fields = ("created_at", "accion", "entidad", "username")
    default_ordering = ("-created_at",)

    def get_queryset(self):
        qs = super().get_queryset()
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(accion__icontains=q)
                | Q(entidad__icontains=q)
                | Q(descripcion__icontains=q)
                | Q(username__icontains=q)
            )
        self.search_query = q
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = getattr(self, "search_query", "")
        return context


class CategoriaListView(PaginatedOrderedListMixin, ListView):
    model = Categoria
    template_name = "tienda/categoria_list.html"
    context_object_name = "categorias"
    ordering_fields = ("nombre",)
    default_ordering = ("nombre",)

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class CategoriaCreateView(NextUrlRedirectMixin, PrivateViewMixin, CreateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = "tienda/categoria_form.html"
    success_url = reverse_lazy("tienda:categoria_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="crear",
            entidad="categoria",
            objeto_id=self.object.pk,
            descripcion=self.object.nombre,
        )
        messages.success(self.request, "Categoría creada correctamente.")
        return response


class CategoriaUpdateView(NextUrlRedirectMixin, PrivateViewMixin, UpdateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = "tienda/categoria_form.html"
    success_url = reverse_lazy("tienda:categoria_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="editar",
            entidad="categoria",
            objeto_id=self.object.pk,
            descripcion=self.object.nombre,
        )
        messages.success(self.request, "Categoría actualizada correctamente.")
        return response

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class CategoriaDeleteView(PrivateViewMixin, View):
    template_name = "tienda/categoria_confirm_delete.html"

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        categoria = get_object_or_404(Categoria, pk=pk, is_active=True)
        return render(
            request,
            self.template_name,
            {"object": categoria, "next_url": get_safe_next_url(request)},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        categoria = get_object_or_404(Categoria, pk=pk, is_active=True)
        categoria.is_active = False
        categoria.save(update_fields=["is_active"])
        registrar_accion(
            request,
            accion="desactivar",
            entidad="categoria",
            objeto_id=categoria.pk,
            descripcion=categoria.nombre,
        )
        messages.warning(request, "Categoría desactivada.")
        return redirect(get_safe_next_url(request) or "tienda:categoria_list")


class MetodoPagoListView(PaginatedOrderedListMixin, ListView):
    model = MetodoPago
    template_name = "tienda/metodo_pago_list.html"
    context_object_name = "metodos_pago"
    ordering_fields = ("nombre",)
    default_ordering = ("nombre",)

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class MetodoPagoCreateView(NextUrlRedirectMixin, PrivateViewMixin, CreateView):
    model = MetodoPago
    form_class = MetodoPagoForm
    template_name = "tienda/metodo_pago_form.html"
    success_url = reverse_lazy("tienda:metodo_pago_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="crear",
            entidad="metodo_pago",
            objeto_id=self.object.pk,
            descripcion=self.object.nombre,
        )
        messages.success(self.request, "Método de pago creado correctamente.")
        return response


class MetodoPagoUpdateView(NextUrlRedirectMixin, PrivateViewMixin, UpdateView):
    model = MetodoPago
    form_class = MetodoPagoForm
    template_name = "tienda/metodo_pago_form.html"
    success_url = reverse_lazy("tienda:metodo_pago_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="editar",
            entidad="metodo_pago",
            objeto_id=self.object.pk,
            descripcion=self.object.nombre,
        )
        messages.success(self.request, "Método de pago actualizado correctamente.")
        return response

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class MetodoPagoDeleteView(PrivateViewMixin, View):
    template_name = "tienda/metodo_pago_confirm_delete.html"

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        metodo = get_object_or_404(MetodoPago, pk=pk, is_active=True)
        return render(
            request,
            self.template_name,
            {"object": metodo, "next_url": get_safe_next_url(request)},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        metodo = get_object_or_404(MetodoPago, pk=pk, is_active=True)
        metodo.is_active = False
        metodo.save(update_fields=["is_active"])
        registrar_accion(
            request,
            accion="desactivar",
            entidad="metodo_pago",
            objeto_id=metodo.pk,
            descripcion=metodo.nombre,
        )
        messages.warning(request, "Método de pago desactivado.")
        return redirect(get_safe_next_url(request) or "tienda:metodo_pago_list")


class ClienteListView(PaginatedOrderedListMixin, ListView):
    model = Cliente
    template_name = "tienda/cliente_list.html"
    context_object_name = "clientes"
    ordering_fields = ("nombre", "dni", "email")
    default_ordering = ("nombre",)

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class ClienteDetailView(DetailView):
    model = Cliente
    template_name = "tienda/cliente_detail.html"
    context_object_name = "cliente"

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        historial = (
            self.object.alquileres.select_related("pelicula", "pelicula__categoria", "metodo_pago")
            .order_by("-fecha_alquiler", "-id")
        )
        context["historial_alquileres"] = historial
        context["total_alquileres"] = historial.count()
        return context


class ClienteCreateView(NextUrlRedirectMixin, PrivateViewMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "tienda/cliente_form.html"
    success_url = reverse_lazy("tienda:cliente_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="crear",
            entidad="cliente",
            objeto_id=self.object.pk,
            descripcion=self.object.nombre,
        )
        messages.success(self.request, "Cliente creado correctamente.")
        return response


class ClienteUpdateView(NextUrlRedirectMixin, PrivateViewMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "tienda/cliente_form.html"
    success_url = reverse_lazy("tienda:cliente_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="editar",
            entidad="cliente",
            objeto_id=self.object.pk,
            descripcion=self.object.nombre,
        )
        messages.success(self.request, "Cliente actualizado correctamente.")
        return response

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class ClienteDeleteView(PrivateViewMixin, View):
    template_name = "tienda/cliente_confirm_delete.html"

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        cliente = get_object_or_404(Cliente, pk=pk, is_active=True)
        return render(
            request,
            self.template_name,
            {"object": cliente, "next_url": get_safe_next_url(request)},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        cliente = get_object_or_404(Cliente, pk=pk, is_active=True)
        cliente.is_active = False
        cliente.save(update_fields=["is_active"])
        registrar_accion(
            request,
            accion="desactivar",
            entidad="cliente",
            objeto_id=cliente.pk,
            descripcion=cliente.nombre,
        )
        messages.warning(request, "Cliente desactivado.")
        return redirect(get_safe_next_url(request) or "tienda:cliente_list")


class ClienteExportCSVView(PrivateViewMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="clientes.csv"'

        writer = csv.writer(response)
        writer.writerow(["nombre", "dni", "email", "telefono"])
        clientes = Cliente.objects.filter(is_active=True).order_by("nombre")
        for cliente in clientes:
            writer.writerow(
                [
                    cliente.nombre,
                    cliente.dni,
                    cliente.email or "",
                    cliente.telefono or "",
                ]
            )

        return response


class ClienteImportCSVView(PrivateViewMixin, RateLimitedFormMixin, View):
    template_name = "tienda/cliente_import_csv.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = ClienteCSVImportForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = ClienteCSVImportForm(request.POST, request.FILES)
        context = {"form": form}
        if not form.is_valid():
            return render(request, self.template_name, context)

        csv_file = form.cleaned_data["csv_file"]
        actualizar_existentes = form.cleaned_data["actualizar_existentes"]
        content = csv_file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))

        errors = []
        rows = []
        seen_dni = set()

        for line_number, row in enumerate(reader, start=2):
            normalized = {str(key).strip().lower(): (value or "").strip() for key, value in row.items()}
            nombre = normalized.get("nombre", "")
            dni = normalized.get("dni", "")
            email = normalized.get("email", "")
            telefono = normalized.get("telefono", "")
            row_errors = []

            if not nombre:
                row_errors.append(f"Fila {line_number}: el nombre es obligatorio.")
            if not dni:
                row_errors.append(f"Fila {line_number}: el DNI es obligatorio.")
            elif len(dni) != 8 or not dni.isdigit():
                row_errors.append(f"Fila {line_number}: el DNI debe tener 8 dígitos numéricos.")

            if dni in seen_dni:
                row_errors.append(f"Fila {line_number}: el DNI {dni} está repetido dentro del CSV.")
            elif dni:
                seen_dni.add(dni)

            if row_errors:
                errors.extend(row_errors)
            else:
                rows.append(
                    {
                        "nombre": nombre,
                        "dni": dni,
                        "email": email or None,
                        "telefono": telefono,
                    }
                )

        if errors:
            messages.error(request, "El CSV contiene errores. Revisa el detalle en el formulario.")
            form.add_error(
                None,
                "Se encontraron errores en el CSV: " + " | ".join(errors[:10]),
            )
            return render(request, self.template_name, context)

        created_count = 0
        updated_count = 0
        skipped_count = 0

        try:
            with transaction.atomic():
                for data in rows:
                    cliente = Cliente.objects.filter(dni=data["dni"]).first()
                    if cliente is None:
                        nuevo = Cliente(**data)
                        nuevo.full_clean()
                        nuevo.save()
                        created_count += 1
                        continue

                    if not actualizar_existentes:
                        skipped_count += 1
                        continue

                    cliente.nombre = data["nombre"]
                    cliente.email = data["email"]
                    cliente.telefono = data["telefono"]
                    cliente.full_clean()
                    cliente.save(update_fields=["nombre", "email", "telefono"])
                    updated_count += 1
        except ValidationError as error:
            messages.error(request, "No se pudo completar la importación por errores de validación.")
            form.add_error(None, f"Error de validación al importar: {error}")
            return render(request, self.template_name, context)

        context.update(
            {
                "resumen": {
                    "creados": created_count,
                    "actualizados": updated_count,
                    "omitidos": skipped_count,
                }
            }
        )
        messages.success(
            request,
            f"Importación completada. Creados: {created_count}, actualizados: {updated_count}, omitidos: {skipped_count}.",
        )
        registrar_accion(
            request,
            accion="importar_csv",
            entidad="cliente",
            descripcion=f"creados={created_count}, actualizados={updated_count}, omitidos={skipped_count}",
        )
        return render(request, self.template_name, context)


class PapeleraListView(PrivateViewMixin, TemplateView):
    template_name = "tienda/papelera_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categorias_eliminadas"] = Categoria.objects.filter(is_active=False).order_by("nombre")
        context["clientes_eliminados"] = Cliente.objects.filter(is_active=False).order_by("nombre")
        context["peliculas_eliminadas"] = Pelicula.objects.filter(is_active=False).order_by("titulo", "anio")
        context["metodos_pago_eliminados"] = MetodoPago.objects.filter(is_active=False).order_by("nombre")
        return context


class RestoreCategoriaView(PrivateViewMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        categoria = get_object_or_404(Categoria, pk=pk, is_active=False)
        categoria.is_active = True
        categoria.save(update_fields=["is_active"])
        registrar_accion(request, accion="restaurar", entidad="categoria", objeto_id=categoria.pk, descripcion=categoria.nombre)
        messages.success(request, "Categoría restaurada.")
        return redirect("tienda:papelera_list")


class RestoreClienteView(PrivateViewMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        cliente = get_object_or_404(Cliente, pk=pk, is_active=False)
        cliente.is_active = True
        cliente.save(update_fields=["is_active"])
        registrar_accion(request, accion="restaurar", entidad="cliente", objeto_id=cliente.pk, descripcion=cliente.nombre)
        messages.success(request, "Cliente restaurado.")
        return redirect("tienda:papelera_list")


class RestorePeliculaView(PrivateViewMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        pelicula = get_object_or_404(Pelicula, pk=pk, is_active=False)
        pelicula.is_active = True
        pelicula.save(update_fields=["is_active"])
        registrar_accion(request, accion="restaurar", entidad="pelicula", objeto_id=pelicula.pk, descripcion=pelicula.titulo)
        messages.success(request, "Película restaurada.")
        return redirect("tienda:papelera_list")


class RestoreMetodoPagoView(PrivateViewMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        metodo = get_object_or_404(MetodoPago, pk=pk, is_active=False)
        metodo.is_active = True
        metodo.save(update_fields=["is_active"])
        registrar_accion(request, accion="restaurar", entidad="metodo_pago", objeto_id=metodo.pk, descripcion=metodo.nombre)
        messages.success(request, "Método de pago restaurado.")
        return redirect("tienda:papelera_list")


class PeliculaListView(PaginatedOrderedListMixin, ListView):
    model = Pelicula
    template_name = "tienda/pelicula_list.html"
    context_object_name = "peliculas"
    ordering_fields = ("titulo", "anio", "precio_alquiler", "stock")
    default_ordering = ("titulo", "anio")

    def get_queryset(self):
        qs = super().get_queryset().filter(is_active=True, categoria__is_active=True).select_related("categoria")
        self.filter_form = PeliculaFilterForm(self.request.GET)
        if self.filter_form.is_valid():
            anio = self.filter_form.cleaned_data.get("anio")
            categoria = self.filter_form.cleaned_data.get("categoria")
            precio_min = self.filter_form.cleaned_data.get("precio_min")
            precio_max = self.filter_form.cleaned_data.get("precio_max")
            if anio:
                qs = qs.filter(anio=anio)
            if categoria:
                qs = qs.filter(categoria=categoria)
            if precio_min is not None:
                qs = qs.filter(precio_alquiler__gte=precio_min)
            if precio_max is not None:
                qs = qs.filter(precio_alquiler__lte=precio_max)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = getattr(self, "filter_form", PeliculaFilterForm())
        return ctx


class PeliculaDetailView(DetailView):
    model = Pelicula
    template_name = "tienda/pelicula_detail.html"
    context_object_name = "pelicula"

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True, categoria__is_active=True).select_related("categoria")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        alquileres = self.object.alquileres.select_related("cliente", "metodo_pago").order_by(
            "-fecha_alquiler", "-id"
        )
        context["historial_alquileres"] = alquileres
        context["veces_alquilada"] = alquileres.count()
        context["veces_pagada"] = alquileres.filter(estado=Alquiler.ESTADO_PAGADO).count()
        context["ingresos_generados"] = (
            alquileres.filter(estado=Alquiler.ESTADO_PAGADO).aggregate(total=Sum("precio")).get("total") or 0
        )
        return context


class PeliculaCreateView(NextUrlRedirectMixin, PrivateViewMixin, CreateView):
    model = Pelicula
    form_class = PeliculaForm
    template_name = "tienda/pelicula_form.html"
    success_url = reverse_lazy("tienda:pelicula_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="crear",
            entidad="pelicula",
            objeto_id=self.object.pk,
            descripcion=self.object.titulo,
        )
        messages.success(self.request, "Película creada correctamente.")
        return response


class PeliculaUpdateView(NextUrlRedirectMixin, PrivateViewMixin, UpdateView):
    model = Pelicula
    form_class = PeliculaForm
    template_name = "tienda/pelicula_form.html"
    success_url = reverse_lazy("tienda:pelicula_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_accion(
            self.request,
            accion="editar",
            entidad="pelicula",
            objeto_id=self.object.pk,
            descripcion=self.object.titulo,
        )
        messages.success(self.request, "Película actualizada correctamente.")
        return response

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class PeliculaDeleteView(PrivateViewMixin, View):
    template_name = "tienda/pelicula_confirm_delete.html"

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        pelicula = get_object_or_404(Pelicula, pk=pk, is_active=True)
        return render(
            request,
            self.template_name,
            {"object": pelicula, "next_url": get_safe_next_url(request)},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        pelicula = get_object_or_404(Pelicula, pk=pk, is_active=True)
        pelicula.is_active = False
        pelicula.save(update_fields=["is_active"])
        registrar_accion(
            request,
            accion="desactivar",
            entidad="pelicula",
            objeto_id=pelicula.pk,
            descripcion=pelicula.titulo,
        )
        messages.warning(request, "Película desactivada.")
        return redirect(get_safe_next_url(request) or "tienda:pelicula_list")


class PeliculaActualizarPreciosLoteView(PrivateViewMixin, View):
    template_name = "tienda/pelicula_actualizar_precios_lote.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = CategoriaPrecioLoteForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = CategoriaPrecioLoteForm(request.POST)
        context = {"form": form}
        if form.is_valid():
            categoria = form.cleaned_data["categoria"]
            nuevo_precio = form.cleaned_data["nuevo_precio"]
            actualizados = Pelicula.objects.filter(categoria=categoria, is_active=True).update(precio_alquiler=nuevo_precio)
            context["actualizados"] = actualizados
            context["categoria"] = categoria
            context["nuevo_precio"] = nuevo_precio
            messages.success(
                request,
                f"Se actualizaron {actualizados} películas de la categoría {categoria.nombre}.",
            )
            registrar_accion(
                request,
                accion="actualizar_precios_lote",
                entidad="pelicula",
                descripcion=f"categoria={categoria.nombre}, actualizados={actualizados}",
            )
        return render(request, self.template_name, context)


class AlquilerCreateView(NextUrlRedirectMixin, PrivateViewMixin, CreateView):
    model = Alquiler
    form_class = AlquilerCreateForm
    template_name = "tienda/alquiler_form.html"
    success_url = reverse_lazy("tienda:alquiler_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["cliente"].queryset = Cliente.objects.filter(is_active=True)
        form.fields["pelicula"].queryset = Pelicula.objects.filter(is_active=True, stock__gt=0)
        return form

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
            messages.success(self.request, "Alquiler registrado correctamente.")
            registrar_accion(
                self.request,
                accion="crear",
                entidad="alquiler",
                objeto_id=self.object.pk,
                descripcion=f"cliente={self.object.cliente_id}, pelicula={self.object.pelicula_id}",
            )
            return response
        except ValidationError as error:
            messages.error(self.request, "No se pudo registrar el alquiler.")
            form.add_error(None, error)
            return self.form_invalid(form)


class AlquilerListView(WriteLoginRequiredMixin, RateLimitedFormMixin, PaginatedOrderedListMixin, ListView):
    model = Alquiler
    template_name = "tienda/alquiler_list.html"
    context_object_name = "alquileres"
    ordering_fields = ("id", "fecha_alquiler", "precio", "estado")
    default_ordering = ("-fecha_alquiler", "-id")

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente", "pelicula", "pelicula__categoria", "metodo_pago")
        self.search_form = AlquilerAdvancedSearchForm(self.request.GET)
        if self.search_form.is_valid():
            cliente = self.search_form.cleaned_data.get("cliente")
            pelicula = self.search_form.cleaned_data.get("pelicula")
            categoria = self.search_form.cleaned_data.get("categoria")
            estado = self.search_form.cleaned_data.get("estado")
            fecha_desde = self.search_form.cleaned_data.get("fecha_desde")
            fecha_hasta = self.search_form.cleaned_data.get("fecha_hasta")
            precio_min = self.search_form.cleaned_data.get("precio_min")
            precio_max = self.search_form.cleaned_data.get("precio_max")
            solo_vencidos = self.search_form.cleaned_data.get("solo_vencidos")

            if cliente:
                qs = qs.filter(cliente=cliente)
            if pelicula:
                qs = qs.filter(pelicula=pelicula)
            if categoria:
                qs = qs.filter(pelicula__categoria=categoria)
            if estado:
                qs = qs.filter(estado=estado)
            if fecha_desde:
                qs = qs.filter(fecha_alquiler__gte=fecha_desde)
            if fecha_hasta:
                qs = qs.filter(fecha_alquiler__lte=fecha_hasta)
            if precio_min is not None:
                qs = qs.filter(precio__gte=precio_min)
            if precio_max is not None:
                qs = qs.filter(precio__lte=precio_max)
            if solo_vencidos:
                qs = qs.filter(estado=Alquiler.ESTADO_PENDIENTE, fecha_alquiler__lt=timezone.localdate())

        # Compatibilidad con enlaces antiguos ?pagado=0/1
        pagado = self.request.GET.get("pagado")
        if pagado == "1":
            qs = qs.filter(estado=Alquiler.ESTADO_PAGADO)
        elif pagado == "0":
            qs = qs.filter(estado=Alquiler.ESTADO_PENDIENTE)
        return qs

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.bulk_form = CobroMasivoForm(request.POST)
        if self.bulk_form.is_valid():
            ids = self.bulk_form.cleaned_data["ids"]
            metodo_pago = self.bulk_form.cleaned_data.get("metodo_pago")
            fecha_devolucion = self.bulk_form.cleaned_data.get("fecha_devolucion")

            alquileres = list(Alquiler.objects.filter(id__in=ids).order_by("id"))
            found_ids = {a.id for a in alquileres}
            missing_ids = [str(alq_id) for alq_id in ids if alq_id not in found_ids]
            if missing_ids:
                messages.warning(request, "Algunos IDs de cobro masivo no existen.")
                self.bulk_form.add_error(None, f"No existen estos IDs: {', '.join(missing_ids)}.")

            cobrados = 0
            for alquiler in alquileres:
                estaba_pagado = alquiler.pagado
                try:
                    alquiler.marcar_pagado(
                        fecha_devolucion=fecha_devolucion,
                        metodo_pago=metodo_pago,
                    )
                except ValidationError as error:
                    messages.error(request, f"No se pudo cobrar el alquiler ID {alquiler.id}.")
                    self.bulk_form.add_error(None, f"ID {alquiler.id}: {error}")
                    continue
                if not estaba_pagado and alquiler.pagado:
                    cobrados += 1

            if not self.bulk_form.errors:
                messages.success(request, f"Cobro masivo aplicado. Alquileres cobrados: {cobrados}.")
                registrar_accion(
                    request,
                    accion="cobro_masivo",
                    entidad="alquiler",
                    descripcion=f"ids={ids}, cobrados={cobrados}",
                )
                return redirect(f"{reverse_lazy('tienda:alquiler_list')}?cobro_ok=1&cobrados={cobrados}")

        self.object_list = self.get_queryset()
        context = self.get_context_data()
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_form"] = getattr(self, "search_form", AlquilerAdvancedSearchForm(self.request.GET))
        ctx["bulk_form"] = getattr(self, "bulk_form", CobroMasivoForm())
        ctx["cobro_ok"] = self.request.GET.get("cobro_ok") == "1"
        ctx["cobrados"] = self.request.GET.get("cobrados")
        return ctx


class MarcarPagadoView(PrivateViewMixin, RateLimitedFormMixin, View):
    template_name = "tienda/marcar_pagado.html"

    def _can_manage_object(self, request: HttpRequest, alquiler: Alquiler) -> bool:
        user = request.user
        if user_is_supervisor(user):
            return True
        if not user.has_perm("tienda.change_alquiler"):
            return False
        if user.groups.filter(name="cajero").exists():
            return alquiler.estado == Alquiler.ESTADO_PENDIENTE and alquiler.fecha_alquiler == timezone.localdate()
        return False

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        alquiler = get_object_or_404(Alquiler, pk=pk)
        if not self._can_manage_object(request, alquiler):
            messages.error(request, "No tienes permiso para marcar este alquiler como pagado.")
            return redirect("tienda:alquiler_list")
        form = MarcarPagadoForm(alquiler=alquiler)
        return render(
            request,
            self.template_name,
            {"alquiler": alquiler, "form": form, "next_url": get_safe_next_url(request)},
        )

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        alquiler = get_object_or_404(Alquiler, pk=pk)
        if not self._can_manage_object(request, alquiler):
            messages.error(request, "No tienes permiso para marcar este alquiler como pagado.")
            return redirect("tienda:alquiler_list")
        form = MarcarPagadoForm(request.POST, alquiler=alquiler)
        if form.is_valid():
            try:
                alquiler.marcar_pagado(
                    fecha_devolucion=form.cleaned_data.get("fecha_devolucion"),
                    metodo_pago=form.cleaned_data.get("metodo_pago"),
                )
                messages.success(request, "Alquiler marcado como pagado.")
                registrar_accion(
                    request,
                    accion="marcar_pagado",
                    entidad="alquiler",
                    objeto_id=alquiler.pk,
                    descripcion=f"metodo_pago={form.cleaned_data.get('metodo_pago')}",
                )
                return redirect(get_safe_next_url(request) or "tienda:alquiler_list")
            except ValidationError as error:
                messages.error(request, "No se pudo marcar el alquiler como pagado.")
                form.add_error(None, error)
        return render(
            request,
            self.template_name,
            {"alquiler": alquiler, "form": form, "next_url": get_safe_next_url(request)},
        )


class AnularAlquilerView(PrivateViewMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        alquiler = get_object_or_404(Alquiler, pk=pk)
        estado_anterior = alquiler.estado
        alquiler.anular()
        if estado_anterior != alquiler.ESTADO_PENDIENTE:
            messages.warning(request, "Solo se pueden anular alquileres pendientes.")
        else:
            messages.success(request, "Alquiler anulado correctamente.")
            registrar_accion(
                request,
                accion="anular",
                entidad="alquiler",
                objeto_id=alquiler.pk,
            )
        return redirect(get_safe_next_url(request) or "tienda:alquiler_list")


class VentasListView(PaginatedOrderedListMixin, ListView):
    model = Alquiler
    template_name = "tienda/ventas_list.html"
    context_object_name = "ventas"
    ordering_fields = ("id", "fecha_alquiler", "precio", "cliente__nombre", "pelicula__titulo")
    default_ordering = ("-fecha_alquiler", "-id")

    def get_queryset(self):
        qs = super().get_queryset().filter(estado=Alquiler.ESTADO_PAGADO).select_related(
            "cliente", "pelicula", "pelicula__categoria", "metodo_pago"
        )
        self.filter_form = VentasFilterForm(self.request.GET)
        if self.filter_form.is_valid():
            desde = self.filter_form.cleaned_data.get("desde")
            hasta = self.filter_form.cleaned_data.get("hasta")
            if desde:
                qs = qs.filter(fecha_alquiler__gte=desde)
            if hasta:
                qs = qs.filter(fecha_alquiler__lte=hasta)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ventas_qs = self.get_queryset()
        ctx["filter_form"] = self.filter_form
        ctx["can_simular_ventas"] = user_is_supervisor(self.request.user)
        ctx["total_ingresos"] = ventas_qs.aggregate(total=Sum("precio")).get("total") or 0
        today = timezone.localdate()
        ctx["caja_cerrada_hoy"] = CajaDiaria.esta_cerrada(today)
        ctx["caja_fecha_hoy"] = today
        ctx["ventas_por_dia"] = (
            ventas_qs
            .values(fecha=F("fecha_alquiler"))
            .annotate(total=Sum("precio"))
            .order_by("fecha")
        )
        return ctx


class CerrarCajaDiariaView(PrivateViewMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        today = timezone.localdate()
        _, created = CajaDiaria.objects.get_or_create(
            fecha=today,
            defaults={"cerrada_por": request.user.get_username()},
        )
        if created:
            messages.success(request, f"Caja diaria cerrada para {today}.")
            registrar_accion(
                request,
                accion="cerrar_caja",
                entidad="ventas",
                descripcion=f"fecha={today}",
            )
        else:
            messages.warning(request, f"La caja diaria de {today} ya estaba cerrada.")
        return redirect("tienda:ventas_list")


class SimularVentasFormView(SupervisorRequiredMixin, RateLimitedFormMixin, FormView):
    template_name = "tienda/simular_ventas.html"
    form_class = SimularVentasForm

    def get_initial(self):
        initial = super().get_initial()
        today = timezone.localdate()
        initial.update(
            {
                "numero_ventas": 10,
                "desde": today,
                "hasta": today,
            }
        )
        return initial

    def form_valid(self, form):
        numero = form.cleaned_data["numero_ventas"]
        desde = form.cleaned_data["desde"]
        hasta = form.cleaned_data["hasta"]
        today = timezone.localdate()

        # Manejo defensivo: si llega solo una fecha, usamos la otra como respaldo.
        if desde is None and hasta is None:
            desde = today
            hasta = today
        elif desde is None:
            desde = hasta
        elif hasta is None:
            hasta = desde

        if CajaDiaria.esta_cerrada(timezone.localdate()):
            messages.warning(self.request, "Caja cerrada: no se pueden simular ventas hoy.")
            return self.render_to_response(
                self.get_context_data(
                    form=form,
                    error="La caja diaria de hoy está cerrada. No se pueden registrar nuevas ventas.",
                )
            )

        clientes = list(Cliente.objects.filter(is_active=True))
        peliculas = list(Pelicula.objects.filter(is_active=True, stock__gt=0))

        if not clientes or not peliculas:
            messages.warning(self.request, "No hay datos suficientes para simular ventas.")
            return self.render_to_response(
                self.get_context_data(
                    form=form,
                    error="Necesitas al menos 1 cliente y 1 película con stock para simular.",
                )
            )

        alquileres_creados = 0
        delta_dias = (hasta - desde).days if hasta >= desde else 0

        for _ in range(numero):
            peliculas_disponibles = [p for p in peliculas if p.stock > 0]
            if not peliculas_disponibles:
                break

            cliente = random.choice(clientes)
            pelicula = random.choice(peliculas_disponibles)

            offset = random.randint(0, max(delta_dias, 0))
            fecha_alquiler = desde + datetime.timedelta(days=offset)
            fecha_devolucion = fecha_alquiler + datetime.timedelta(days=random.randint(0, 7))
            try:
                Alquiler.objects.create(
                    cliente=cliente,
                    pelicula=pelicula,
                    fecha_alquiler=fecha_alquiler,
                    estado=Alquiler.ESTADO_PAGADO,
                    pagado=True,
                    fecha_devolucion=fecha_devolucion,
                )
            except ValidationError:
                pelicula.refresh_from_db()
                continue

            pelicula.refresh_from_db()
            alquileres_creados += 1

        if alquileres_creados == 0:
            messages.error(self.request, "No se pudo generar ninguna venta.")
            return self.render_to_response(
                self.get_context_data(
                    form=form,
                    error="No se pudo generar ninguna venta porque no hay suficiente stock disponible.",
                )
            )

        resumen = {
            "solicitadas": numero,
            "creadas": alquileres_creados,
            "omitidas": numero - alquileres_creados,
            "desde": desde,
            "hasta": hasta,
        }
        messages.success(self.request, f"Simulación completada: {alquileres_creados} ventas creadas.")
        return self.render_to_response(self.get_context_data(form=form, resumen=resumen))


