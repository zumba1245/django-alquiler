from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify


CATALOGO_RETOS = [
    {"id": i, "titulo": f"Reto Django #{i}"} for i in range(1, 101)
]


class Command(BaseCommand):
    help = "Genera un reto personalizado por alumno para evitar entregas copiadas."

    def add_arguments(self, parser):
        parser.add_argument("--alumno", required=True, help="Nombre completo del alumno.")
        parser.add_argument("--codigo", required=True, help="Código único (matrícula, DNI, etc.).")
        parser.add_argument(
            "--cantidad",
            type=int,
            default=12,
            help="Cantidad de retos a asignar (default: 12).",
        )
        parser.add_argument(
            "--salida",
            default="retos",
            help="Carpeta de salida para guardar el JSON (default: retos).",
        )
        parser.add_argument(
            "--semilla-curso",
            default="django-alquiler-curso-2026",
            help="Semilla secreta del curso para variar resultados.",
        )

    def handle(self, *args, **options):
        alumno = options["alumno"].strip()
        codigo = options["codigo"].strip()
        cantidad = int(options["cantidad"])
        salida = options["salida"].strip()
        semilla_curso = options["semilla_curso"].strip()

        if not alumno or not codigo:
            raise CommandError("Debes indicar --alumno y --codigo.")
        if cantidad < 5 or cantidad > 25:
            raise CommandError("La cantidad debe estar entre 5 y 25 retos.")

        seed_source = f"{alumno}|{codigo}|{semilla_curso}"
        seed_hash = hashlib.sha256(seed_source.encode("utf-8")).hexdigest()
        seed_int = int(seed_hash[:16], 16)
        rng = random.Random(seed_int)

        retos = rng.sample(CATALOGO_RETOS, k=cantidad)
        retos = sorted(retos, key=lambda x: x["id"])

        token = hashlib.sha256(f"TOKEN|{seed_source}".encode("utf-8")).hexdigest()[:12].upper()
        slug_alumno = slugify(alumno) or "alumno"

        # Parámetros únicos para "firma" de la solución de cada alumno.
        parametros_unicos = {
            "stock_minimo_pelicula": rng.randint(1, 4),
            "mora_por_dia_soles": rng.randint(1, 5),
            "limite_alquileres_pendientes": rng.randint(2, 6),
            "dias_maximo_retraso": rng.randint(3, 10),
            "prefijo_slug_obligatorio": f"{slug_alumno[:6]}-{rng.randint(10, 99)}",
        }

        data = {
            "alumno": alumno,
            "codigo": codigo,
            "token_entrega": token,
            "generado_en_utc": datetime.now(timezone.utc).isoformat(),
            "reglas_entrega": {
                "rama_git_obligatoria": f"alumno/{slug_alumno}-{token[:4].lower()}",
                "nombre_archivo_reflexion": f"REFLEXION_{token}.md",
                "incluir_token_en_readme": True,
                "incluir_token_en_commit_final": True,
            },
            "parametros_unicos": parametros_unicos,
            "retos_asignados": retos,
            "instruccion_docente": (
                "Pide al alumno que implemente solo estos retos. "
                "Si otro repo tiene token o parámetros distintos, se considera copia."
            ),
        }

        output_dir = Path(salida)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{slug_alumno}-{codigo}.json"
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Reto generado: {output_path}"))
        self.stdout.write(self.style.WARNING(f"Token único del alumno: {token}"))
