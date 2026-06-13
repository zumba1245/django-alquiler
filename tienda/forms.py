from __future__ import annotations

import csv
import datetime
import io
from decimal import Decimal

from django import forms
from django.conf import settings

from .models import Alquiler, Categoria, Cliente, MetodoPago, Pelicula


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nombre", "descripcion"]
        help_texts = {
            "nombre": "Nombre único de la categoría (ejemplo: Acción).",
            "descripcion": "Descripción breve opcional para identificar la categoría.",
        }


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "dni", "email", "telefono"]
        help_texts = {
            "nombre": "Nombre completo del cliente.",
            "dni": "Debe tener 8 dígitos y ser único.",
            "email": "Opcional. Si se registra, debe ser único.",
            "telefono": "Número de contacto opcional.",
        }


class PeliculaForm(forms.ModelForm):
    class Meta:
        model = Pelicula
        fields = [
            "titulo",
            "director",
            "pais_origen",
            "anio",
            "categoria",
            "precio_alquiler",
            "duracion_minutos",
            "stock",
        ]
        help_texts = {
            "titulo": "Título principal de la película.",
            "director": "Nombre del director (opcional).",
            "pais_origen": "País de origen (opcional).",
            "anio": "No puede ser mayor al año actual.",
            "categoria": "Categoría a la que pertenece la película.",
            "precio_alquiler": "Precio por alquiler en soles.",
            "duracion_minutos": "Duración total en minutos.",
            "stock": "Cantidad disponible para alquilar.",
        }

    def clean_titulo(self):
        titulo = (self.cleaned_data.get("titulo") or "").strip()
        if not titulo:
            raise forms.ValidationError("El título no puede estar vacío.")
        return titulo

    def clean_anio(self):
        anio = self.cleaned_data["anio"]
        current_year = datetime.date.today().year
        if anio > current_year:
            raise forms.ValidationError("El año no puede ser mayor al año actual.")
        return anio

    def clean_precio_alquiler(self):
        precio = self.cleaned_data["precio_alquiler"]
        precio_minimo = Decimal(str(getattr(settings, "PELICULA_PRECIO_MINIMO", 0)))
        if precio < precio_minimo:
            raise forms.ValidationError(
                f"El precio de alquiler no puede ser menor a {precio_minimo:.2f}."
            )
        return precio

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = Categoria.objects.filter(is_active=True)


class PeliculaFilterForm(forms.Form):
    anio = forms.IntegerField(required=False, label="Año", help_text="Filtra por año exacto.")
    categoria = forms.ModelChoiceField(
        required=False,
        queryset=Categoria.objects.filter(is_active=True),
        label="Categoría",
        help_text="Filtra por una categoría específica.",
    )
    precio_min = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=8,
        label="Precio mín",
        help_text="Precio mínimo de alquiler.",
    )
    precio_max = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=8,
        label="Precio máx",
        help_text="Precio máximo de alquiler.",
    )

    def clean(self):
        cleaned = super().clean()
        precio_min = cleaned.get("precio_min")
        precio_max = cleaned.get("precio_max")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise forms.ValidationError("El precio mínimo no puede ser mayor al precio máximo.")
        return cleaned


class AlquilerCreateForm(forms.ModelForm):
    class Meta:
        model = Alquiler
        fields = ["cliente", "pelicula"]
        help_texts = {
            "cliente": "Cliente que realizará el alquiler.",
            "pelicula": "Solo se muestran películas con stock disponible.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.filter(is_active=True)
        self.fields["pelicula"].queryset = Pelicula.objects.filter(is_active=True, stock__gt=0)


class AlquilerAdvancedSearchForm(forms.Form):
    cliente = forms.ModelChoiceField(
        required=False,
        queryset=Cliente.objects.filter(is_active=True),
        label="Cliente",
        help_text="Filtra por cliente específico.",
    )
    pelicula = forms.ModelChoiceField(
        required=False,
        queryset=Pelicula.objects.filter(is_active=True),
        label="Película",
        help_text="Filtra por película específica.",
    )
    categoria = forms.ModelChoiceField(
        required=False,
        queryset=Categoria.objects.filter(is_active=True),
        label="Categoría",
        help_text="Filtra por categoría de la película.",
    )
    estado = forms.ChoiceField(
        required=False,
        choices=[("", "Todos")] + list(Alquiler.ESTADO_CHOICES),
        label="Estado",
        help_text="Filtra por estado del alquiler.",
    )
    fecha_desde = forms.DateField(
        required=False,
        label="Fecha desde",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Fecha mínima de alquiler.",
    )
    fecha_hasta = forms.DateField(
        required=False,
        label="Fecha hasta",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Fecha máxima de alquiler.",
    )
    precio_min = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=8,
        label="Precio mín",
        help_text="Precio mínimo del alquiler.",
    )
    precio_max = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=8,
        label="Precio máx",
        help_text="Precio máximo del alquiler.",
    )
    solo_vencidos = forms.BooleanField(
        required=False,
        label="Solo vencidos",
        help_text="Muestra solo pendientes con fecha anterior a hoy.",
    )

    def clean(self):
        cleaned = super().clean()
        fecha_desde = cleaned.get("fecha_desde")
        fecha_hasta = cleaned.get("fecha_hasta")
        precio_min = cleaned.get("precio_min")
        precio_max = cleaned.get("precio_max")

        if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
            raise forms.ValidationError("La fecha desde no puede ser posterior a la fecha hasta.")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise forms.ValidationError("El precio mínimo no puede ser mayor al precio máximo.")
        return cleaned


class CobroMasivoForm(forms.Form):
    ids = forms.CharField(
        label="IDs de alquiler",
        help_text="Separa por comas o espacios (ejemplo: 1,2,3).",
        widget=forms.TextInput(attrs={"placeholder": "1,2,3"}),
    )
    metodo_pago = forms.ModelChoiceField(
        required=False,
        queryset=MetodoPago.objects.filter(is_active=True),
        label="Método de pago (opcional)",
        help_text="Método que se aplicará a todos los alquileres cobrados.",
    )
    fecha_devolucion = forms.DateField(
        required=False,
        label="Fecha de devolución (opcional)",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Si se omite, se usará la fecha de hoy.",
    )

    def clean_ids(self):
        raw = self.cleaned_data["ids"]
        parts = [part.strip() for part in raw.replace(",", " ").split() if part.strip()]
        if not parts:
            raise forms.ValidationError("Debes indicar al menos un ID.")

        parsed_ids = []
        for part in parts:
            if not part.isdigit():
                raise forms.ValidationError("Los IDs deben ser números enteros positivos.")
            value = int(part)
            if value <= 0:
                raise forms.ValidationError("Los IDs deben ser mayores que 0.")
            parsed_ids.append(value)

        unique_ids = list(dict.fromkeys(parsed_ids))
        return unique_ids


class ClienteCSVImportForm(forms.Form):
    csv_file = forms.FileField(
        label="Archivo CSV",
        help_text="Columnas requeridas: nombre,dni. Opcionales: email,telefono.",
    )
    actualizar_existentes = forms.BooleanField(
        required=False,
        label="Actualizar clientes existentes por DNI",
        help_text="Si se marca, actualizará nombre/email/teléfono de clientes ya registrados.",
    )

    def clean_csv_file(self):
        csv_file = self.cleaned_data["csv_file"]
        filename = (csv_file.name or "").lower()
        if not filename.endswith(".csv"):
            raise forms.ValidationError("Debes subir un archivo con extensión .csv.")

        try:
            content = csv_file.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise forms.ValidationError("El CSV debe estar codificado en UTF-8.") from error
        finally:
            csv_file.seek(0)

        if not content.strip():
            raise forms.ValidationError("El archivo CSV está vacío.")

        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            raise forms.ValidationError("El CSV debe incluir cabeceras en la primera fila.")

        headers = {header.strip().lower() for header in reader.fieldnames if header}
        required_headers = {"nombre", "dni"}
        missing_headers = sorted(required_headers - headers)
        if missing_headers:
            raise forms.ValidationError(
                f"Faltan columnas requeridas: {', '.join(missing_headers)}."
            )

        return csv_file


class CategoriaPrecioLoteForm(forms.Form):
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.filter(is_active=True),
        label="Categoría",
        help_text="Se actualizarán todas las películas de esta categoría.",
    )
    nuevo_precio = forms.DecimalField(
        min_value=Decimal("0"),
        decimal_places=2,
        max_digits=8,
        label="Nuevo precio",
        help_text="Precio que se aplicará en lote a todas las películas de la categoría.",
    )

    def clean_nuevo_precio(self):
        nuevo_precio = self.cleaned_data["nuevo_precio"]
        precio_minimo = Decimal(str(getattr(settings, "PELICULA_PRECIO_MINIMO", 0)))
        if nuevo_precio < precio_minimo:
            raise forms.ValidationError(
                f"El precio no puede ser menor a {precio_minimo:.2f}."
            )
        return nuevo_precio

    def clean_categoria(self):
        categoria = self.cleaned_data["categoria"]
        if not Pelicula.objects.filter(categoria=categoria).exists():
            raise forms.ValidationError("La categoría seleccionada no tiene películas.")
        return categoria


class MarcarPagadoForm(forms.Form):
    metodo_pago = forms.ModelChoiceField(
        required=False,
        queryset=MetodoPago.objects.filter(is_active=True),
        label="Método de pago (opcional)",
        help_text="Selecciona cómo se realizó el pago.",
    )
    fecha_devolucion = forms.DateField(
        required=False,
        label="Fecha de devolución (opcional)",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="No puede ser anterior a la fecha de alquiler.",
    )

    def __init__(self, *args, alquiler=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.alquiler = alquiler

    def clean_fecha_devolucion(self):
        fecha_devolucion = self.cleaned_data.get("fecha_devolucion")
        if (
            fecha_devolucion
            and self.alquiler is not None
            and fecha_devolucion < self.alquiler.fecha_alquiler
        ):
            raise forms.ValidationError(
                "La fecha de devolución no puede ser anterior a la fecha de alquiler."
            )
        return fecha_devolucion


class VentasFilterForm(forms.Form):
    desde = forms.DateField(
        required=False,
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Fecha inicial del rango (opcional).",
    )
    hasta = forms.DateField(
        required=False,
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Fecha final del rango (opcional).",
    )

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get("desde")
        hasta = cleaned.get("hasta")

        if desde and hasta and desde > hasta:
            raise forms.ValidationError("La fecha 'Desde' no puede ser posterior a 'Hasta'.")

        return cleaned


class SimularVentasForm(forms.Form):
    numero_ventas = forms.IntegerField(
        min_value=1,
        max_value=200,
        label="Cantidad de ventas a simular",
        help_text="Cantidad de alquileres pagados que se generarán.",
    )
    desde = forms.DateField(
        required=False,
        label="Desde (opcional)",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Inicio del rango de fechas. Si se omite, se usa hoy.",
    )
    hasta = forms.DateField(
        required=False,
        label="Hasta (opcional)",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Fin del rango de fechas. Si se omite, se usa hoy.",
    )

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get("desde")
        hasta = cleaned.get("hasta")

        if desde and hasta and desde > hasta:
            raise forms.ValidationError("La fecha 'Desde' no puede ser posterior a 'Hasta'.")

        # Si no se manda rango, usaremos la fecha de hoy.
        if not desde and not hasta:
            today = datetime.date.today()
            cleaned["desde"] = today
            cleaned["hasta"] = today

        return cleaned


class MetodoPagoForm(forms.ModelForm):
    class Meta:
        model = MetodoPago
        fields = ["nombre", "descripcion"]
        help_texts = {
            "nombre": "Nombre único del método de pago (ejemplo: Yape).",
            "descripcion": "Descripción opcional del método.",
        }

