from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "Crea una copia de seguridad de la base SQLite con marca de tiempo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Alias de base de datos configurado en Django (default: default).",
        )
        parser.add_argument(
            "--output-dir",
            default="backups",
            help="Directorio donde se guardara la copia de seguridad.",
        )
        parser.add_argument(
            "--source",
            default="",
            help="Ruta explicita del archivo SQLite a respaldar. Si se omite, se usa la configuracion Django.",
        )

    def handle(self, *args, **options):
        source_path = self._resolve_source_path(
            database_alias=options["database"],
            explicit_source=options["source"],
        )
        output_dir = Path(options["output_dir"]).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = output_dir / f"{source_path.stem}-{timestamp}{source_path.suffix}"
        shutil.copy2(source_path, backup_path)

        self.stdout.write(self.style.SUCCESS(f"Backup creado: {backup_path}"))

    def _resolve_source_path(self, *, database_alias: str, explicit_source: str) -> Path:
        if explicit_source:
            source_path = Path(explicit_source).expanduser().resolve()
            if not source_path.exists():
                raise CommandError(f"No existe el archivo SQLite indicado: {source_path}")
            return source_path

        try:
            connection = connections[database_alias]
        except Exception as error:
            raise CommandError(f"No existe la base de datos configurada: {database_alias}") from error

        engine = connection.settings_dict.get("ENGINE", "")
        if engine != "django.db.backends.sqlite3":
            raise CommandError("El comando backup_sqlite solo funciona con bases SQLite.")

        name = connection.settings_dict.get("NAME")
        if not name:
            raise CommandError("La base SQLite no tiene una ruta de archivo configurada.")

        source_path = Path(name).expanduser().resolve()
        if not source_path.exists():
            raise CommandError(f"No existe el archivo SQLite configurado: {source_path}")
        return source_path
