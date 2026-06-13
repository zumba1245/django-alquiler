from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_delete, post_migrate, post_save, pre_save
from django.dispatch import receiver

from .models import (
    ActionAudit,
    Alquiler,
    Categoria,
    Cliente,
    EventoDominio,
    HistorialPrecioPelicula,
    LoginAttemptAudit,
    MetodoPago,
    Pelicula,
    UserSecurityProfile,
)


@receiver(user_login_failed)
def log_failed_login(sender, credentials, request, **kwargs):
    username = credentials.get("username") or credentials.get("email") or ""
    ip_address = None
    if request is not None:
        ip_address = request.META.get("REMOTE_ADDR")
    LoginAttemptAudit.objects.create(
        username=username,
        ip_address=ip_address,
        path=getattr(request, "path", ""),
        user_agent=request.META.get("HTTP_USER_AGENT", "") if request is not None else "",
    )


def _sync_group_permissions(group_name: str, permission_codenames: set[str]) -> None:
    group, _ = Group.objects.get_or_create(name=group_name)
    perms = Permission.objects.filter(content_type__app_label="tienda", codename__in=permission_codenames)
    group.permissions.set(perms)


@receiver(post_migrate)
def create_default_groups_and_permissions(sender, **kwargs):
    """
    Crea/actualiza grupos base de la app luego de migraciones.
    Se ejecuta de forma idempotente.
    """
    if getattr(sender, "name", None) != "tienda":
        return

    cajero_perms = {
        "view_categoria",
        "view_cliente",
        "add_cliente",
        "change_cliente",
        "view_pelicula",
        "view_metodopago",
        "view_alquiler",
        "add_alquiler",
        "change_alquiler",
    }

    supervisor_perms = {
        "view_categoria",
        "add_categoria",
        "change_categoria",
        "view_cliente",
        "add_cliente",
        "change_cliente",
        "view_pelicula",
        "add_pelicula",
        "change_pelicula",
        "view_metodopago",
        "add_metodopago",
        "change_metodopago",
        "view_alquiler",
        "add_alquiler",
        "change_alquiler",
        "delete_alquiler",
        "view_cajadiaria",
        "add_cajadiaria",
        "view_actionaudit",
    }

    _sync_group_permissions("cajero", cajero_perms)
    _sync_group_permissions("supervisor", supervisor_perms)


@receiver(post_save, sender=get_user_model())
def ensure_user_security_profile(sender, instance, created, **kwargs):
    if not created:
        return
    UserSecurityProfile.objects.get_or_create(
        user=instance,
        defaults={"must_change_password": not instance.is_superuser},
    )


def register_domain_event(
    *,
    evento: str,
    entidad: str,
    referencia_id: int | None = None,
    descripcion: str = "",
    payload: dict | None = None,
):
    EventoDominio.objects.create(
        evento=evento,
        entidad=entidad,
        referencia_id=referencia_id,
        descripcion=descripcion,
        payload=payload or {},
    )


@receiver(pre_save, sender=Pelicula)
def capture_previous_pelicula_price(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_precio_alquiler = None
        return
    previous = Pelicula.objects.filter(pk=instance.pk).only("precio_alquiler").first()
    instance._old_precio_alquiler = previous.precio_alquiler if previous else None


@receiver(post_save, sender=Pelicula)
def register_price_change_history(sender, instance, created, **kwargs):
    if created:
        return
    old_price = getattr(instance, "_old_precio_alquiler", None)
    if old_price is None or old_price == instance.precio_alquiler:
        return

    HistorialPrecioPelicula.objects.create(
        pelicula=instance,
        precio_anterior=old_price,
        precio_nuevo=instance.precio_alquiler,
    )
    register_domain_event(
        evento="precio_pelicula_actualizado",
        entidad="pelicula",
        referencia_id=instance.pk,
        descripcion=f"{instance.titulo}: {old_price} -> {instance.precio_alquiler}",
        payload={
            "precio_anterior": str(old_price),
            "precio_nuevo": str(instance.precio_alquiler),
        },
    )


@receiver(pre_save, sender=Alquiler)
def capture_previous_alquiler_state(sender, instance, **kwargs):
    if not instance.pk:
        instance._old_estado = None
        instance._old_pagado = None
        return
    previous = Alquiler.objects.filter(pk=instance.pk).only("estado", "pagado").first()
    instance._old_estado = previous.estado if previous else None
    instance._old_pagado = previous.pagado if previous else None


@receiver(post_save, sender=Alquiler)
def register_alquiler_business_events(sender, instance, created, **kwargs):
    if created:
        ActionAudit.objects.create(
            accion="alquiler_creado",
            entidad="alquiler",
            objeto_id=instance.pk,
            descripcion=f"cliente={instance.cliente_id}, pelicula={instance.pelicula_id}",
            username="sistema",
        )
        register_domain_event(
            evento="alquiler_creado",
            entidad="alquiler",
            referencia_id=instance.pk,
            descripcion="alquiler creado",
            payload={"cliente_id": instance.cliente_id, "pelicula_id": instance.pelicula_id},
        )
        return

    old_estado = getattr(instance, "_old_estado", None)
    old_pagado = getattr(instance, "_old_pagado", None)

    if old_estado != instance.estado and instance.estado == Alquiler.ESTADO_PAGADO:
        ActionAudit.objects.create(
            accion="alquiler_pagado",
            entidad="alquiler",
            objeto_id=instance.pk,
            descripcion=f"fecha_pago={instance.fecha_pago}",
            username="sistema",
        )
        register_domain_event(
            evento="alquiler_pagado",
            entidad="alquiler",
            referencia_id=instance.pk,
            descripcion="alquiler marcado como pagado",
            payload={"fecha_pago": str(instance.fecha_pago)},
        )
        return

    if old_estado != instance.estado and instance.estado == Alquiler.ESTADO_ANULADO:
        ActionAudit.objects.create(
            accion="alquiler_anulado",
            entidad="alquiler",
            objeto_id=instance.pk,
            descripcion=f"pagado_antes={old_pagado}",
            username="sistema",
        )
        register_domain_event(
            evento="alquiler_anulado",
            entidad="alquiler",
            referencia_id=instance.pk,
            descripcion="alquiler anulado",
            payload={"pagado_antes": bool(old_pagado)},
        )


@receiver(post_delete)
def register_delete_events(sender, instance, **kwargs):
    tracked_models = (Categoria, Cliente, Pelicula, MetodoPago, Alquiler)
    if sender not in tracked_models:
        return

    description = str(instance)
    ActionAudit.objects.create(
        accion="eliminar",
        entidad=sender._meta.model_name,
        objeto_id=getattr(instance, "pk", None),
        descripcion=description[:255],
        username="sistema",
    )
