from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.checks import Error, register


@register()
def tienda_configuration_checks(app_configs, **kwargs):
    errors = []

    if getattr(settings, "PELICULA_PRECIO_MINIMO", 0) < 0:
        errors.append(
            Error(
                "PELICULA_PRECIO_MINIMO no puede ser negativo.",
                hint="Usa 0 o un valor positivo para la regla mínima de precio.",
                id="tienda.E001",
            )
        )

    middleware = list(getattr(settings, "MIDDLEWARE", []))
    session_security_middleware = "tienda.middleware.SessionSecurityMiddleware"
    force_initial_password_change = getattr(settings, "FORCE_INITIAL_PASSWORD_CHANGE", True)
    session_idle_timeout_seconds = int(getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 0))
    if (
        (force_initial_password_change or session_idle_timeout_seconds > 0)
        and session_security_middleware not in middleware
    ):
        errors.append(
            Error(
                "SessionSecurityMiddleware es obligatorio para las reglas de seguridad activas.",
                hint=(
                    "Agrega 'tienda.middleware.SessionSecurityMiddleware' a MIDDLEWARE "
                    "o desactiva las banderas de seguridad que dependen de él."
                ),
                id="tienda.E002",
            )
        )

    logging_config = getattr(settings, "LOGGING", {})
    error_handler = logging_config.get("handlers", {}).get("error_file")
    if not error_handler:
        errors.append(
            Error(
                "Falta el handler LOGGING.handlers.error_file para el log rotativo de errores.",
                hint="Configura un RotatingFileHandler para registrar errores en archivo.",
                id="tienda.E003",
            )
        )
    else:
        if error_handler.get("class") != "logging.handlers.RotatingFileHandler":
            errors.append(
                Error(
                    "LOGGING.handlers.error_file debe usar RotatingFileHandler.",
                    hint="Usa la clase logging.handlers.RotatingFileHandler.",
                    id="tienda.E004",
                )
            )

        filename = error_handler.get("filename")
        if not filename:
            errors.append(
                Error(
                    "LOGGING.handlers.error_file debe definir un filename.",
                    hint="Apunta el log a un archivo como logs/errors.log.",
                    id="tienda.E005",
                )
            )
        else:
            log_dir = Path(filename).expanduser().resolve().parent
            if not log_dir.exists():
                errors.append(
                    Error(
                        "El directorio del log de errores no existe.",
                        hint=f"Crea el directorio {log_dir} o ajusta la ruta del log.",
                        id="tienda.E006",
                    )
                )

        if int(error_handler.get("maxBytes", 0) or 0) <= 0:
            errors.append(
                Error(
                    "LOGGING.handlers.error_file debe definir maxBytes mayor que 0.",
                    hint="Configura el tamaño máximo del archivo antes de rotar.",
                    id="tienda.E007",
                )
            )

        if int(error_handler.get("backupCount", 0) or 0) < 1:
            errors.append(
                Error(
                    "LOGGING.handlers.error_file debe conservar al menos una copia.",
                    hint="Configura backupCount con valor 1 o mayor.",
                    id="tienda.E008",
                )
            )

    return errors
