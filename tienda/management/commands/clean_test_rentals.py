from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from tienda.models import Alquiler, Pelicula


class Command(BaseCommand):
    help = "Elimina alquileres de prueba asociados a datos Seed y restaura stock cuando corresponde."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra cuántos alquileres de prueba se borrarían sin aplicar cambios.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        alquileres = list(
            Alquiler.objects.select_related("cliente", "pelicula").filter(
                cliente__nombre__startswith="Cliente Seed "
            ) | Alquiler.objects.select_related("cliente", "pelicula").filter(
                pelicula__titulo__startswith="Pelicula Seed "
            )
        )
        total = len(alquileres)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry-run: se eliminarian {total} alquileres de prueba.")
            )
            return

        stock_restaurado = 0
        with transaction.atomic():
            for alquiler in alquileres:
                if alquiler.estado != Alquiler.ESTADO_ANULADO:
                    Pelicula.objects.filter(pk=alquiler.pelicula_id).update(
                        stock=F("stock") + 1
                    )
                    stock_restaurado += 1
                alquiler.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Limpieza completada: alquileres_eliminados={total}, stock_restaurado={stock_restaurado}."
            )
        )
