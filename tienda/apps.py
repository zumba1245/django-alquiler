from django.apps import AppConfig


class TiendaConfig(AppConfig):
    name = "tienda"

    def ready(self):
        # Registrar señales de auditoría al cargar la app
        import tienda.signals  # noqa: F401
        import tienda.checks  # noqa: F401
