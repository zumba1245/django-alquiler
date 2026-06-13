from django.conf import settings
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F
from django.utils.text import slugify
from django.utils import timezone


class Categoria(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    descripcion = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class Cliente(models.Model):
    nombre = models.CharField(max_length=120)
    dni = models.CharField(
        max_length=8,
        unique=True,
        verbose_name="DNI",
        validators=[MinLengthValidator(8)],
    )
    email = models.EmailField(blank=True, null=True, unique=True)
    telefono = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.nombre


class Pelicula(models.Model):
    titulo = models.CharField(max_length=200)
    slug = models.SlugField(max_length=240, unique=True)
    director = models.CharField(max_length=120, blank=True, default="")
    pais_origen = models.CharField(max_length=80, blank=True, default="")
    anio = models.PositiveIntegerField(validators=[MinValueValidator(1900)], verbose_name="Año")
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="peliculas")
    precio_alquiler = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    duracion_minutos = models.PositiveIntegerField(
        default=90,
        validators=[MinValueValidator(1)],
        verbose_name="Duración (minutos)",
        help_text="Duración en minutos.",
    )
    stock = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["titulo", "anio"]
        unique_together = [("titulo", "anio")]

    def __str__(self) -> str:
        return f"{self.titulo} ({self.anio})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.titulo)[:220] or "pelicula"
            candidate = base_slug
            counter = 2
            while Pelicula.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                suffix = f"-{counter}"
                candidate = f"{base_slug[: 240 - len(suffix)]}{suffix}"
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class MetodoPago(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    descripcion = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Método de pago"
        verbose_name_plural = "Métodos de pago"

    def __str__(self) -> str:
        return self.nombre


class Alquiler(models.Model):
    ESTADO_PENDIENTE = "pendiente"
    ESTADO_PAGADO = "pagado"
    ESTADO_ANULADO = "anulado"
    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_PAGADO, "Pagado"),
        (ESTADO_ANULADO, "Anulado"),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="alquileres")
    pelicula = models.ForeignKey(Pelicula, on_delete=models.PROTECT, related_name="alquileres")

    # Usamos default para que la simulación pueda fijar fechas explícitas.
    fecha_alquiler = models.DateField(default=timezone.localdate)
    fecha_pago = models.DateField(blank=True, null=True)
    fecha_devolucion = models.DateField(blank=True, null=True)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    pagado = models.BooleanField(default=False)
    metodo_pago = models.ForeignKey(
        MetodoPago,
        on_delete=models.SET_NULL,
        related_name="alquileres",
        blank=True,
        null=True,
    )

    # Guardamos el precio en el momento del alquiler para que no cambie si cambia la película.
    precio = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)

    class Meta:
        ordering = ["-fecha_alquiler", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["cliente", "pelicula", "fecha_alquiler"],
                name="uq_alquiler_cliente_pelicula_fecha",
            )
        ]

    def __str__(self) -> str:
        return f"Alquiler: {self.pelicula} - {self.cliente}"

    def clean(self):
        errors = []

        if self.cliente_id and not self.cliente.is_active:
            errors.append("No se puede registrar alquiler para un cliente inactivo.")
        if self.pelicula_id:
            if not self.pelicula.is_active:
                errors.append("No se puede registrar alquiler para una película inactiva.")
            if not self.pelicula.categoria.is_active:
                errors.append("No se puede registrar alquiler para una película con categoría inactiva.")
        if self.metodo_pago_id and not self.metodo_pago.is_active:
            errors.append("No se puede usar un método de pago inactivo.")

        if self.fecha_devolucion and self.fecha_devolucion < self.fecha_alquiler:
            errors.append("La fecha de devolución no puede ser anterior a la fecha de alquiler.")
        if self.cliente_id and self.pelicula_id and self.fecha_alquiler:
            duplicate_exists = Alquiler.objects.filter(
                cliente_id=self.cliente_id,
                pelicula_id=self.pelicula_id,
                fecha_alquiler=self.fecha_alquiler,
            ).exclude(pk=self.pk).exists()
            if duplicate_exists:
                errors.append("Ya existe un alquiler para este cliente, película y fecha.")
        if self.pagado:
            fecha_venta = self.fecha_pago or timezone.localdate()
            already_paid = self.pk and Alquiler.objects.filter(pk=self.pk, pagado=True).exists()
            if not already_paid and CajaDiaria.esta_cerrada(fecha_venta):
                errors.append("La caja diaria está cerrada. No se pueden registrar ventas de hoy.")

        if errors:
            raise ValidationError(errors)

    def marcar_pagado(self, fecha_devolucion=None, metodo_pago=None) -> None:
        """
        Marca el alquiler como pagado y (opcionalmente) registra la devolución.
        Esta operación es idempotente: si ya estaba pagado, no cambia el estado.
        """
        if not self.pk:
            return
        if self.pagado:
            return

        with transaction.atomic():
            locked = Alquiler.objects.select_for_update().get(pk=self.pk)
            if locked.pagado:
                self.estado = locked.estado
                self.pagado = locked.pagado
                self.fecha_pago = locked.fecha_pago
                self.metodo_pago = locked.metodo_pago
                self.fecha_devolucion = locked.fecha_devolucion
                return

            if fecha_devolucion is None:
                fecha_devolucion = timezone.localdate()

            locked.estado = self.ESTADO_PAGADO
            locked.pagado = True
            locked.fecha_pago = timezone.localdate()
            if metodo_pago is not None:
                locked.metodo_pago = metodo_pago
            locked.fecha_devolucion = fecha_devolucion
            locked.save(update_fields=["estado", "pagado", "fecha_pago", "metodo_pago", "fecha_devolucion"])

            self.estado = locked.estado
            self.pagado = locked.pagado
            self.fecha_pago = locked.fecha_pago
            self.metodo_pago = locked.metodo_pago
            self.fecha_devolucion = locked.fecha_devolucion

    def anular(self) -> None:
        """
        Marca el alquiler como anulado.
        Operación idempotente: si ya estaba anulado no cambia.
        """
        if not self.pk:
            return
        if self.estado == self.ESTADO_ANULADO:
            return
        if self.estado != self.ESTADO_PENDIENTE:
            return

        with transaction.atomic():
            locked = Alquiler.objects.select_for_update().get(pk=self.pk)
            if locked.estado != self.ESTADO_PENDIENTE:
                return

            Pelicula.objects.filter(pk=locked.pelicula_id).update(stock=F("stock") + 1)
            locked.estado = self.ESTADO_ANULADO
            locked.pagado = False
            locked.save(update_fields=["estado", "pagado"])

            self.estado = locked.estado
            self.pagado = locked.pagado
            self.pelicula.refresh_from_db(fields=["stock"])

    def save(self, *args, **kwargs):
        self.clean()
        is_new = self.pk is None

        if self.pagado and self.estado != self.ESTADO_PAGADO:
            self.estado = self.ESTADO_PAGADO
        elif self.estado == self.ESTADO_PAGADO:
            self.pagado = True
        elif self.estado in {self.ESTADO_PENDIENTE, self.ESTADO_ANULADO}:
            self.pagado = False

        if self.pagado and not self.fecha_pago:
            self.fecha_pago = timezone.localdate()
        if not self.pagado:
            self.fecha_pago = None

        if is_new:
            # Operación crítica: crear alquiler + descontar stock en una sola transacción.
            with transaction.atomic():
                pelicula_lock = Pelicula.objects.select_for_update().get(pk=self.pelicula_id)
                if pelicula_lock.stock <= 0:
                    raise ValidationError(f'La película "{pelicula_lock.titulo}" no tiene stock disponible.')

                if self.precio is None:
                    self.precio = pelicula_lock.precio_alquiler

                Pelicula.objects.filter(pk=pelicula_lock.pk).update(stock=F("stock") - 1)
                super().save(*args, **kwargs)
                self.pelicula.refresh_from_db(fields=["stock"])
            return

        # Guardar el precio actual de la película si faltaba.
        if self.precio is None and self.pelicula_id:
            self.precio = self.pelicula.precio_alquiler
        super().save(*args, **kwargs)


class LoginAttemptAudit(models.Model):
    username = models.CharField(max_length=150, blank=True, null=True)
    attempted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    path = models.CharField(max_length=200, blank=True, null=True)
    user_agent = models.CharField(max_length=300, blank=True, null=True)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "Intento de login fallido"
        verbose_name_plural = "Intentos de login fallidos"

    def __str__(self) -> str:
        return f"{self.username or 'desconocido'} - {self.attempted_at:%Y-%m-%d %H:%M:%S}"


class CajaDiaria(models.Model):
    fecha = models.DateField(unique=True)
    cerrada_en = models.DateTimeField(auto_now_add=True)
    cerrada_por = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Caja diaria"
        verbose_name_plural = "Cajas diarias"

    def __str__(self) -> str:
        return f"Caja cerrada {self.fecha:%Y-%m-%d}"

    @classmethod
    def esta_cerrada(cls, fecha) -> bool:
        return cls.objects.filter(fecha=fecha).exists()


class ActionAudit(models.Model):
    accion = models.CharField(max_length=80)
    entidad = models.CharField(max_length=80)
    objeto_id = models.PositiveIntegerField(blank=True, null=True)
    descripcion = models.CharField(max_length=255, blank=True, default="")
    username = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Auditoría de acción"
        verbose_name_plural = "Auditoría de acciones"

    def __str__(self) -> str:
        base = f"{self.accion} - {self.entidad}"
        if self.objeto_id:
            base += f" #{self.objeto_id}"
        return f"{base} ({self.created_at:%Y-%m-%d %H:%M:%S})"


class UserSecurityProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_profile",
    )
    must_change_password = models.BooleanField(default=True)
    password_changed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Perfil de seguridad de usuario"
        verbose_name_plural = "Perfiles de seguridad de usuarios"

    def __str__(self) -> str:
        return f"Seguridad de {self.user}"


class HistorialPrecioPelicula(models.Model):
    pelicula = models.ForeignKey(Pelicula, on_delete=models.CASCADE, related_name="historial_precios")
    precio_anterior = models.DecimalField(max_digits=8, decimal_places=2)
    precio_nuevo = models.DecimalField(max_digits=8, decimal_places=2)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name = "Historial de precio de película"
        verbose_name_plural = "Historial de precios de películas"

    def __str__(self) -> str:
        return (
            f"{self.pelicula.titulo}: {self.precio_anterior} -> "
            f"{self.precio_nuevo} ({self.changed_at:%Y-%m-%d %H:%M:%S})"
        )


class EventoDominio(models.Model):
    evento = models.CharField(max_length=80)
    entidad = models.CharField(max_length=80)
    referencia_id = models.PositiveIntegerField(blank=True, null=True)
    descripcion = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Evento de dominio"
        verbose_name_plural = "Eventos de dominio"

    def __str__(self) -> str:
        base = f"{self.evento} - {self.entidad}"
        if self.referencia_id:
            base += f" #{self.referencia_id}"
        return f"{base} ({self.created_at:%Y-%m-%d %H:%M:%S})"
