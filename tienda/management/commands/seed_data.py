from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tienda.models import Categoria, Cliente, MetodoPago, Pelicula


class Command(BaseCommand):
    help = "Carga datos base de ejemplo para desarrollo y pruebas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clientes",
            type=int,
            default=5,
            help="Cantidad de clientes de ejemplo a crear.",
        )
        parser.add_argument(
            "--peliculas",
            type=int,
            default=5,
            help="Cantidad de peliculas de ejemplo a crear.",
        )

    def handle(self, *args, **options):
        total_clientes = int(options["clientes"])
        total_peliculas = int(options["peliculas"])

        if total_clientes < 0 or total_peliculas < 0:
            raise CommandError("Los valores --clientes y --peliculas no pueden ser negativos.")
        if total_clientes == 0 and total_peliculas == 0:
            raise CommandError("Debes solicitar al menos un cliente o una pelicula.")

        with transaction.atomic():
            categorias = self._ensure_categorias()
            self._ensure_metodos_pago()
            clientes_creados = self._create_clientes(total_clientes)
            peliculas_creadas = self._create_peliculas(total_peliculas, categorias)

        self.stdout.write(
            self.style.SUCCESS(
                "Seed completado: "
                f"clientes={clientes_creados}, peliculas={peliculas_creadas}, "
                f"categorias={len(categorias)}."
            )
        )

    def _ensure_categorias(self):
        categorias = []
        for nombre in ["Accion", "Drama", "Comedia", "Ciencia Ficcion"]:
            categoria, _ = Categoria.objects.get_or_create(
                nombre=nombre,
                defaults={
                    "descripcion": f"Categoria generada por seed_data: {nombre}.",
                    "is_active": True,
                },
            )
            categorias.append(categoria)
        return categorias

    def _ensure_metodos_pago(self):
        for nombre in ["Efectivo", "Yape", "Tarjeta"]:
            MetodoPago.objects.get_or_create(
                nombre=nombre,
                defaults={
                    "descripcion": f"Metodo generado por seed_data: {nombre}.",
                    "is_active": True,
                },
            )

    def _create_clientes(self, total_clientes):
        existentes = Cliente.objects.filter(nombre__startswith="Cliente Seed ").count()
        for offset in range(1, total_clientes + 1):
            index = existentes + offset
            Cliente.objects.create(
                nombre=f"Cliente Seed {index}",
                dni=f"{81000000 + index:08d}",
                email=f"seed{index}@example.com",
                telefono=f"900{index:05d}",
                is_active=True,
            )
        return total_clientes

    def _create_peliculas(self, total_peliculas, categorias):
        existentes = Pelicula.objects.filter(titulo__startswith="Pelicula Seed ").count()
        for offset in range(1, total_peliculas + 1):
            index = existentes + offset
            categoria = categorias[(index - 1) % len(categorias)]
            Pelicula.objects.create(
                titulo=f"Pelicula Seed {index}",
                anio=2020 + ((index - 1) % 5),
                categoria=categoria,
                precio_alquiler=Decimal("10.00") + Decimal(index),
                duracion_minutos=90 + ((index - 1) % 30),
                stock=1 + ((index - 1) % 4),
                is_active=True,
            )
        return total_peliculas
