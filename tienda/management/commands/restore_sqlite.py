from __future__ import annotations

import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "Restaura una copia de seguridad SQLite con confirmación explícita."

    def add_arguments(self, parser):
        parser.add_argument(
            "--backup",
            required=True,
            help="Ruta del archivo SQLite de respaldo que se restaurará.",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Alias de base de datos configurado en Django (default: default).",
        )
        parser.add_argument(
            "--target",
            default="",
            help="Ruta explícita del archivo SQLite de destino. Si se omite, se usa la configuración Django.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Confirma la restauración sin prompt interactivo.",
        )

    def handle(self, *args, **options):
        backup_path = Path(options["backup"]).expanduser().resolve()
        if not backup_path.exists():
            raise CommandError(f"No existe el archivo de respaldo indicado: {backup_path}")

        target_path = self._resolve_target_path(
            database_alias=options["database"],
            explicit_target=options["target"],
        )
        if backup_path == target_path:
            raise CommandError("El archivo de respaldo y el destino no pueden ser el mismo.")

        if not options["yes"]:
            prompt = (
                f'Esto reemplazará "{target_path}" con "{backup_path}". '
                'Escribe RESTORE para continuar: '
            )
            confirmation = input(prompt).strip()
            if confirmation != "RESTORE":
                raise CommandError("Restauración cancelada por el usuario.")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        connections.close_all()
        shutil.copy2(backup_path, target_path)

        self.stdout.write(self.style.SUCCESS(f"Base restaurada en: {target_path}"))

    def _resolve_target_path(self, *, database_alias: str, explicit_target: str) -> Path:
        if explicit_target:
            return Path(explicit_target).expanduser().resolve()

        try:
            connection = connections[database_alias]
        except Exception as error:
            raise CommandError(f"No existe la base de datos configurada: {database_alias}") from error

        engine = connection.settings_dict.get("ENGINE", "")
        if engine != "django.db.backends.sqlite3":
            raise CommandError("El comando restore_sqlite solo funciona con bases SQLite.")

        name = connection.settings_dict.get("NAME")
        if not name:
            raise CommandError("La base SQLite no tiene una ruta de archivo configurada.")

        return Path(name).expanduser().resolve()
