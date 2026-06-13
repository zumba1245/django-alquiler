# Manual y guía de clase — Alquiler de Películas (Django + SQLite)

Este documento es el **manual del proyecto** y al mismo tiempo una **guía para el aula**: explica _qué hace la aplicación_, _cómo se construyó_, _qué conceptos de Django practican_ y _qué tareas les sirven para reforzar_.

---

## 1. Qué es este proyecto (en una frase)

Es una aplicación web hecha con **Django** que permite registrar **categorías de películas**, **películas**, **clientes** y **alquileres**, y ver **ventas** entendidas como _alquileres ya pagados_. La base de datos es **SQLite** (un solo archivo local, ideal para clase).

---

## 2. Objetivos de aprendizaje (qué van a aprender)

Al trabajar con este repositorio, el estudiante debería poder:

1. Explicar el patrón **MVT** de Django (Modelos, Vistas, Plantillas) y cómo encaja una **petición HTTP** en ese flujo.
2. Crear un **proyecto** y una **app**, registrar la app en `INSTALLED_APPS` y enlazar **URLs**.
3. Definir **modelos** con relaciones (`ForeignKey`), generar **migraciones** y aplicarlas (`migrate`).
4. Construir pantallas **CRUD** (crear, listar, editar, borrar) usando vistas genéricas cuando tiene sentido.
5. **Consultar** y **filtrar** datos desde las vistas (por ejemplo, alquileres pagados vs pendientes).
6. Entender **reglas de negocio simples** en código (por ejemplo: “venta” = alquiler con `pagado=True`).
7. Leer y modificar **plantillas** y usar un **filtro personalizado** para formato de moneda.

---

## 3. Prerrequisitos y materiales

### 3.1. Qué deben saber antes

- Uso básico de **terminal** (cambiar de carpeta, ejecutar comandos).
- **Python 3** instalado (en clase conviene acordar una versión mínima; este proyecto se generó con Django 6).
- Nociones de **HTML** (etiquetas, formularios) ayudan mucho al ver las plantillas.

### 3.2. Qué necesitan en la computadora

- Editor de código (por ejemplo VS Code / Cursor).
- Navegador web.
- Opcional: **Git** (si el docente publica el repo en GitHub/GitLab).

---

## 4. Glosario rápido (vocabulario Django)

| Término       | Significado breve                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------------------- |
| **Proyecto**  | Carpeta de configuración global (`alquiler_site/`), URLs raíz, settings por entorno (`settings/base.py`, `settings/dev.py`, `settings/prod.py`). |
| **App**       | Módulo reutilizable con modelos/vistas (`tienda/`). Un proyecto puede tener varias apps.                |
| **Modelo**    | Clase Python que representa una **tabla** en la base de datos.                                          |
| **Migración** | Archivo que describe cambios en el esquema de la BD; se aplica con `migrate`.                           |
| **Vista**     | Función o clase que **recibe** la petición HTTP y **devuelve** una respuesta (HTML, redirección, etc.). |
| **Plantilla** | Archivo HTML con sintaxis Django (`{{ }}`, `{% %}`) para mostrar datos.                                 |
| **URLconf**   | Mapeo “ruta del navegador ↔ vista”.                                                                     |
| **ORM**       | Capa que traduce `Modelo.objects.filter(...)` a **SQL** sin escribir SQL a mano.                        |
| **Admin**     | Panel web incluido en Django para gestionar datos (`/admin/`).                                          |

---

## 5. Caso de negocio (reglas que deben entender)

### 5.1. Entidades

- **Categoría**: agrupa películas (por ejemplo: Acción, Comedia).
- **Película**: tiene título, año, categoría y precio de alquiler en **soles** (el valor numérico se guarda en BD; la **presentación** `S/ 3,50` está en plantillas).
- **Cliente**: quien alquila.
- **Alquiler**: relación entre cliente y película en una fecha; tiene `pagado` y un `precio` “congelado” al momento del alquiler.

### 5.2. Qué cuenta como “venta”

En esta versión didáctica:

- **Venta** = un `Alquiler` con `pagado=True`.

Eso simplifica la clase: no hay otra tabla `Venta`; el ingreso se calcula sumando `precio` de alquileres pagados.

---

## 6. Cómo “piensa” Django: MVT y el recorrido de una petición

### 6.1. MVT (Model–View–Template)

1. **Modelo**: define _qué datos existen_ y cómo se guardan.
2. **Vista**: decide _qué consultar_, _qué validar_ y _qué responder_.
3. **Plantilla**: define _cómo se ve_ la respuesta HTML.

### 6.2. Ejemplo mental (una visita a `/peliculas/`)

1. El navegador pide `GET /peliculas/`.
2. Django busca en `alquiler_site/urls.py` y llega a `tienda/urls.py`.
3. Esa ruta llama a una **vista** (aquí, una vista genérica tipo listado).
4. La vista consulta el **modelo** `Pelicula` en la base de datos.
5. Django renderiza la **plantilla** `templates/tienda/pelicula_list.html` con la lista.

Si un estudiante puede contar ese flujo en voz alta, ya entendió la mitad del framework.

---

## 7. Mapa del repositorio (dónde está cada cosa)

```text
django-alquiler/
├── manage.py                 # Punto de entrada: comandos de Django
├── requirements.txt          # Django (y dependencias) con versiones fijadas
├── db.sqlite3                # Base SQLite (aparece tras migrar; no suele subirse a Git)
├── alquiler_site/            # Proyecto Django
│   ├── settings/
│   │   ├── base.py           # Configuración compartida
│   │   ├── dev.py            # Configuración de desarrollo
│   │   └── prod.py           # Configuración de producción
│   └── urls.py               # URLs globales (incluye la app tienda)
├── tienda/                   # App del negocio
│   ├── models.py             # Tablas: Categoria, Pelicula, Cliente, Alquiler
│   ├── views.py              # Lógica de pantallas
│   ├── urls.py               # Rutas de la app
│   ├── forms.py              # Formularios (simulación, marcar pagado, etc.)
│   ├── admin.py              # Registro en el panel admin
│   └── templatetags/
│       └── soles.py          # Filtro |soles → muestra S/ 3,50
└── templates/
    ├── base.html             # Layout común (menú, estilos simples)
    └── tienda/               # Pantallas HTML de la app
```

---

## 8. Cómo se creó este proyecto (reproducible, paso a paso)

> Esta sección sirve para que el docente **muestre el origen** del código, o para que un alumno avanzado lo regenere desde cero en otra carpeta.

### 8.1. Entorno y dependencias

```bash
python -m venv .venv
source .venv/bin/activate          # En Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

### 8.2. Crear el proyecto y la app

```bash
django-admin startproject alquiler_site .
python manage.py startapp tienda
```

### 8.3. Conectar la app

- En `alquiler_site/settings/dev.py`:
  - Agregar `'tienda'` a `INSTALLED_APPS`.
  - Configurar `TEMPLATES['DIRS']` para que encuentre `templates/`.
- En `alquiler_site/urls.py`:
  - Incluir `path('', include('tienda.urls'))`.

### 8.4. Modelos y base de datos

```bash
python manage.py makemigrations
python manage.py migrate
```

### 8.5. Crear superusuario (panel admin)

```bash
python manage.py createsuperuser
```

Luego entrar a `http://127.0.0.1:8000/admin/`.

### 8.6. Ejecutar el servidor de desarrollo

```bash
python manage.py runserver
```

Abrir `http://127.0.0.1:8000/`.

### 8.7. Seleccionar entorno de configuración

Por defecto, `manage.py`, `wsgi.py` y `asgi.py` usan:

- `alquiler_site.settings.dev`

Si quieres ejecutar con configuración de producción en local, define:

```bash
DJANGO_SETTINGS_MODULE=alquiler_site.settings.prod
```

Variables de entorno clave:

- `DJANGO_SECRET_KEY`: clave secreta de Django (obligatoria en despliegues reales).
- `DJANGO_DEBUG`: `1/true/on` para activar modo debug, `0/false/off` para desactivarlo.

### 8.8. Procedimiento de release (paso a paso)

> Objetivo: publicar una versión con validaciones mínimas, copia de seguridad y posibilidad de rollback.

1. **Actualizar código local**
   - Cambia a la rama que vas a liberar.
   - Trae los cambios más recientes del repositorio.

2. **Activar entorno**

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

3. **Ejecutar chequeos automáticos previos**

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test tienda.tests
```

Si usas cobertura:

```bash
python -m coverage run manage.py test tienda.tests
python -m coverage report
```

4. **Crear backup antes de tocar la base**

```bash
python manage.py backup_sqlite --output-dir backups
```

5. **Aplicar migraciones con settings del entorno objetivo**

```bash
DJANGO_SETTINGS_MODULE=alquiler_site.settings.prod python manage.py migrate
```

6. **Reiniciar el proceso de la aplicación**
   - Reinicia el servidor o servicio que publica Django en ese entorno.

7. **Validación manual rápida post-release**
   - Entrar al dashboard `/`.
   - Crear un alquiler de prueba.
   - Marcarlo como pagado.
   - Verificar que aparezca en `/ventas/`.
   - Revisar que no existan errores recientes en `logs/errors.log`.

8. **Si algo sale mal, detener y restaurar**

```bash
python manage.py restore_sqlite --backup backups/<archivo>.sqlite3
```

Escribe `RESTORE` cuando el comando lo solicite, o usa `--yes` solo en automatizaciones controladas.

### 8.9. Plan de rollback ante error en producción

> Objetivo: volver rápidamente a un estado estable si una liberación introduce fallos.

#### Cuándo activar rollback

- Error 500 repetido en pantallas clave como `/`, `/alquileres/` o `/ventas/`.
- Fallo al aplicar migraciones.
- Datos inconsistentes después de crear, pagar o anular alquileres.
- Errores nuevos y continuos en `logs/errors.log`.

#### Pasos de rollback

1. **Detener la liberación**
   - No sigas aplicando cambios ni nuevas migraciones.
   - Si hay usuarios operando, comunica una ventana breve de mantenimiento.

2. **Identificar el último backup válido**
   - Busca el archivo correcto en `backups/`.
   - Confirma fecha y hora del backup previo al release fallido.

3. **Volver al código estable**
   - Cambia a la última versión validada del repositorio.
   - Reinstala dependencias si hubo cambios en `requirements.txt`.

4. **Restaurar la base SQLite**

```bash
python manage.py restore_sqlite --backup backups/<archivo_valido>.sqlite3
```

5. **Aplicar migraciones solo si la versión estable lo necesita**

```bash
python manage.py migrate
```

6. **Reiniciar el servicio**
   - Reinicia el proceso web o servicio del entorno.

7. **Validar que el sistema volvió a estar sano**
   - Abrir `/`.
   - Revisar `/ventas/`.
   - Crear un alquiler de prueba.
   - Marcarlo como pagado.
   - Verificar que no aparezcan errores nuevos en `logs/errors.log`.

#### Recomendaciones operativas

- No sobrescribas ni elimines el backup usado en el rollback.
- Documenta qué release falló, a qué hora y con qué síntoma.
- Si el rollback fue por datos, conserva copia del backup fallido para análisis posterior.

### 8.10. Checklist final de calidad

> Úsalo antes de cerrar una entrega o hacer un release.

#### Código y base de datos

- [ ] `python manage.py check`
- [ ] `python manage.py makemigrations --check --dry-run`
- [ ] Las migraciones nuevas están versionadas si hubo cambios de modelos.
- [ ] Existe backup reciente si se va a tocar la base real.

#### Testing

- [ ] `python manage.py test tienda.tests`
- [ ] Si aplica, `python -m coverage run manage.py test tienda.tests`
- [ ] Si aplica, `python -m coverage report`
- [ ] Las pruebas nuevas cubren validación, integración o regresión del cambio hecho.

#### Seguridad y operación

- [ ] `DJANGO_SECRET_KEY` no usa un valor inseguro en producción.
- [ ] `DJANGO_DEBUG` está desactivado en producción.
- [ ] `logs/errors.log` existe y el logging rotativo está operativo.
- [ ] El plan de rollback y el backup a restaurar están identificados.

#### Revisión funcional

- [ ] El dashboard carga correctamente.
- [ ] Se puede crear un alquiler.
- [ ] Se puede marcar un alquiler como pagado.
- [ ] Las ventas se reflejan correctamente en `/ventas/`.
- [ ] No hay errores visibles en los flujos principales.

#### Documentación y entrega

- [ ] README actualizado si cambió comportamiento, comando o configuración.
- [ ] Comandos nuevos documentados.
- [ ] Fixtures, backups o logs generados localmente no quedan versionados por error.
- [ ] La rama o entrega final incluye los cambios probados y consistentes.

---

## 9. Recorrido didáctico por archivos (qué leer primero)

### 9.1. `tienda/models.py` — el “corazón” de los datos

Aquí se definen tablas y relaciones:

- `Pelicula.categoria` apunta a `Categoria` (**muchos a uno**: muchas películas, una categoría).
- `Alquiler.cliente` y `Alquiler.pelicula` conectan cliente y película (**muchos a uno** en ambos casos).

**Pregunta para la clase:** ¿por qué conviene guardar `Alquiler.precio` si ya existe `Peliculas.precio_alquiler`?

**Respuesta esperada:** porque si mañana cambias el precio de la película, los alquileres viejos deberían conservar el precio histórico.

### 9.2. `tienda/views.py` — reglas y pantallas

Aquí ocurre “lo que el servidor hace”:

- Vistas genéricas para CRUD (menos código repetido, ideal para principiantes).
- `MarcarPagadoView` para convertir un pendiente en venta.
- `simular_ventas` para generar datos de práctica.

### 9.3. `tienda/urls.py` — el mapa de la web

Cada `path(...)` es una **entrada del menú** en términos técnicos: une una URL con una vista.

### 9.4. `templates/` — lo que ve el usuario

- `base.html`: menú común (para no repetir HTML en cada página).
- Cada pantalla extiende `base` y muestra tablas/formularios.

### 9.5. `tienda/templatetags/soles.py` — presentación de moneda

En plantillas se usa:

```django
{% load soles %}
{{ importe|soles }}
```

Eso separa **dato** (número en BD) de **formato** (cómo se enseña en pantalla).

---

## 10. Tabla de rutas útiles (para practicar lectura de URLs)

| URL                               | Qué hace                                    |
| --------------------------------- | ------------------------------------------- |
| `/`                               | Inicio con resumen e ingresos               |
| `/categorias/`                    | Lista categorías                            |
| `/categorias/nueva/`              | Crear categoría                             |
| `/peliculas/`                     | Lista películas                             |
| `/peliculas/nueva/`               | Crear película                              |
| `/clientes/`                      | Lista clientes                              |
| `/clientes/nuevo/`                | Crear cliente                               |
| `/alquileres/`                    | Lista alquileres (filtro `?pagado=0` o `1`) |
| `/alquileres/nuevo/`              | Crear alquiler                              |
| `/alquileres/<id>/marcar-pagado/` | Marcar pagado (venta)                       |
| `/ventas/`                        | Lista de ventas + total                     |
| `/ventas/simular/`                | Simular ventas                              |
| `/admin/`                         | Panel administración Django                 |

---

## 11. Optimización de consultas: con y sin select_related

Si una lista muestra campos de relaciones `ForeignKey`, Django puede hacer muchas consultas extra.

- Sin optimización: se hace 1 consulta por cada fila al acceder a la relación.
- Con `select_related`: se carga la relación en la misma consulta.

En este proyecto:

- `PeliculaListView` usa `select_related("categoria")`
- `AlquilerListView` y `VentasListView` usan `select_related("cliente", "pelicula", "pelicula__categoria")`

Esto es útil cuando la plantilla necesita `pelicula.categoria.nombre` o `venta.cliente.nombre`.

---

## 12. Uso diario (referencia rápida)

### 11.1. Si ya tienes el código en tu máquina

```bash
cd /ruta/al/django-alquiler
source .venv/bin/activate
python manage.py migrate
python manage.py runserver
```

### 11.2. Si partes solo del `requirements.txt` (sin venv empaquetado)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### 11.3. Clonar con Git (cuando exista repositorio remoto)

```bash
git clone <URL_DEL_REPO>
cd <nombre_del_repo>
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

---

## 12. 100 retos de Django puro (nivel desafío)

> Objetivo: dominar Django de verdad.  
> Regla: resolver sin frameworks externos (solo Django y librería estándar de Python).

### Truco anti copia/pega (diferencial por alumno)

Para evitar que se pasen el repositorio ya hecho, este proyecto incluye un comando Django que genera
un **paquete de retos personalizado por alumno** con:

- token único de entrega
- parámetros de negocio distintos por estudiante
- subconjunto de retos asignados
- nombre de rama obligatoria para entrega

Comando:

```bash
python manage.py generar_reto_personalizado --alumno "Nombre Apellido" --codigo "2026A001"
```

Salida esperada:

- archivo JSON en `retos/<alumno>-<codigo>.json`
- token único (ejemplo: `A1B2C3D4E5F6`)

Regla de clase recomendada:

1. Cada alumno trabaja en su rama obligatoria (`alumno/<slug>-<token4>`).
2. Debe incluir su token en el README de su entrega y en el commit final.
3. Debe implementar los parámetros de negocio que le salieron en su JSON.
4. Si la entrega no coincide con su token/parámetros, se considera no válida.

### Bloque A — Modelos, relaciones y restricciones (1–10)

1. Agregar `stock` en `Pelicula` y evitar alquiler si `stock <= 0`.
2. Crear campo `dni` único en `Cliente` con validación de longitud.
3. Agregar `slug` único en `Pelicula` y autogenerarlo desde el título.
4. Añadir `estado` en `Alquiler` con choices (`pendiente`, `pagado`, `anulado`).
5. Registrar `fecha_pago` cuando un alquiler pase a `pagado`.
6. Crear modelo `MetodoPago` y asociarlo opcionalmente al alquiler.
7. Agregar `duracion_minutos` en película con `MinValueValidator`.
8. Agregar `director` y `pais_origen` en película.
9. Restringir `fecha_devolucion >= fecha_alquiler`.
10. Crear `UniqueConstraint` para impedir alquiler duplicado mismo cliente/película/fecha.

### Bloque B — ORM avanzado y consultas (11–20)

1. Listar top 10 películas más alquiladas con `annotate(Count(...))`.
2. Calcular ingreso total por categoría con `values().annotate(Sum(...))`.
3. Obtener clientes sin alquileres usando `annotate` + filtro.
4. Mostrar ticket promedio (`Avg`) de alquileres pagados.
5. Crear consulta para alquileres vencidos (pendientes y con fecha pasada).
6. Implementar ranking mensual de clientes por gasto total.
7. Calcular total de ventas por día en rango de fechas.
8. Filtrar películas por múltiples criterios combinables (año, categoría, precio).
9. Usar `select_related`/`prefetch_related` en listados para optimizar consultas.
10. Demostrar en documentación la diferencia de consultas con y sin optimización.

### Bloque C — Formularios y validaciones serias (21–30)

1. Crear `ModelForm` de película con validación de año no mayor al actual.
2. Validar que el título no sea vacío tras `strip()`.
3. Añadir validación de precio mínimo configurable por setting.
4. Mostrar errores globales (`non_field_errors`) en formularios.
5. Validar que una devolución no se marque antes del alquiler.
6. Agregar ayuda contextual (`help_text`) en todos los formularios principales.
7. Crear formulario de búsqueda avanzada para alquileres.
8. Implementar formulario de “cobro masivo” por IDs de alquiler.
9. Crear formulario para importar clientes desde CSV con validaciones.
10. Crear formulario para actualizar precios por categoría en lote.

### Bloque D — Vistas basadas en clases y mixins (31–40)

1. Reescribir un CRUD completo usando solo CBV.
2. Crear mixin para requerir usuario autenticado en vistas privadas.
3. Crear mixin reusable para paginación + ordenamiento.
4. Implementar `DetailView` de cliente con historial de alquileres.
5. Implementar `DetailView` de película con métricas (veces alquilada).
6. Crear `FormView` para simulación de ventas con resumen al finalizar.
7. Crear `TemplateView` de dashboard con KPIs.
8. Implementar borrado lógico (`is_active`) en vez de `DeleteView` físico.
9. Agregar vista para restaurar registros “borrados lógicamente”.
10. Crear vista para cerrar caja diaria y bloquear nuevas ventas del día.

### Bloque E — URLs, navegación y UX backend (41–50)

1. Diseñar esquema de URLs RESTful consistente para toda la app.
2. Agregar namespaces de app (`app_name`) y uso completo de `reverse`.
3. Mantener filtros en querystring durante paginación y ordenamiento.
4. Agregar breadcrumbs dinámicos con contexto en plantillas.
5. Crear páginas 404 y 500 personalizadas.
6. Agregar mensajes `success/error/warning` en operaciones clave.
7. Implementar botón “volver al listado filtrado” usando `next`.
8. Crear vista de inicio con métricas cacheadas por 60 segundos.
9. Agregar vista de auditoría de acciones recientes.
10. Crear navegación condicional según permisos del usuario.

### Bloque F — Admin profesional (51–60)

1. Mejorar `ModelAdmin` con `list_display`, `search_fields` y `list_filter`.
2. Agregar acciones personalizadas en admin (marcar pagados en lote).
3. Mostrar columnas calculadas en admin (total gastado por cliente).
4. Crear `InlineModelAdmin` para visualizar alquileres desde cliente.
5. Evitar edición de campos sensibles en admin si no es superuser.
6. Agregar filtros por rango de fechas personalizados en admin.
7. Configurar `readonly_fields` según estado del alquiler.
8. Optimizar admin con `autocomplete_fields`.
9. Añadir validaciones en admin para evitar inconsistencias.
10. Documentar 10 atajos útiles del admin en el README.

### Bloque G — Autenticación, autorización y seguridad (61–70)

1. Proteger vistas de escritura con `LoginRequiredMixin`.
2. Crear grupos (`cajero`, `supervisor`) y permisos por grupo.
3. Restringir simulación de ventas solo a `supervisor`.
4. Implementar política de permisos por objeto (ejemplo simple en vista).
5. Mover `DEBUG` y `SECRET_KEY` a variables de entorno.
6. Configurar `CSRF_COOKIE_SECURE` y `SESSION_COOKIE_SECURE` por entorno.
7. Agregar protección de tasa básica para formularios críticos (simple, en sesión).
8. Registrar intentos de login fallidos en una tabla de auditoría.
9. Forzar cambio de contraseña inicial para usuarios nuevos.
10. Implementar cierre de sesión automático por inactividad.

### Bloque H — Señales, transacciones y consistencia (71–80)

1. Usar `transaction.atomic` al crear alquiler + actualizar stock.
2. Revertir stock automáticamente cuando se anula un alquiler.
3. Crear señal `post_save` para registrar eventos de negocio.
4. Crear señal `post_delete` para registrar eliminación en auditoría.
5. Evitar dobles cobros con bloqueo transaccional (`select_for_update`).
6. Implementar idempotencia simple para marcar pago.
7. Registrar historial de cambios de precio de película.
8. Crear modelo `EventoDominio` para trazabilidad de acciones clave.
9. Implementar validación cruzada entre modelos en `clean()`.
10. Probar escenario de concurrencia con tests transaccionales.

### Bloque I — Testing serio en Django (81–90)

1. Escribir tests de modelos para todas las validaciones críticas.
2. Escribir tests de formularios con casos válidos e inválidos.
3. Escribir tests de vistas para permisos y respuestas HTTP.
4. Escribir tests de integración para flujo: crear alquiler -> pagar -> venta.
5. Crear fixture inicial para pruebas repetibles.
6. Medir cobertura y fijar objetivo mínimo (por ejemplo 70%).
7. Testear consultas optimizadas para evitar N+1 en listados.
8. Testear exportación CSV y su encabezado esperado.
9. Testear comando custom de carga de datos.
10. Crear suite de regresión para bugs reportados por alumnos.

### Bloque J — Gestión, despliegue básico y mantenimiento (91–100)

1. Crear comando `seed_data` con opciones (`--clientes`, `--peliculas`).
2. Crear comando para limpiar alquileres de prueba.
3. Implementar backups SQLite con comando y timestamp.
4. Crear comando para restaurar backup SQLite con confirmación.
5. Configurar logging a archivo rotativo para errores.
6. Separar settings por entorno (`base.py`, `dev.py`, `prod.py`).
7. Agregar chequeos custom en `manage.py check`.
8. Documentar procedimiento de release (paso a paso).
9. Documentar plan de rollback ante error en producción.
10. Preparar checklist final de calidad (tests, migraciones, seguridad, docs).

---

## 13. Atajos útiles del admin (10)

Estos atajos aceleran mucho el trabajo en `http://127.0.0.1:8000/admin/`:

1. En la lista, usa `click` en el nombre de columna para ordenar asc/desc.
2. Usa la caja de búsqueda superior para filtrar por `search_fields` sin abrir formularios.
3. Usa el filtro lateral (`list_filter`) para acotar por estado/fecha rápidamente.
4. Marca varios registros con checkbox y ejecuta acciones masivas (por ejemplo, marcar pagados).
5. Pulsa `Añadir` desde cada módulo para crear registros sin navegar por la app pública.
6. En `ForeignKey` con `autocomplete_fields`, escribe 2–3 letras para buscar más rápido.
7. Usa “Historial” dentro del formulario admin para auditar cambios por registro.
8. Usa “Ver en el sitio” para validar cómo se refleja un objeto en el dashboard público.
9. En listas largas, cambia página con paginación inferior para revisar lotes de datos.
10. Usa el filtro de fechas por rango (`Desde/Hasta`) en alquileres para cortes operativos.

## 14. Seguridad de vistas de escritura y grupos

- Las vistas con operación de escritura (crear/editar/eliminar/cobro masivo/simular ventas) están protegidas con mixins basados en `LoginRequiredMixin`.
- Se creó `WriteLoginRequiredMixin` para exigir login solo en métodos de escritura (`POST`, `PUT`, `PATCH`, `DELETE`), manteniendo públicos algunos listados cuando aplica.
- Se crean automáticamente dos grupos al migrar la app `tienda`:
1. `cajero`: enfocado en operación diaria (ver/agregar/cambiar alquileres y lectura de catálogos).
2. `supervisor`: permisos ampliados (catálogos, alquileres, caja diaria y auditoría de acciones).

Para asignar un usuario:
1. Entra a `admin/auth/user/`.
2. Abre el usuario.
3. En “Grupos”, agrega `cajero` o `supervisor`.
4. Guarda.

## 15. Problemas frecuentes y cómo interpretarlos

| Síntoma                                      | Causa común                                     | Qué hacer                                        |
| -------------------------------------------- | ----------------------------------------------- | ------------------------------------------------ |
| `No module named django`                     | Venv no activado / paquetes no instalados       | Activar venv y `pip install -r requirements.txt` |
| Error al migrar                              | Modelos cambiaron sin migración                 | `makemigrations` y luego `migrate`               |
| `DisallowedHost`                             | Host no permitido                               | Revisar `ALLOWED_HOSTS` en `settings/dev.py` o `settings/prod.py` |
| Pantalla sin estilo “raro”                   | Normal: el proyecto prioriza simpleza didáctica | Esperado en esta versión                         |
| `TemplateSyntaxError: Invalid filter: soles` | Falta `{% load soles %}`                        | Agregar `load` en la plantilla                   |

---

## 16. Notas para el docente (evaluación sugerida)

Rúbrica simple (10 puntos):

- **3 pts — MVT y flujo:** explica petición→URL→vista→plantilla con un ejemplo real del proyecto.
- **3 pts — Modelo + migraciones:** crea campo nuevo con migración coherente.
- **2 pts — Consultas:** filtra/agrega correctamente con ORM.
- **2 pts — Calidad de entrega:** capturas, instrucciones reproducibles, sin “funciona en mi PC” sin pasos.

---

## 17. Licencia y uso educativo

Proyecto pensado para **uso educativo**. Si se publica, conviene aclarar versión de Python/Django y si `db.sqlite3` se ignora en Git (lo habitual).
