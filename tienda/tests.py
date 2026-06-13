import csv
import datetime
import time
from unittest.mock import patch
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .forms import (
    AlquilerAdvancedSearchForm,
    AlquilerCreateForm,
    CategoriaForm,
    CategoriaPrecioLoteForm,
    ClienteCSVImportForm,
    ClienteForm,
    CobroMasivoForm,
    MarcarPagadoForm,
    MetodoPagoForm,
    PeliculaFilterForm,
    PeliculaForm,
    SimularVentasForm,
    VentasFilterForm,
)
from .models import (
    ActionAudit,
    Alquiler,
    CajaDiaria,
    Categoria,
    Cliente,
    EventoDominio,
    HistorialPrecioPelicula,
    MetodoPago,
    Pelicula,
    UserSecurityProfile,
)


class TiendaViewTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre="Acción")
        self.pelicula = Pelicula.objects.create(
            titulo="Prueba",
            anio=2020,
            categoria=self.categoria,
            precio_alquiler=10.00,
            duracion_minutos=120,
            stock=5,
        )
        self.cliente = Cliente.objects.create(
            nombre="Cliente prueba",
            dni="12345678",
            email="cliente@example.com",
        )
        self.metodo_pago = MetodoPago.objects.create(nombre="Efectivo")
        self.alquiler = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )
        self.venta = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=1),
            pagado=True,
            fecha_devolucion=timezone.localdate(),
        )

        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="testpassword",
        )
        self.cajero_user = User.objects.create_user(
            username="cajero",
            email="cajero@example.com",
            password="testpassword",
            is_staff=True,
        )
        self.supervisor_user = User.objects.create_user(
            username="supervisor",
            email="supervisor@example.com",
            password="testpassword",
            is_staff=True,
        )
        cajero_group, _ = Group.objects.get_or_create(name="cajero")
        supervisor_group, _ = Group.objects.get_or_create(name="supervisor")
        self.cajero_user.groups.add(cajero_group)
        self.supervisor_user.groups.add(supervisor_group)
        for user in (self.admin_user, self.cajero_user, self.supervisor_user):
            profile, _ = UserSecurityProfile.objects.get_or_create(user=user)
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])

    def test_public_views_return_200(self):
        for name in ["index", "pelicula_list", "alquiler_list", "ventas_list", "metodo_pago_list"]:
            response = self.client.get(reverse(f"tienda:{name}"))
            self.assertEqual(response.status_code, 200)

    def test_authenticated_user_without_metodo_pago_permission_does_not_see_nav_link(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="sin_permiso_metodo",
            email="sin-permiso@example.com",
            password="testpassword",
        )
        profile, _ = UserSecurityProfile.objects.get_or_create(user=user)
        profile.must_change_password = False
        profile.save(update_fields=["must_change_password"])

        self.client.login(username="sin_permiso_metodo", password="testpassword")
        response = self.client.get(reverse("tienda:index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Métodos pago")

    def test_ventas_list_filter_returns_200(self):
        desde = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        hasta = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("tienda:ventas_list"),
            {
                "desde": desde,
                "hasta": hasta,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Total de ventas por día")

    def test_dashboard_template_view_shows_kpis(self):
        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Películas")
        self.assertContains(response, "Clientes")
        self.assertContains(response, "Ticket promedio (pagados)")

    def test_simular_ventas_form_view_shows_resumen(self):
        self.client.login(username="admin", password="testpassword")
        fecha = (timezone.localdate() - datetime.timedelta(days=2)).isoformat()
        response = self.client.post(
            reverse("tienda:ventas_simular"),
            {
                "numero_ventas": 1,
                "desde": fecha,
                "hasta": fecha,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumen de simulación")
        self.assertContains(response, "Solicitadas")
        self.assertContains(response, "Creadas")

    def test_simular_ventas_form_view_handles_single_date_without_crash(self):
        self.client.login(username="admin", password="testpassword")
        fecha = timezone.localdate().isoformat()
        response = self.client.post(
            reverse("tienda:ventas_simular"),
            {
                "numero_ventas": 1,
                "desde": "",
                "hasta": fecha,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ("Resumen de simulación" in response.content.decode("utf-8"))
            or ("No se pudo generar ninguna venta" in response.content.decode("utf-8"))
        )

    def test_simular_ventas_is_forbidden_for_non_supervisor(self):
        self.client.login(username="cajero", password="testpassword")
        response = self.client.get(reverse("tienda:ventas_simular"))
        self.assertEqual(response.status_code, 403)

    def test_simular_ventas_is_allowed_for_supervisor(self):
        self.client.login(username="supervisor", password="testpassword")
        response = self.client.get(reverse("tienda:ventas_simular"))
        self.assertEqual(response.status_code, 200)

    def test_metodo_pago_crud_views(self):
        self.client.login(username="admin", password="testpassword")
        create_response = self.client.post(
            reverse("tienda:metodo_pago_create"),
            {"nombre": "Transferencia", "descripcion": "Banco"},
        )
        self.assertEqual(create_response.status_code, 302)
        metodo = MetodoPago.objects.get(nombre="Transferencia")

        update_response = self.client.post(
            reverse("tienda:metodo_pago_update", args=[metodo.pk]),
            {"nombre": "Transferencia", "descripcion": "Banco actualizado"},
        )
        self.assertEqual(update_response.status_code, 302)
        metodo.refresh_from_db()
        self.assertEqual(metodo.descripcion, "Banco actualizado")

        delete_response = self.client.post(reverse("tienda:metodo_pago_delete", args=[metodo.pk]))
        self.assertEqual(delete_response.status_code, 302)
        metodo.refresh_from_db()
        self.assertFalse(metodo.is_active)

    def test_marcar_pagado_view_is_idempotent(self):
        self.client.login(username="admin", password="testpassword")
        url = reverse("tienda:alquiler_marcar_pagado", args=[self.alquiler.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        response = self.client.post(url, {"fecha_devolucion": "", "metodo_pago": self.metodo_pago.pk})
        self.assertEqual(response.status_code, 302)
        self.alquiler.refresh_from_db()
        self.assertTrue(self.alquiler.pagado)
        self.assertEqual(
            ActionAudit.objects.filter(objeto_id=self.alquiler.pk, accion="alquiler_pagado").count(),
            1,
        )
        self.assertEqual(self.alquiler.metodo_pago, self.metodo_pago)
        self.assertEqual(self.alquiler.fecha_pago, timezone.localdate())

        response = self.client.post(url, {"fecha_devolucion": "", "metodo_pago": self.metodo_pago.pk})
        self.assertEqual(response.status_code, 302)
        self.alquiler.refresh_from_db()
        self.assertTrue(self.alquiler.pagado)

    def test_marcar_pagado_view_shows_validation_error_for_invalid_fecha_devolucion(self):
        self.client.login(username="admin", password="testpassword")
        url = reverse("tienda:alquiler_marcar_pagado", args=[self.alquiler.pk])
        invalid_date = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        response = self.client.post(url, {"fecha_devolucion": invalid_date, "metodo_pago": self.metodo_pago.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La fecha de devolución no puede ser anterior a la fecha de alquiler.")
        self.alquiler.refresh_from_db()
        self.assertFalse(self.alquiler.pagado)

    def test_marcar_pagado_object_policy_denies_cajero_on_old_alquiler(self):
        self.client.login(username="cajero", password="testpassword")
        alquiler_antiguo = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=2),
            pagado=False,
        )
        response = self.client.post(
            reverse("tienda:alquiler_marcar_pagado", args=[alquiler_antiguo.pk]),
            {"fecha_devolucion": timezone.localdate().isoformat(), "metodo_pago": self.metodo_pago.pk},
        )
        self.assertEqual(response.status_code, 302)
        alquiler_antiguo.refresh_from_db()
        self.assertFalse(alquiler_antiguo.pagado)

    def test_anular_alquiler_view_sets_estado_anulado(self):
        self.client.login(username="admin", password="testpassword")
        url = reverse("tienda:alquiler_anular", args=[self.alquiler.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.alquiler.refresh_from_db()
        self.assertEqual(self.alquiler.estado, Alquiler.ESTADO_ANULADO)
        self.assertFalse(self.alquiler.pagado)

    def test_anular_alquiler_reverts_stock_once(self):
        pelicula_stock = Pelicula.objects.create(
            titulo="Stock Revert",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=7.50,
            duracion_minutos=90,
            stock=2,
        )
        cliente_stock = Cliente.objects.create(
            nombre="Cliente Stock",
            dni="55554444",
            email="stock@example.com",
        )
        alquiler_stock = Alquiler.objects.create(
            cliente=cliente_stock,
            pelicula=pelicula_stock,
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )
        pelicula_stock.refresh_from_db()
        self.assertEqual(pelicula_stock.stock, 1)

        alquiler_stock.anular()
        pelicula_stock.refresh_from_db()
        self.assertEqual(pelicula_stock.stock, 2)

        alquiler_stock.anular()
        pelicula_stock.refresh_from_db()
        self.assertEqual(pelicula_stock.stock, 2)

    def test_post_save_signal_registers_alquiler_events(self):
        before = ActionAudit.objects.count()
        alquiler_event = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=Pelicula.objects.create(
                titulo="Signal Movie",
                anio=2022,
                categoria=self.categoria,
                precio_alquiler=11.00,
                duracion_minutos=95,
                stock=2,
            ),
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )
        self.assertTrue(
            ActionAudit.objects.filter(
                objeto_id=alquiler_event.pk,
                accion="alquiler_creado",
                entidad="alquiler",
            ).exists()
        )

        alquiler_event.marcar_pagado(metodo_pago=self.metodo_pago)
        self.assertTrue(
            ActionAudit.objects.filter(
                objeto_id=alquiler_event.pk,
                accion="alquiler_pagado",
                entidad="alquiler",
            ).exists()
        )
        self.assertGreaterEqual(ActionAudit.objects.count(), before + 2)

    def test_post_delete_signal_registers_audit_event(self):
        pelicula_temp = Pelicula.objects.create(
            titulo="Delete Signal",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=13.00,
            duracion_minutos=100,
            stock=1,
        )
        pk = pelicula_temp.pk
        pelicula_temp.delete()
        self.assertTrue(
            ActionAudit.objects.filter(
                accion="eliminar",
                entidad="pelicula",
                objeto_id=pk,
            ).exists()
        )

    def test_pelicula_price_change_creates_history(self):
        pelicula_hist = Pelicula.objects.create(
            titulo="Precio Historial",
            anio=2020,
            categoria=self.categoria,
            precio_alquiler=10.00,
            duracion_minutos=95,
            stock=3,
        )
        pelicula_hist.precio_alquiler = 15.50
        pelicula_hist.save(update_fields=["precio_alquiler"])

        historial = HistorialPrecioPelicula.objects.filter(pelicula=pelicula_hist).first()
        self.assertIsNotNone(historial)
        self.assertEqual(float(historial.precio_anterior), 10.0)
        self.assertEqual(float(historial.precio_nuevo), 15.5)

    def test_evento_dominio_is_registered_for_key_actions(self):
        alquiler = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=Pelicula.objects.create(
                titulo="Dominio Movie",
                anio=2019,
                categoria=self.categoria,
                precio_alquiler=12.00,
                duracion_minutos=88,
                stock=2,
            ),
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )
        self.assertTrue(EventoDominio.objects.filter(evento="alquiler_creado", referencia_id=alquiler.pk).exists())

        alquiler.marcar_pagado(metodo_pago=self.metodo_pago)
        self.assertTrue(EventoDominio.objects.filter(evento="alquiler_pagado", referencia_id=alquiler.pk).exists())

    def test_admin_requires_login(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_admin_access_after_login(self):
        self.client.login(username="admin", password="testpassword")
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sitio administrativo")

    def test_new_user_is_forced_to_change_initial_password(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="nuevo_user",
            email="nuevo@example.com",
            password="temporal123",
            is_staff=True,
        )
        self.client.login(username="nuevo_user", password="temporal123")
        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("tienda:initial_password_change"), response.url)

        profile = UserSecurityProfile.objects.get(user=user)
        self.assertTrue(profile.must_change_password)

    def test_initial_password_change_turns_off_force_flag(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="nuevo_user2",
            email="nuevo2@example.com",
            password="temporal123",
            is_staff=True,
        )
        self.client.login(username="nuevo_user2", password="temporal123")
        response = self.client.post(
            reverse("tienda:initial_password_change"),
            {
                "old_password": "temporal123",
                "new_password1": "NuevaClaveSegura123!",
                "new_password2": "NuevaClaveSegura123!",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        profile = UserSecurityProfile.objects.get(user=user)
        self.assertFalse(profile.must_change_password)

    @override_settings(SESSION_IDLE_TIMEOUT_SECONDS=1, FORCE_INITIAL_PASSWORD_CHANGE=False)
    def test_session_is_closed_after_inactivity(self):
        self.client.login(username="admin", password="testpassword")
        self.client.get(reverse("tienda:index"))
        session = self.client.session
        session["last_activity_ts"] = int(time.time()) - 10
        session.save()

        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)

    def test_pelicula_slug_is_auto_generated_and_unique(self):
        self.assertEqual(self.pelicula.slug, "prueba")

        otra = Pelicula.objects.create(
            titulo="Prueba",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=12.00,
            duracion_minutos=110,
            stock=2,
        )
        self.assertTrue(otra.slug.startswith("prueba"))
        self.assertNotEqual(otra.slug, self.pelicula.slug)

    def test_pelicula_can_store_director_and_pais_origen(self):
        pelicula = Pelicula.objects.create(
            titulo="Interstellar",
            director="Christopher Nolan",
            pais_origen="EEUU",
            anio=2014,
            categoria=self.categoria,
            precio_alquiler=14.00,
            duracion_minutos=169,
            stock=2,
        )
        self.assertEqual(pelicula.director, "Christopher Nolan")
        self.assertEqual(pelicula.pais_origen, "EEUU")

    @override_settings(PELICULA_PRECIO_MINIMO=15)
    def test_pelicula_form_validates_configurable_min_price(self):
        self.client.login(username="admin", password="testpassword")
        response = self.client.post(
            reverse("tienda:pelicula_create"),
            {
                "titulo": "Precio bajo",
                "director": "Dir",
                "pais_origen": "PE",
                "anio": 2020,
                "categoria": self.categoria.pk,
                "precio_alquiler": "10.00",
                "duracion_minutos": 90,
                "stock": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "El precio de alquiler no puede ser menor a 15.00.")

    def test_pelicula_form_rejects_future_year(self):
        self.client.login(username="admin", password="testpassword")
        response = self.client.post(
            reverse("tienda:pelicula_create"),
            {
                "titulo": "Pelicula futura",
                "director": "Dir",
                "pais_origen": "PE",
                "anio": timezone.localdate().year + 1,
                "categoria": self.categoria.pk,
                "precio_alquiler": "20.00",
                "duracion_minutos": 90,
                "stock": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "El año no puede ser mayor al año actual.")

    def test_main_forms_render_help_text(self):
        self.client.login(username="admin", password="testpassword")
        pelicula_form_response = self.client.get(reverse("tienda:pelicula_create"))
        self.assertEqual(pelicula_form_response.status_code, 200)
        self.assertContains(pelicula_form_response, "Precio por alquiler en soles.")
        self.assertContains(pelicula_form_response, "No puede ser mayor al año actual.")

        cliente_form_response = self.client.get(reverse("tienda:cliente_create"))
        self.assertEqual(cliente_form_response.status_code, 200)
        self.assertContains(cliente_form_response, "Debe tener 8 dígitos y ser único.")

    def test_alquiler_estado_defaults_and_syncs_on_pago(self):
        self.assertEqual(self.alquiler.estado, Alquiler.ESTADO_PENDIENTE)
        self.assertFalse(self.alquiler.pagado)
        self.assertIsNone(self.alquiler.fecha_pago)

        self.alquiler.marcar_pagado(metodo_pago=self.metodo_pago)
        self.alquiler.refresh_from_db()
        self.assertEqual(self.alquiler.estado, Alquiler.ESTADO_PAGADO)
        self.assertTrue(self.alquiler.pagado)
        self.assertEqual(self.alquiler.metodo_pago, self.metodo_pago)
        self.assertEqual(self.alquiler.fecha_pago, timezone.localdate())

    def test_alquiler_rejects_fecha_devolucion_before_fecha_alquiler(self):
        with self.assertRaises(ValidationError):
            Alquiler.objects.create(
                cliente=self.cliente,
                pelicula=self.pelicula,
                fecha_alquiler=timezone.localdate(),
                fecha_devolucion=timezone.localdate() - datetime.timedelta(days=1),
                pagado=False,
            )

    def test_alquiler_rejects_duplicate_cliente_pelicula_fecha(self):
        with self.assertRaises(ValidationError):
            Alquiler.objects.create(
                cliente=self.cliente,
                pelicula=self.pelicula,
                fecha_alquiler=self.alquiler.fecha_alquiler,
                pagado=False,
            )

    def test_alquiler_cross_model_validation_rejects_inactive_related_data(self):
        cliente_inactivo = Cliente.objects.create(
            nombre="Inactivo",
            dni="33445566",
            email="inactivo@example.com",
            is_active=False,
        )
        metodo_inactivo = MetodoPago.objects.create(nombre="Método Inactivo", is_active=False)
        with self.assertRaises(ValidationError):
            Alquiler.objects.create(
                cliente=cliente_inactivo,
                pelicula=self.pelicula,
                fecha_alquiler=timezone.localdate(),
                pagado=False,
                metodo_pago=metodo_inactivo,
            )

    def test_index_shows_top_peliculas_mas_alquiladas(self):
        pelicula_top = Pelicula.objects.create(
            titulo="Top Rental",
            anio=2022,
            categoria=self.categoria,
            precio_alquiler=9.00,
            duracion_minutos=100,
            stock=5,
        )
        cliente_extra = Cliente.objects.create(
            nombre="Cliente Top",
            dni="87654321",
            email="top@example.com",
        )
        Alquiler.objects.create(
            cliente=cliente_extra,
            pelicula=pelicula_top,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=2),
            pagado=False,
        )
        Alquiler.objects.create(
            cliente=cliente_extra,
            pelicula=pelicula_top,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=1),
            pagado=False,
        )

        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Top 10 películas más alquiladas")
        self.assertContains(response, "Top Rental")

    def test_index_shows_ingresos_por_categoria_y_clientes_sin_alquileres(self):
        categoria_drama = Categoria.objects.create(nombre="Drama")
        pelicula_drama = Pelicula.objects.create(
            titulo="Drama Hit",
            anio=2023,
            categoria=categoria_drama,
            precio_alquiler=18.00,
            duracion_minutos=105,
            stock=2,
        )
        cliente_drama = Cliente.objects.create(
            nombre="Cliente Drama",
            dni="11223344",
            email="drama@example.com",
        )
        cliente_sin_alquiler = Cliente.objects.create(
            nombre="Cliente Sin Alquiler",
            dni="99887766",
            email="sin-alquiler@example.com",
        )
        Alquiler.objects.create(
            cliente=cliente_drama,
            pelicula=pelicula_drama,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=3),
            pagado=True,
            fecha_devolucion=timezone.localdate() - datetime.timedelta(days=2),
        )

        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ingresos por categoría")
        self.assertContains(response, "Drama")
        self.assertContains(response, "Clientes sin alquileres")
        self.assertContains(response, cliente_sin_alquiler.nombre)

    def test_index_shows_ticket_promedio_and_alquileres_vencidos(self):
        cliente_vencido = Cliente.objects.create(
            nombre="Cliente Vencido",
            dni="55443322",
            email="vencido@example.com",
        )
        Alquiler.objects.create(
            cliente=cliente_vencido,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=5),
            pagado=False,
        )

        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ticket promedio (pagados)")
        self.assertContains(response, "Alquileres vencidos")
        self.assertContains(response, cliente_vencido.nombre)

    def test_index_shows_ranking_mensual_clientes_por_gasto(self):
        cliente_rank_a = Cliente.objects.create(
            nombre="Cliente Ranking A",
            dni="44332211",
            email="ranka@example.com",
        )
        cliente_rank_b = Cliente.objects.create(
            nombre="Cliente Ranking B",
            dni="66778899",
            email="rankb@example.com",
        )
        Alquiler.objects.create(
            cliente=cliente_rank_a,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate(),
            pagado=True,
            fecha_devolucion=timezone.localdate(),
            precio=30,
        )
        Alquiler.objects.create(
            cliente=cliente_rank_b,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate(),
            pagado=True,
            fecha_devolucion=timezone.localdate(),
            precio=10,
        )

        response = self.client.get(reverse("tienda:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ranking mensual de clientes por gasto total")
        self.assertContains(response, "Cliente Ranking A")
        self.assertContains(response, "Cliente Ranking B")

    def test_pelicula_list_allows_combined_filters(self):
        categoria_otra = Categoria.objects.create(nombre="Comedia")
        Pelicula.objects.create(
            titulo="Filtro Match",
            anio=2024,
            categoria=categoria_otra,
            precio_alquiler=25.00,
            duracion_minutos=100,
            stock=3,
        )
        Pelicula.objects.create(
            titulo="Filtro No Match",
            anio=2022,
            categoria=self.categoria,
            precio_alquiler=8.00,
            duracion_minutos=95,
            stock=3,
        )

        response = self.client.get(
            reverse("tienda:pelicula_list"),
            {
                "anio": 2024,
                "categoria": categoria_otra.pk,
                "precio_min": "20",
                "precio_max": "30",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Filtro Match")
        self.assertNotContains(response, "Filtro No Match")

    def test_alquiler_list_allows_advanced_search_combined_filters(self):
        categoria_drama = Categoria.objects.create(nombre="Drama filtro")
        pelicula_match = Pelicula.objects.create(
            titulo="Busqueda Match",
            anio=2021,
            categoria=categoria_drama,
            precio_alquiler=20.00,
            duracion_minutos=100,
            stock=3,
        )
        pelicula_no_match = Pelicula.objects.create(
            titulo="Busqueda No Match",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=20.00,
            duracion_minutos=100,
            stock=3,
        )
        cliente_filtro = Cliente.objects.create(
            nombre="Cliente Filtro",
            dni="22334455",
            email="filtro@example.com",
        )
        Alquiler.objects.create(
            cliente=cliente_filtro,
            pelicula=pelicula_match,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=3),
            precio=20.00,
            pagado=False,
        )
        Alquiler.objects.create(
            cliente=cliente_filtro,
            pelicula=pelicula_no_match,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=3),
            precio=20.00,
            pagado=False,
        )

        response = self.client.get(
            reverse("tienda:alquiler_list"),
            {
                "cliente": cliente_filtro.pk,
                "categoria": categoria_drama.pk,
                "estado": Alquiler.ESTADO_PENDIENTE,
                "solo_vencidos": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        resultados_ids = {alq.id for alq in response.context["alquileres"]}
        self.assertIn(
            Alquiler.objects.get(cliente=cliente_filtro, pelicula=pelicula_match).id,
            resultados_ids,
        )
        self.assertNotIn(
            Alquiler.objects.get(cliente=cliente_filtro, pelicula=pelicula_no_match).id,
            resultados_ids,
        )

    def test_cobro_masivo_por_ids(self):
        self.client.login(username="admin", password="testpassword")
        pelicula_extra = Pelicula.objects.create(
            titulo="Cobro masivo",
            anio=2020,
            categoria=self.categoria,
            precio_alquiler=11.00,
            duracion_minutos=90,
            stock=2,
        )
        alquiler_extra = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=pelicula_extra,
            fecha_alquiler=timezone.localdate() - datetime.timedelta(days=2),
            pagado=False,
        )

        response = self.client.post(
            reverse("tienda:alquiler_list"),
            {
                "ids": f"{self.alquiler.id}, {alquiler_extra.id}",
                "metodo_pago": self.metodo_pago.pk,
                "fecha_devolucion": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.alquiler.refresh_from_db()
        alquiler_extra.refresh_from_db()
        self.assertTrue(self.alquiler.pagado)
        self.assertTrue(alquiler_extra.pagado)
        self.assertEqual(self.alquiler.metodo_pago, self.metodo_pago)
        self.assertEqual(alquiler_extra.metodo_pago, self.metodo_pago)

    def test_private_views_redirect_when_anonymous(self):
        private_urls = [
            reverse("tienda:pelicula_create"),
            reverse("tienda:cliente_create"),
            reverse("tienda:metodo_pago_create"),
            reverse("tienda:cliente_import_csv"),
            reverse("tienda:pelicula_actualizar_precios_lote"),
            reverse("tienda:papelera_list"),
            reverse("tienda:alquiler_marcar_pagado", args=[self.alquiler.pk]),
        ]
        for url in private_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response.url)

    def test_write_endpoints_require_login(self):
        response_cobro = self.client.post(
            reverse("tienda:alquiler_list"),
            {"ids": str(self.alquiler.id)},
        )
        self.assertEqual(response_cobro.status_code, 302)
        self.assertIn("/admin/login/", response_cobro.url)

        response_simular = self.client.post(
            reverse("tienda:ventas_simular"),
            {
                "numero_ventas": 1,
                "desde": timezone.localdate().isoformat(),
                "hasta": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response_simular.status_code, 302)
        self.assertIn("/admin/login/", response_simular.url)

    @override_settings(RATE_LIMIT_FORM_MAX_ATTEMPTS=1, RATE_LIMIT_FORM_WINDOW_SECONDS=3600)
    def test_rate_limit_blocks_repeated_simular_post(self):
        self.client.login(username="admin", password="testpassword")
        payload = {
            "numero_ventas": 1,
            "desde": timezone.localdate().isoformat(),
            "hasta": timezone.localdate().isoformat(),
        }
        first = self.client.post(reverse("tienda:ventas_simular"), payload)
        self.assertIn(first.status_code, (200, 302))

        second = self.client.post(reverse("tienda:ventas_simular"), payload)
        self.assertEqual(second.status_code, 429)

    def test_borrado_logico_y_restauracion_cliente(self):
        self.client.login(username="admin", password="testpassword")
        delete_response = self.client.post(reverse("tienda:cliente_delete", args=[self.cliente.pk]))
        self.assertEqual(delete_response.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.is_active)

        list_response = self.client.get(reverse("tienda:cliente_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotContains(list_response, self.cliente.nombre)

        restore_response = self.client.post(reverse("tienda:cliente_restore", args=[self.cliente.pk]))
        self.assertEqual(restore_response.status_code, 302)
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.is_active)

    def test_cerrar_caja_diaria_bloquea_nuevas_ventas(self):
        self.client.login(username="admin", password="testpassword")
        close_response = self.client.post(reverse("tienda:ventas_cerrar_caja"))
        self.assertEqual(close_response.status_code, 302)
        self.assertTrue(CajaDiaria.esta_cerrada(timezone.localdate()))

        pay_response = self.client.post(
            reverse("tienda:alquiler_marcar_pagado", args=[self.alquiler.pk]),
            {"fecha_devolucion": timezone.localdate().isoformat(), "metodo_pago": self.metodo_pago.pk},
        )
        self.assertEqual(pay_response.status_code, 200)
        self.assertContains(pay_response, "La caja diaria está cerrada")
        self.alquiler.refresh_from_db()
        self.assertFalse(self.alquiler.pagado)

    def test_simulacion_ventas_bloqueada_si_caja_hoy_esta_cerrada(self):
        self.client.login(username="admin", password="testpassword")
        CajaDiaria.objects.create(fecha=timezone.localdate(), cerrada_por="admin")
        response = self.client.post(
            reverse("tienda:ventas_simular"),
            {
                "numero_ventas": 5,
                "desde": timezone.localdate().isoformat(),
                "hasta": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La caja diaria de hoy está cerrada")

    def test_list_view_accepts_pagination_and_ordering_params(self):
        response = self.client.get(
            reverse("tienda:pelicula_list"),
            {
                "per_page": "5",
                "order": "-anio",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_per_page"], "5")
        self.assertEqual(response.context["current_order"], "-anio")

    def test_list_view_accepts_multiple_ordering_params(self):
        Pelicula.objects.create(
            titulo="Alpha",
            anio=2020,
            categoria=self.categoria,
            precio_alquiler=12.00,
            duracion_minutos=90,
            stock=2,
        )
        Pelicula.objects.create(
            titulo="Beta",
            anio=2020,
            categoria=self.categoria,
            precio_alquiler=20.00,
            duracion_minutos=95,
            stock=2,
        )
        Pelicula.objects.create(
            titulo="Gamma",
            anio=2022,
            categoria=self.categoria,
            precio_alquiler=8.00,
            duracion_minutos=100,
            stock=2,
        )

        response = self.client.get(
            reverse("tienda:pelicula_list"),
            {
                "order": ["anio", "-precio_alquiler"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_order_list"], ["anio", "-precio_alquiler"])
        ordered_titles = [pelicula.titulo for pelicula in response.context["object_list"]]
        self.assertEqual(ordered_titles[:4], ["Beta", "Alpha", "Prueba", "Gamma"])

    def test_cliente_detail_view_shows_historial_alquileres(self):
        response = self.client.get(reverse("tienda:cliente_detail", args=[self.cliente.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historial de alquileres")
        self.assertContains(response, self.pelicula.titulo)

    def test_pelicula_detail_view_shows_metricas(self):
        response = self.client.get(reverse("tienda:pelicula_detail", args=[self.pelicula.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Métricas")
        self.assertContains(response, "Veces alquilada")

    def _count_get_queries(self, url: str) -> int:
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
        return len(captured)

    def test_pelicula_list_avoids_n_plus_one(self):
        url = reverse("tienda:pelicula_list")
        baseline_queries = self._count_get_queries(url)

        for idx in range(10):
            Pelicula.objects.create(
                titulo=f"Pelicula extra {idx}",
                anio=2020 + (idx % 3),
                categoria=self.categoria,
                precio_alquiler=12 + idx,
                duracion_minutos=90,
                stock=3,
            )

        expanded_queries = self._count_get_queries(url)
        self.assertLessEqual(expanded_queries, baseline_queries + 1)

    def test_alquiler_list_avoids_n_plus_one(self):
        url = reverse("tienda:alquiler_list")
        baseline_queries = self._count_get_queries(url)

        for idx in range(10):
            cliente = Cliente.objects.create(
                nombre=f"Cliente extra {idx}",
                dni=f"{idx:08d}",
                email=f"extra{idx}@example.com",
            )
            pelicula = Pelicula.objects.create(
                titulo=f"Alquiler extra {idx}",
                anio=2018 + (idx % 5),
                categoria=self.categoria,
                precio_alquiler=15 + idx,
                duracion_minutos=100,
                stock=2,
            )
            Alquiler.objects.create(
                cliente=cliente,
                pelicula=pelicula,
                fecha_alquiler=timezone.localdate(),
                pagado=bool(idx % 2),
            )

        expanded_queries = self._count_get_queries(url)
        self.assertLessEqual(expanded_queries, baseline_queries + 1)

    def test_ventas_list_avoids_n_plus_one(self):
        url = reverse("tienda:ventas_list")
        baseline_queries = self._count_get_queries(url)

        for idx in range(10):
            cliente = Cliente.objects.create(
                nombre=f"Cliente venta {idx}",
                dni=f"{1000 + idx:08d}",
                email=f"venta{idx}@example.com",
            )
            pelicula = Pelicula.objects.create(
                titulo=f"Venta extra {idx}",
                anio=2015 + (idx % 7),
                categoria=self.categoria,
                precio_alquiler=20 + idx,
                duracion_minutos=95,
                stock=2,
            )
            Alquiler.objects.create(
                cliente=cliente,
                pelicula=pelicula,
                fecha_alquiler=timezone.localdate(),
                pagado=True,
                fecha_devolucion=timezone.localdate(),
            )

        expanded_queries = self._count_get_queries(url)
        self.assertLessEqual(expanded_queries, baseline_queries + 1)

    def test_cliente_import_csv_creates_and_updates(self):
        self.client.login(username="admin", password="testpassword")
        csv_content = (
            "nombre,dni,email,telefono\n"
            "Nuevo Cliente,87651234,nuevo@example.com,999111222\n"
            "Cliente Editado,12345678,editado@example.com,988776655\n"
        )
        csv_file = SimpleUploadedFile(
            "clientes.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("tienda:cliente_import_csv"),
            {
                "csv_file": csv_file,
                "actualizar_existentes": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Importación completada")
        self.assertTrue(Cliente.objects.filter(dni="87651234", nombre="Nuevo Cliente").exists())
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.nombre, "Cliente Editado")
        self.assertEqual(self.cliente.email, "editado@example.com")

    def test_cliente_export_csv_returns_expected_header(self):
        self.client.login(username="admin", password="testpassword")
        response = self.client.get(reverse("tienda:cliente_export_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn('filename="clientes.csv"', response["Content-Disposition"])

        content = response.content.decode("utf-8")
        rows = list(csv.reader(StringIO(content)))
        self.assertEqual(rows[0], ["nombre", "dni", "email", "telefono"])
        self.assertIn(
            [
                self.cliente.nombre,
                self.cliente.dni,
                self.cliente.email,
                self.cliente.telefono,
            ],
            rows[1:],
        )

    def test_cliente_import_csv_rejects_invalid_rows(self):
        self.client.login(username="admin", password="testpassword")
        csv_content = (
            "nombre,dni,email\n"
            ",1234,error@example.com\n"
        )
        csv_file = SimpleUploadedFile(
            "clientes.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        response = self.client.post(
            reverse("tienda:cliente_import_csv"),
            {
                "csv_file": csv_file,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Se encontraron errores en el CSV")
        self.assertContains(response, "el nombre es obligatorio")

    def test_pelicula_actualizar_precios_lote(self):
        self.client.login(username="admin", password="testpassword")
        pelicula_a = Pelicula.objects.create(
            titulo="Lote A",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=8.00,
            duracion_minutos=95,
            stock=3,
        )
        pelicula_b = Pelicula.objects.create(
            titulo="Lote B",
            anio=2022,
            categoria=self.categoria,
            precio_alquiler=9.00,
            duracion_minutos=105,
            stock=3,
        )

        response = self.client.post(
            reverse("tienda:pelicula_actualizar_precios_lote"),
            {
                "categoria": self.categoria.pk,
                "nuevo_precio": "19.50",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Actualización completada")
        pelicula_a.refresh_from_db()
        pelicula_b.refresh_from_db()
        self.assertEqual(pelicula_a.precio_alquiler, pelicula_b.precio_alquiler)
        self.assertEqual(float(pelicula_a.precio_alquiler), 19.5)


class AlquilerConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        categoria = Categoria.objects.create(nombre="Concurrencia")
        pelicula = Pelicula.objects.create(
            titulo="Concurrent Movie",
            anio=2020,
            categoria=categoria,
            precio_alquiler=10.00,
            duracion_minutos=90,
            stock=3,
        )
        cliente = Cliente.objects.create(
            nombre="Cliente Concurrency",
            dni="90909090",
            email="cc@example.com",
        )
        self.metodo = MetodoPago.objects.create(nombre="Yape")
        self.alquiler = Alquiler.objects.create(
            cliente=cliente,
            pelicula=pelicula,
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )

    def test_mark_paid_is_safe_with_stale_instances(self):
        stale_a = Alquiler.objects.get(pk=self.alquiler.pk)
        stale_b = Alquiler.objects.get(pk=self.alquiler.pk)

        stale_a.marcar_pagado(metodo_pago=self.metodo)
        stale_b.marcar_pagado(metodo_pago=self.metodo)

        final = Alquiler.objects.get(pk=self.alquiler.pk)
        self.assertTrue(final.pagado)
        self.assertEqual(final.estado, Alquiler.ESTADO_PAGADO)
        self.assertEqual(
            ActionAudit.objects.filter(objeto_id=final.pk, accion="alquiler_pagado").count(),
            1,
        )
        self.assertEqual(
            EventoDominio.objects.filter(referencia_id=final.pk, evento="alquiler_pagado").count(),
            1,
        )


class ModelValidationTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.categoria_activa = Categoria.objects.create(nombre="Categoria valida")
        self.categoria_inactiva = Categoria.objects.create(
            nombre="Categoria inactiva",
            is_active=False,
        )
        self.cliente_activo = Cliente.objects.create(
            nombre="Cliente activo",
            dni="11112222",
            email="cliente-activo@example.com",
        )
        self.cliente_inactivo = Cliente.objects.create(
            nombre="Cliente inactivo",
            dni="33334444",
            email="cliente-inactivo@example.com",
            is_active=False,
        )
        self.metodo_activo = MetodoPago.objects.create(nombre="Tarjeta")
        self.metodo_inactivo = MetodoPago.objects.create(
            nombre="Metodo bloqueado",
            is_active=False,
        )
        self.pelicula_activa = Pelicula.objects.create(
            titulo="Pelicula valida",
            anio=2020,
            categoria=self.categoria_activa,
            precio_alquiler=Decimal("12.00"),
            duracion_minutos=100,
            stock=2,
        )
        self.pelicula_inactiva = Pelicula.objects.create(
            titulo="Pelicula inactiva",
            anio=2021,
            categoria=self.categoria_activa,
            precio_alquiler=Decimal("9.00"),
            duracion_minutos=95,
            stock=2,
            is_active=False,
        )
        self.pelicula_categoria_inactiva = Pelicula.objects.create(
            titulo="Pelicula categoria inactiva",
            anio=2022,
            categoria=self.categoria_inactiva,
            precio_alquiler=Decimal("11.00"),
            duracion_minutos=90,
            stock=2,
        )

    def assertValidationMessage(self, action, expected_message):
        with self.assertRaises(ValidationError) as context:
            action()
        self.assertIn(expected_message, context.exception.messages)

    def test_cliente_dni_validator_rejects_short_value(self):
        cliente = Cliente(nombre="Cliente corto", dni="1234")

        with self.assertRaises(ValidationError) as context:
            cliente.full_clean()

        self.assertIn("dni", context.exception.message_dict)

    def test_pelicula_field_validators_reject_invalid_values(self):
        pelicula = Pelicula(
            titulo="Pelicula invalida",
            slug="pelicula-invalida",
            anio=1899,
            categoria=self.categoria_activa,
            precio_alquiler=Decimal("-1.00"),
            duracion_minutos=0,
            stock=-1,
        )

        with self.assertRaises(ValidationError) as context:
            pelicula.full_clean()

        self.assertIn("anio", context.exception.message_dict)
        self.assertIn("precio_alquiler", context.exception.message_dict)
        self.assertIn("duracion_minutos", context.exception.message_dict)
        self.assertIn("stock", context.exception.message_dict)

    def test_pelicula_rejects_duplicate_title_and_year(self):
        duplicate = Pelicula(
            titulo=self.pelicula_activa.titulo,
            slug="pelicula-valida-duplicada",
            anio=self.pelicula_activa.anio,
            categoria=self.categoria_activa,
            precio_alquiler=Decimal("14.00"),
            duracion_minutos=105,
            stock=1,
        )

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn("__all__", context.exception.message_dict)

    def test_alquiler_rejects_inactive_cliente(self):
        alquiler = Alquiler(
            cliente=self.cliente_inactivo,
            pelicula=self.pelicula_activa,
            fecha_alquiler=self.today,
        )

        self.assertValidationMessage(
            alquiler.full_clean,
            "No se puede registrar alquiler para un cliente inactivo.",
        )

    def test_alquiler_rejects_inactive_pelicula(self):
        alquiler = Alquiler(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_inactiva,
            fecha_alquiler=self.today,
        )

        self.assertValidationMessage(
            alquiler.full_clean,
            "No se puede registrar alquiler para una película inactiva.",
        )

    def test_alquiler_rejects_inactive_categoria(self):
        alquiler = Alquiler(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_categoria_inactiva,
            fecha_alquiler=self.today,
        )

        self.assertValidationMessage(
            alquiler.full_clean,
            "No se puede registrar alquiler para una película con categoría inactiva.",
        )

    def test_alquiler_rejects_inactive_metodo_pago(self):
        alquiler = Alquiler(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_activa,
            fecha_alquiler=self.today,
            metodo_pago=self.metodo_inactivo,
        )

        self.assertValidationMessage(
            alquiler.full_clean,
            "No se puede usar un método de pago inactivo.",
        )

    def test_alquiler_rejects_fecha_devolucion_before_fecha_alquiler(self):
        alquiler = Alquiler(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_activa,
            fecha_alquiler=self.today,
            fecha_devolucion=self.today - datetime.timedelta(days=1),
        )

        self.assertValidationMessage(
            alquiler.full_clean,
            "La fecha de devolución no puede ser anterior a la fecha de alquiler.",
        )

    def test_alquiler_rejects_duplicate_cliente_pelicula_fecha(self):
        Alquiler.objects.create(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_activa,
            fecha_alquiler=self.today,
            pagado=False,
        )
        duplicate = Alquiler(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_activa,
            fecha_alquiler=self.today,
            pagado=False,
        )

        self.assertValidationMessage(
            duplicate.full_clean,
            "Ya existe un alquiler para este cliente, película y fecha.",
        )

    def test_alquiler_rejects_paid_rental_when_daily_cash_is_closed(self):
        CajaDiaria.objects.create(fecha=self.today, cerrada_por="admin")
        alquiler = Alquiler(
            cliente=self.cliente_activo,
            pelicula=self.pelicula_activa,
            fecha_alquiler=self.today,
            fecha_pago=self.today,
            pagado=True,
            metodo_pago=self.metodo_activo,
        )

        self.assertValidationMessage(
            alquiler.full_clean,
            "La caja diaria está cerrada. No se pueden registrar ventas de hoy.",
        )

    def test_alquiler_rejects_creation_without_stock(self):
        pelicula_sin_stock = Pelicula.objects.create(
            titulo="Pelicula sin stock",
            anio=2023,
            categoria=self.categoria_activa,
            precio_alquiler=Decimal("8.00"),
            duracion_minutos=85,
            stock=0,
        )
        alquiler = Alquiler(
            cliente=self.cliente_activo,
            pelicula=pelicula_sin_stock,
            fecha_alquiler=self.today,
            pagado=False,
        )

        self.assertValidationMessage(
            alquiler.save,
            'La película "Pelicula sin stock" no tiene stock disponible.',
        )


class FormValidationTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.categoria = Categoria.objects.create(nombre="Accion")
        self.categoria_vacia = Categoria.objects.create(nombre="Vacia")
        self.categoria_inactiva = Categoria.objects.create(
            nombre="Categoria filtrada",
            is_active=False,
        )
        self.cliente = Cliente.objects.create(
            nombre="Cliente formulario",
            dni="55556666",
            email="cliente-form@example.com",
        )
        self.cliente_inactivo = Cliente.objects.create(
            nombre="Cliente excluido",
            dni="77778888",
            email="cliente-excluido@example.com",
            is_active=False,
        )
        self.pelicula = Pelicula.objects.create(
            titulo="Pelicula formulario",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=Decimal("15.00"),
            duracion_minutos=110,
            stock=2,
        )
        self.pelicula_sin_stock = Pelicula.objects.create(
            titulo="Pelicula sin stock formulario",
            anio=2022,
            categoria=self.categoria,
            precio_alquiler=Decimal("18.00"),
            duracion_minutos=95,
            stock=0,
        )
        self.metodo_pago = MetodoPago.objects.create(nombre="Yape")
        self.metodo_inactivo = MetodoPago.objects.create(
            nombre="Plin archivado",
            is_active=False,
        )
        self.alquiler = Alquiler.objects.create(
            cliente=self.cliente,
            pelicula=self.pelicula,
            fecha_alquiler=self.today,
            pagado=False,
        )

    def test_categoria_form_accepts_unique_name_and_rejects_duplicate(self):
        valid_form = CategoriaForm(
            data={"nombre": "Documental", "descripcion": "Categoria nueva"}
        )
        invalid_form = CategoriaForm(
            data={"nombre": self.categoria.nombre, "descripcion": "Duplicada"}
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("nombre", invalid_form.errors)

    def test_cliente_form_accepts_valid_data_and_rejects_short_dni(self):
        valid_form = ClienteForm(
            data={
                "nombre": "Cliente valido",
                "dni": "99990000",
                "email": "cliente-valido@example.com",
                "telefono": "999888777",
            }
        )
        invalid_form = ClienteForm(
            data={
                "nombre": "Cliente invalido",
                "dni": "1234567",
                "email": "cliente-invalido@example.com",
                "telefono": "111222333",
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("dni", invalid_form.errors)

    @override_settings(PELICULA_PRECIO_MINIMO=15)
    def test_pelicula_form_accepts_valid_data_and_rejects_invalid_cases(self):
        valid_form = PeliculaForm(
            data={
                "titulo": "Nueva pelicula",
                "director": "Directora",
                "pais_origen": "PE",
                "anio": self.today.year,
                "categoria": self.categoria.pk,
                "precio_alquiler": "20.00",
                "duracion_minutos": 100,
                "stock": 3,
            }
        )
        invalid_year_form = PeliculaForm(
            data={
                "titulo": "Pelicula futura",
                "director": "Director",
                "pais_origen": "PE",
                "anio": self.today.year + 1,
                "categoria": self.categoria.pk,
                "precio_alquiler": "20.00",
                "duracion_minutos": 100,
                "stock": 3,
            }
        )
        invalid_price_form = PeliculaForm(
            data={
                "titulo": "Pelicula barata",
                "director": "Director",
                "pais_origen": "PE",
                "anio": self.today.year,
                "categoria": self.categoria.pk,
                "precio_alquiler": "10.00",
                "duracion_minutos": 100,
                "stock": 3,
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_year_form.is_valid())
        self.assertIn("anio", invalid_year_form.errors)
        self.assertFalse(invalid_price_form.is_valid())
        self.assertIn("precio_alquiler", invalid_price_form.errors)

    def test_pelicula_form_rejects_blank_title_after_strip(self):
        form = PeliculaForm(
            data={
                "titulo": "   ",
                "director": "Directora",
                "pais_origen": "PE",
                "anio": self.today.year,
                "categoria": self.categoria.pk,
                "precio_alquiler": "20.00",
                "duracion_minutos": 100,
                "stock": 3,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("titulo", form.errors)

    def test_pelicula_filter_form_accepts_valid_range_and_rejects_invalid_range(self):
        valid_form = PeliculaFilterForm(
            data={
                "anio": 2021,
                "categoria": self.categoria.pk,
                "precio_min": "10.00",
                "precio_max": "20.00",
            }
        )
        invalid_form = PeliculaFilterForm(
            data={
                "precio_min": "25.00",
                "precio_max": "10.00",
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("El precio mínimo no puede ser mayor al precio máximo.", invalid_form.non_field_errors())

    def test_alquiler_create_form_accepts_valid_choices_and_rejects_filtered_ones(self):
        cliente_valido = Cliente.objects.create(
            nombre="Cliente disponible",
            dni="12121212",
            email="cliente-disponible@example.com",
        )
        valid_form = AlquilerCreateForm(
            data={
                "cliente": cliente_valido.pk,
                "pelicula": self.pelicula.pk,
            }
        )
        invalid_form = AlquilerCreateForm(
            data={
                "cliente": self.cliente_inactivo.pk,
                "pelicula": self.pelicula_sin_stock.pk,
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("cliente", invalid_form.errors)
        self.assertIn("pelicula", invalid_form.errors)

    def test_alquiler_advanced_search_form_accepts_valid_filters_and_rejects_invalid_ranges(self):
        valid_form = AlquilerAdvancedSearchForm(
            data={
                "cliente": self.cliente.pk,
                "pelicula": self.pelicula.pk,
                "categoria": self.categoria.pk,
                "estado": Alquiler.ESTADO_PENDIENTE,
                "fecha_desde": (self.today - datetime.timedelta(days=5)).isoformat(),
                "fecha_hasta": self.today.isoformat(),
                "precio_min": "10.00",
                "precio_max": "20.00",
                "solo_vencidos": "on",
            }
        )
        invalid_date_form = AlquilerAdvancedSearchForm(
            data={
                "fecha_desde": self.today.isoformat(),
                "fecha_hasta": (self.today - datetime.timedelta(days=1)).isoformat(),
            }
        )
        invalid_price_form = AlquilerAdvancedSearchForm(
            data={
                "precio_min": "50.00",
                "precio_max": "20.00",
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_date_form.is_valid())
        self.assertIn(
            "La fecha desde no puede ser posterior a la fecha hasta.",
            invalid_date_form.non_field_errors(),
        )
        self.assertFalse(invalid_price_form.is_valid())
        self.assertIn(
            "El precio mínimo no puede ser mayor al precio máximo.",
            invalid_price_form.non_field_errors(),
        )

    def test_cobro_masivo_form_accepts_valid_ids_and_rejects_invalid_ids(self):
        valid_form = CobroMasivoForm(
            data={
                "ids": "1, 2 2,3",
                "metodo_pago": self.metodo_pago.pk,
                "fecha_devolucion": self.today.isoformat(),
            }
        )
        invalid_form = CobroMasivoForm(
            data={
                "ids": "1, dos, 3",
                "metodo_pago": self.metodo_pago.pk,
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertEqual(valid_form.cleaned_data["ids"], [1, 2, 3])
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("ids", invalid_form.errors)

    def test_cliente_csv_import_form_accepts_valid_csv_and_rejects_invalid_files(self):
        valid_file = SimpleUploadedFile(
            "clientes.csv",
            b"nombre,dni,email,telefono\nNuevo,87654321,nuevo@example.com,999888777\n",
            content_type="text/csv",
        )
        invalid_headers_file = SimpleUploadedFile(
            "clientes.csv",
            b"nombre,email\nSinDni,sin-dni@example.com\n",
            content_type="text/csv",
        )

        valid_form = ClienteCSVImportForm(
            data={"actualizar_existentes": "on"},
            files={"csv_file": valid_file},
        )
        invalid_form = ClienteCSVImportForm(files={"csv_file": invalid_headers_file})

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("csv_file", invalid_form.errors)

    @override_settings(PELICULA_PRECIO_MINIMO=15)
    def test_categoria_precio_lote_form_accepts_valid_data_and_rejects_invalid_cases(self):
        valid_form = CategoriaPrecioLoteForm(
            data={
                "categoria": self.categoria.pk,
                "nuevo_precio": "20.00",
            }
        )
        invalid_empty_category_form = CategoriaPrecioLoteForm(
            data={
                "categoria": self.categoria_vacia.pk,
                "nuevo_precio": "20.00",
            }
        )
        invalid_price_form = CategoriaPrecioLoteForm(
            data={
                "categoria": self.categoria.pk,
                "nuevo_precio": "10.00",
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_empty_category_form.is_valid())
        self.assertIn("categoria", invalid_empty_category_form.errors)
        self.assertFalse(invalid_price_form.is_valid())
        self.assertIn("nuevo_precio", invalid_price_form.errors)

    def test_marcar_pagado_form_accepts_valid_date_and_rejects_past_date(self):
        valid_form = MarcarPagadoForm(
            data={
                "metodo_pago": self.metodo_pago.pk,
                "fecha_devolucion": self.today.isoformat(),
            },
            alquiler=self.alquiler,
        )
        invalid_form = MarcarPagadoForm(
            data={
                "metodo_pago": self.metodo_pago.pk,
                "fecha_devolucion": (self.today - datetime.timedelta(days=1)).isoformat(),
            },
            alquiler=self.alquiler,
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("fecha_devolucion", invalid_form.errors)

    def test_ventas_filter_form_accepts_valid_range_and_rejects_invalid_range(self):
        valid_form = VentasFilterForm(
            data={
                "desde": (self.today - datetime.timedelta(days=7)).isoformat(),
                "hasta": self.today.isoformat(),
            }
        )
        invalid_form = VentasFilterForm(
            data={
                "desde": self.today.isoformat(),
                "hasta": (self.today - datetime.timedelta(days=1)).isoformat(),
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn(
            "La fecha 'Desde' no puede ser posterior a 'Hasta'.",
            invalid_form.non_field_errors(),
        )

    def test_simular_ventas_form_accepts_blank_range_and_rejects_invalid_range(self):
        valid_form = SimularVentasForm(data={"numero_ventas": 3})
        invalid_form = SimularVentasForm(
            data={
                "numero_ventas": 3,
                "desde": self.today.isoformat(),
                "hasta": (self.today - datetime.timedelta(days=1)).isoformat(),
            }
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertEqual(valid_form.cleaned_data["desde"], datetime.date.today())
        self.assertEqual(valid_form.cleaned_data["hasta"], datetime.date.today())
        self.assertFalse(invalid_form.is_valid())
        self.assertIn(
            "La fecha 'Desde' no puede ser posterior a 'Hasta'.",
            invalid_form.non_field_errors(),
        )

    def test_metodo_pago_form_accepts_unique_name_and_rejects_duplicate(self):
        valid_form = MetodoPagoForm(
            data={"nombre": "Transferencia", "descripcion": "Banco"}
        )
        invalid_form = MetodoPagoForm(
            data={"nombre": self.metodo_pago.nombre, "descripcion": "Duplicado"}
        )

        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("nombre", invalid_form.errors)


class FixtureLoadTests(TestCase):
    fixtures = ["initial_test_data.json"]

    def test_initial_fixture_loads_expected_domain_data(self):
        self.assertTrue(Categoria.objects.filter(nombre="Fixture Accion", is_active=True).exists())
        self.assertTrue(Cliente.objects.filter(dni="80808080", is_active=True).exists())
        self.assertTrue(MetodoPago.objects.filter(nombre="Fixture Efectivo", is_active=True).exists())
        self.assertTrue(
            Pelicula.objects.filter(
                slug="fixture-pelicula-principal",
                categoria__nombre="Fixture Accion",
                stock=3,
                is_active=True,
            ).exists()
        )


class AlquilerVentaIntegrationTests(TestCase):
    fixtures = ["initial_test_data.json"]

    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin_integracion",
            email="admin-integracion@example.com",
            password="testpassword",
        )
        self.client.force_login(self.admin_user)
        self.cliente = Cliente.objects.get(dni="80808080")
        self.pelicula = Pelicula.objects.get(slug="fixture-pelicula-principal")
        self.metodo_pago = MetodoPago.objects.get(nombre="Fixture Efectivo")

    def test_create_rental_then_pay_and_see_it_listed_as_sale(self):
        initial_stock = self.pelicula.stock

        create_response = self.client.post(
            reverse("tienda:alquiler_create"),
            {
                "cliente": self.cliente.pk,
                "pelicula": self.pelicula.pk,
            },
        )
        self.assertEqual(create_response.status_code, 302)

        alquiler = Alquiler.objects.get(
            cliente=self.cliente,
            pelicula=self.pelicula,
            fecha_alquiler=timezone.localdate(),
        )
        self.assertEqual(alquiler.estado, Alquiler.ESTADO_PENDIENTE)
        self.assertFalse(alquiler.pagado)
        self.assertEqual(alquiler.precio, self.pelicula.precio_alquiler)
        self.pelicula.refresh_from_db()
        self.assertEqual(self.pelicula.stock, initial_stock - 1)
        self.assertTrue(
            ActionAudit.objects.filter(
                objeto_id=alquiler.pk,
                accion="alquiler_creado",
                entidad="alquiler",
            ).exists()
        )

        pay_response = self.client.post(
            reverse("tienda:alquiler_marcar_pagado", args=[alquiler.pk]),
            {
                "fecha_devolucion": timezone.localdate().isoformat(),
                "metodo_pago": self.metodo_pago.pk,
            },
        )
        self.assertEqual(pay_response.status_code, 302)

        alquiler.refresh_from_db()
        self.assertTrue(alquiler.pagado)
        self.assertEqual(alquiler.estado, Alquiler.ESTADO_PAGADO)
        self.assertEqual(alquiler.metodo_pago, self.metodo_pago)
        self.assertEqual(alquiler.fecha_pago, timezone.localdate())
        self.assertTrue(
            EventoDominio.objects.filter(
                referencia_id=alquiler.pk,
                evento="alquiler_pagado",
                entidad="alquiler",
            ).exists()
        )

        sales_response = self.client.get(reverse("tienda:ventas_list"))
        self.assertEqual(sales_response.status_code, 200)
        self.assertContains(sales_response, self.cliente.nombre)
        self.assertContains(sales_response, self.pelicula.titulo)
        self.assertContains(sales_response, "Total de ventas por día")
        self.assertIn(alquiler.pk, {venta.pk for venta in sales_response.context["ventas"]})
        self.assertEqual(sales_response.context["total_ingresos"], alquiler.precio)


class SeedDataCommandTests(TestCase):
    def test_seed_data_command_creates_requested_records(self):
        out = StringIO()

        call_command("seed_data", clientes=2, peliculas=3, stdout=out)

        self.assertEqual(Cliente.objects.filter(nombre__startswith="Cliente Seed ").count(), 2)
        self.assertEqual(Pelicula.objects.filter(titulo__startswith="Pelicula Seed ").count(), 3)
        self.assertGreaterEqual(Categoria.objects.count(), 4)
        self.assertGreaterEqual(MetodoPago.objects.count(), 3)
        self.assertIn("clientes=2, peliculas=3", out.getvalue())

    def test_seed_data_command_rejects_empty_request(self):
        with self.assertRaises(CommandError):
            call_command("seed_data", clientes=0, peliculas=0)

    def test_clean_test_rentals_command_deletes_seed_rentals_and_restores_stock(self):
        call_command("seed_data", clientes=1, peliculas=1, stdout=StringIO())
        cliente_seed = Cliente.objects.get(nombre="Cliente Seed 1")
        pelicula_seed = Pelicula.objects.get(titulo="Pelicula Seed 1")
        stock_inicial = pelicula_seed.stock

        alquiler = Alquiler.objects.create(
            cliente=cliente_seed,
            pelicula=pelicula_seed,
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )
        pelicula_seed.refresh_from_db()
        self.assertEqual(pelicula_seed.stock, stock_inicial - 1)

        out = StringIO()
        call_command("clean_test_rentals", stdout=out)

        pelicula_seed.refresh_from_db()
        self.assertFalse(Alquiler.objects.filter(pk=alquiler.pk).exists())
        self.assertEqual(pelicula_seed.stock, stock_inicial)
        self.assertIn("alquileres_eliminados=1", out.getvalue())

    def test_clean_test_rentals_command_dry_run_keeps_data(self):
        call_command("seed_data", clientes=1, peliculas=1, stdout=StringIO())
        cliente_seed = Cliente.objects.get(nombre="Cliente Seed 1")
        pelicula_seed = Pelicula.objects.get(titulo="Pelicula Seed 1")
        alquiler = Alquiler.objects.create(
            cliente=cliente_seed,
            pelicula=pelicula_seed,
            fecha_alquiler=timezone.localdate(),
            pagado=False,
        )

        out = StringIO()
        call_command("clean_test_rentals", dry_run=True, stdout=out)

        self.assertTrue(Alquiler.objects.filter(pk=alquiler.pk).exists())
        self.assertIn("Dry-run", out.getvalue())

    def test_backup_sqlite_command_copies_file_with_timestamp(self):
        with TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "db.sqlite3"
            source_content = b"sqlite-backup-test"
            source_path.write_bytes(source_content)
            out = StringIO()

            call_command(
                "backup_sqlite",
                source=str(source_path),
                output_dir=temp_dir,
                stdout=out,
            )

            backup_files = sorted(Path(temp_dir).glob("db-*.sqlite3"))
            self.assertEqual(len(backup_files), 1)
            self.assertEqual(backup_files[0].read_bytes(), source_content)
            self.assertIn("Backup creado:", out.getvalue())

    def test_backup_sqlite_command_rejects_missing_source(self):
        with TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.sqlite3"
            with self.assertRaises(CommandError):
                call_command("backup_sqlite", source=str(missing_path), stdout=StringIO())

    def test_restore_sqlite_command_restores_file_after_confirmation(self):
        with TemporaryDirectory() as temp_dir:
            backup_path = Path(temp_dir) / "backup.sqlite3"
            target_path = Path(temp_dir) / "target.sqlite3"
            backup_content = b"sqlite-restored-content"
            target_path.write_bytes(b"old-content")
            backup_path.write_bytes(backup_content)
            out = StringIO()

            with patch("builtins.input", return_value="RESTORE"):
                call_command(
                    "restore_sqlite",
                    backup=str(backup_path),
                    target=str(target_path),
                    stdout=out,
                )

            self.assertEqual(target_path.read_bytes(), backup_content)
            self.assertIn("Base restaurada en:", out.getvalue())

    def test_restore_sqlite_command_requires_confirmation(self):
        with TemporaryDirectory() as temp_dir:
            backup_path = Path(temp_dir) / "backup.sqlite3"
            target_path = Path(temp_dir) / "target.sqlite3"
            original_content = b"keep-me"
            target_path.write_bytes(original_content)
            backup_path.write_bytes(b"new-content")

            with patch("builtins.input", return_value="NO"):
                with self.assertRaises(CommandError):
                    call_command(
                        "restore_sqlite",
                        backup=str(backup_path),
                        target=str(target_path),
                        stdout=StringIO(),
                    )

            self.assertEqual(target_path.read_bytes(), original_content)


class LoggingConfigurationTests(TestCase):
    def test_rotating_error_log_handler_is_configured(self):
        logging_config = settings.LOGGING
        error_handler = logging_config["handlers"]["error_file"]

        self.assertEqual(
            error_handler["class"],
            "logging.handlers.RotatingFileHandler",
        )
        self.assertEqual(error_handler["level"], "ERROR")
        self.assertEqual(error_handler["formatter"], "verbose")
        self.assertTrue(error_handler["filename"].endswith("errors.log"))
        self.assertGreater(error_handler["maxBytes"], 0)
        self.assertGreaterEqual(error_handler["backupCount"], 1)
        self.assertTrue(Path(error_handler["filename"]).parent.exists())


class CustomSystemChecksTests(TestCase):
    def _tienda_check_ids(self):
        return [check.id for check in run_checks() if check.id.startswith("tienda.")]

    def test_default_configuration_passes_custom_checks(self):
        self.assertEqual(self._tienda_check_ids(), [])

    def test_negative_minimum_price_is_reported(self):
        with override_settings(PELICULA_PRECIO_MINIMO=-1):
            self.assertIn("tienda.E001", self._tienda_check_ids())

    def test_missing_session_security_middleware_is_reported(self):
        middleware = [
            item for item in settings.MIDDLEWARE if item != "tienda.middleware.SessionSecurityMiddleware"
        ]
        with override_settings(
            MIDDLEWARE=middleware,
            FORCE_INITIAL_PASSWORD_CHANGE=True,
            SESSION_IDLE_TIMEOUT_SECONDS=1800,
        ):
            self.assertIn("tienda.E002", self._tienda_check_ids())

    def test_invalid_logging_handler_is_reported(self):
        with override_settings(
            LOGGING={
                "version": 1,
                "handlers": {
                    "error_file": {
                        "class": "logging.FileHandler",
                        "filename": "",
                        "maxBytes": 0,
                        "backupCount": 0,
                    }
                },
            }
        ):
            check_ids = self._tienda_check_ids()
            self.assertIn("tienda.E004", check_ids)
            self.assertIn("tienda.E005", check_ids)
            self.assertIn("tienda.E007", check_ids)
            self.assertIn("tienda.E008", check_ids)


class ReportedBugRegressionTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.categoria = Categoria.objects.create(nombre="Regression")
        self.cliente_activo = Cliente.objects.create(
            nombre="Cliente Regression",
            dni="70001111",
            email="regression@example.com",
        )
        self.cliente_inactivo = Cliente.objects.create(
            nombre="Cliente Inactivo Regression",
            dni="70002222",
            email="regression-inactivo@example.com",
            is_active=False,
        )
        self.pelicula_activa = Pelicula.objects.create(
            titulo="Pelicula Regression",
            anio=2021,
            categoria=self.categoria,
            precio_alquiler=Decimal("13.50"),
            duracion_minutos=95,
            stock=2,
        )
        self.pelicula_sin_stock = Pelicula.objects.create(
            titulo="Pelicula Sin Stock Regression",
            anio=2022,
            categoria=self.categoria,
            precio_alquiler=Decimal("11.00"),
            duracion_minutos=100,
            stock=0,
        )
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin_regression",
            email="admin-regression@example.com",
            password="testpassword",
        )
        self.client.force_login(self.admin_user)

    def test_alquiler_create_view_invalid_filtered_choices_returns_form_errors(self):
        response = self.client.post(
            reverse("tienda:alquiler_create"),
            {
                "cliente": self.cliente_inactivo.pk,
                "pelicula": self.pelicula_sin_stock.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("cliente", response.context["form"].errors)
        self.assertIn("pelicula", response.context["form"].errors)
        self.assertEqual(Alquiler.objects.count(), 0)

    def test_simular_ventas_single_end_date_returns_response_without_crash(self):
        response = self.client.post(
            reverse("tienda:ventas_simular"),
            {
                "numero_ventas": 1,
                "desde": "",
                "hasta": self.today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumen de simulación")

    def test_invalid_csv_import_does_not_create_partial_records(self):
        csv_file = SimpleUploadedFile(
            "clientes.csv",
            (
                "nombre,dni,email\n"
                "Cliente Valido,87654321,valido@example.com\n"
                ",1234,invalido@example.com\n"
            ).encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("tienda:cliente_import_csv"),
            {
                "csv_file": csv_file,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Se encontraron errores en el CSV")
        self.assertFalse(Cliente.objects.filter(dni="87654321").exists())

