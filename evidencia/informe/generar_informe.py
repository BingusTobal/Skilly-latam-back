from pathlib import Path
from datetime import date

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image

BASE = Path('/home/tobal/Proyectos/skilly_BACK')
EVID = BASE / 'evidencia'
OUT = EVID / 'informe'
THUMBS = OUT / 'thumbs'
THUMBS.mkdir(parents=True, exist_ok=True)

doc = Document()
seccion = doc.sections[0]
seccion.left_margin = Inches(0.8)
seccion.right_margin = Inches(0.8)
seccion.top_margin = Inches(0.8)
seccion.bottom_margin = Inches(0.8)

estilo = doc.styles['Normal']
estilo.font.name = 'Calibri'
estilo.font.size = Pt(10)


def titulo(texto, nivel=1):
    doc.add_heading(texto, nivel)


def parrafo(texto, estilo_parrafo=None):
    return doc.add_paragraph(texto, style=estilo_parrafo)


def lista(items):
    for item in items:
        doc.add_paragraph(item, style='List Bullet')


def tabla(cabeceras, filas):
    t = doc.add_table(rows=1, cols=len(cabeceras))
    t.style = 'Table Grid'
    for i, cabecera in enumerate(cabeceras):
        celda = t.rows[0].cells[i]
        celda.text = str(cabecera)
        for run in celda.paragraphs[0].runs:
            run.bold = True
    for fila in filas:
        celdas = t.add_row().cells
        for i, valor in enumerate(fila):
            celdas[i].text = str(valor)
    doc.add_paragraph()
    return t


p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('SKILLY LATAM')
run.bold = True
run.font.size = Pt(26)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('Informe Consolidado de Pruebas y Certificación de Calidad')
run.bold = True
run.font.size = Pt(16)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run('Versión 2.0 — 17 de noviembre de 2026').italic = True
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run('Ejecución real sobre backend Django/DRF, frontend React/Vite y MariaDB local')
doc.add_page_break()

titulo('1. Resumen ejecutivo', 1)
parrafo(
    'Se ejecutó el plan de pruebas del marketplace Skilly Latam sobre una instalación real del '
    'backend y del frontend. La ejecución combinó 570 pruebas automatizadas, 25 peticiones '
    'funcionales E2E con Newman, 27 capturas de interfaz, dos escenarios de carga con Locust y '
    'tres análisis de seguridad. El hallazgo bloqueante H1 (migración MariaDB) fue reproducido, '
    'corregido y verificado con una prueba de regresión dedicada.'
)
lista([
    'IAF — Índice de Aprobación Funcional: 100 % (35/35 aserciones Newman en verde).',
    'IDDC — Índice de Densidad de Defectos Críticos abiertos: 0.',
    'IEC — Índice de Estabilidad bajo Carga: 100 % (1.996/1.996 respuestas sin error 5xx; p95 = 56 ms).',
    'CT — Cobertura de Trazabilidad: 100 % (7/7 casos de uso con escenario normal y de borde).',
    'Cobertura de código Python: 93 % (570 passed, 1 deselected).',
    'Veredicto: CERTIFICADO para el alcance probado, condicionado a resolver los hallazgos de '
    'seguridad no bloqueantes listados en la sección 6.1.'
])

titulo('2. Alcance y entorno real de ejecución', 1)
parrafo(
    'El documento original declaraba Gunicorn con 3 workers, Python 3.14.8, Locust 2.46.7 y '
    'credenciales que no existen en la base sembrada. Se mantuvo el stack funcional del proyecto '
    'y se registró el entorno realmente utilizado:'
)
tabla(
    ['Componente', 'Valor real', 'Observación'],
    [
        ['Backend', 'Django 5.2.7 + Django REST Framework', 'Servidor de desarrollo, 127.0.0.1:8000'],
        ['Lenguaje', 'Python 3.14 (venv .venv)', 'Gunicorn no levantado en esta ejecución'],
        ['Frontend', 'React 18 + Vite 6', 'http://localhost:5173'],
        ['Base de datos', 'MariaDB 13.0.2 local, socket /tmp/opencode/mariadb.sock, puerto 3307', 'Docker no disponible; se usó MariaDB local'],
        ['Pasarela', 'FakeGateway (PAYMENT_GATEWAY=fake)', 'Transbank sandbox no ejecutado en esta corrida'],
        ['Herramientas QA', 'Newman 6.2.3, Playwright, Locust 2.47.0, Bandit 1.9.4, pip-audit 2.10.1', 'Dependencias en requirements-dev.txt y package.json'],
        ['Datos', 'cargar_seed + cargar_demo + datos de QA', 'Credenciales tomadas del seed real'],
    ],
)

titulo('3. Tipos de prueba y trazabilidad', 1)
tabla(
    ['#', 'Tipo de prueba', 'Técnica', 'Ejecución real'],
    [
        ['1', 'Unitarias / integración', 'Caja blanca', 'pytest + Django TestCase + FakeGateway'],
        ['2', 'Funcionales API', 'Caja negra', 'Newman sobre colección CP-FUNC-01..11'],
        ['3', 'Interfaz E2E', 'Caja negra', 'Playwright headless, fullPage: true'],
        ['4', 'Carga y estrés', 'Caja negra', 'Locust nominal y estres'],
        ['5', 'Seguridad', 'Caja blanca / negra', 'Bandit, pip-audit, manage.py check --deploy'],
    ],
)
titulo('3.1 Matriz Caso de Uso / RF', 2)
tabla(
    ['ID CU / RF', 'Módulo', 'Casos ejecutados', 'Estado'],
    [
        ['CU-01 / RF-01', 'Autenticación', 'CP-FUNC-01, CP-FUNC-02', 'OK'],
        ['CU-02 / RF-02', 'Catálogo y detalle', 'CP-FUNC-03', 'OK'],
        ['CU-03 / RF-03', 'Disponibilidad y slots', 'CP-FUNC-04, CP-FUNC-05', 'OK'],
        ['CU-04 / RF-04', 'Reserva invitada y con cuenta', 'CP-FUNC-06, CP-FUNC-06B', 'OK'],
        ['CU-05 / RF-05', 'Pago y estado', 'CP-FUNC-08, CP-FUNC-09', 'OK'],
        ['CU-06 / RF-06', 'Entrega y cierre', 'CP-FUNC-10', 'OK'],
        ['CU-07 / RF-07', 'Postulaciones y archivos', 'CP-FUNC-11-REG', 'OK'],
    ],
)
titulo('3.2 Matriz de requerimientos no funcionales', 2)
tabla(
    ['RNF', 'Atributo', 'Caso técnico', 'Estado'],
    [
        ['RNF-01', 'Rendimiento nominal', 'CP-TEC-01', 'OK'],
        ['RNF-02', 'Estrés', 'CP-TEC-02', 'OK tras ajuste de max_connections'],
        ['RNF-03', 'Idempotencia financiera', 'Suite apps/pagos', 'OK'],
        ['RNF-04', 'Seguridad', 'CP-TEC-04', 'Hallazgos no bloqueantes'],
        ['RNF-05', 'Compatibilidad de esquema', 'CP-TEC-05 / H1', 'OK tras corrección'],
    ],
)

titulo('4. Ejecución funcional E2E', 1)
parrafo(
    'La colección Newman ejecutó 25 peticiones y 35 aserciones con 0 fallos. Se usó el flujo '
    'completo: login, catálogo, slots, reserva invitada, doble reserva rechazada, pago con token '
    'de reserva, retorno idempotente, consulta de estado, reserva autenticada, aceptación y '
    'entrega, creación de postulación, rechazo de archivo >5 MB y panel admin.'
)
tabla(
    ['Métrica', 'Valor'],
    [
        ['Peticiones', '25'],
        ['Aserciones', '35'],
        ['Fallos', '0'],
        ['Duración total', '2,8 s'],
        ['Latencia media', '92 ms'],
        ['Evidencia', 'evidencia/api/newman.html, newman.json, newman.log'],
    ],
)
tabla(
    ['Caso', 'Resultado esperado', 'Resultado obtenido', 'Estado'],
    [
        ['CP-FUNC-01', 'HTTP 200 + JWT', 'HTTP 200 + access/refresh', 'OK'],
        ['CP-FUNC-02', '401 y 400', '401 y 400', 'OK'],
        ['CP-FUNC-03', 'Listado y detalle con perfil público', '200; sin email/RUT privados', 'OK'],
        ['CP-FUNC-04', '18 slots, bloqueo 3 h', '18 slots, bloqueo_horas=3', 'OK'],
        ['CP-FUNC-05', 'Segunda reserva solapada rechazada', 'HTTP 400', 'OK'],
        ['CP-FUNC-06', 'Reserva invitada con token', 'HTTP 201 + token', 'OK'],
        ['CP-FUNC-08', 'Pago iniciado y retorno 302', '200 + token, retorno 302', 'OK'],
        ['CP-FUNC-09', 'Consulta de estado pública', 'HTTP 200, estado retenido/liberado', 'OK'],
        ['CP-FUNC-10', 'Ciclo aceptar → entregado → finalizada', 'HTTP 200 en los tres pasos', 'OK'],
        ['CP-FUNC-11-REG', 'Archivo >5 MB rechazado', 'HTTP 400', 'OK'],
    ],
)

titulo('5. Hallazgo bloqueante H1 y regresión', 1)
parrafo(
    'Se reprodujo el fallo reportado en MariaDB: el modelo Certificado definía archivo como '
    'FileField(max_length=5 * 1024 * 1024). Django traduce ese valor a VARCHAR(5242880), que '
    'excede el máximo de 16.383 bytes por columna VARCHAR UTF-8 en MariaDB.'
)
tabla(
    ['Fase', 'Evidencia', 'Resultado'],
    [
        ['Reproducción', 'evidencia/funcional/CP-FUNC-11_fallo_migrate.log', 'OperationalError (1074)'],
        ['Corrección', 'apps/postulaciones/models.py:235 y migration 0001 regenerada', 'FileField sin max_length'],
        ['Corrección extendida', 'apps/reservas/models.py y migration 0003', 'Mismo patrón en EvidenciaDisputa'],
        ['Migración limpia', 'evidencia/funcional/CP-FUNC-11-REG_migrate_ok.log', '45 migraciones OK'],
        ['Regresión', 'evidencia/funcional/CP-FUNC-11-REG_pytest.log', '2 passed'],
        ['Suite completa', 'evidencia/automatizacion/pytest_full.log', '570 passed, 1 deselected'],
    ],
)
parrafo(
    'Se agregó TestRegresionH1ColumnasArchivo para impedir que un FileField vuelva a declarar '
    'un max_length superior a 255. La prueba falla primero con el valor original y pasa tras la '
    'corrección.'
)

titulo('6. Pruebas técnicas', 1)
titulo('6.1 Seguridad', 2)
tabla(
    ['Herramienta', 'Resultado', 'Interpretación'],
    [
        ['Bandit', '982 hallazgos LOW; 0 MEDIUM/CRITICAL', 'Principalmente assert en tests y contraseñas del seed'],
        ['pip-audit', '66 vulnerabilidades en 4 paquetes', 'certifi 2, django 59, djangorestframework 3, marshmallow 2'],
        ['check --deploy', '38 avisos', 'Avisos de drf_spectacular y configuración; no bloquea el arranque'],
    ],
)
lista([
    'Recomendación prioritaria: actualizar Django, DRF, certifi y marshmallow a versiones parcheadas.',
    'Mantener Bandit excluyendo tests o marcar los asserts como expected en la configuración del proyecto.',
    'Revisar encabezados de seguridad y HSTS antes de exponer el servicio a Internet.',
])
titulo('6.2 Carga y estrés', 2)
tabla(
    ['Escenario', 'Usuarios', 'Solicitudes', 'Fallos', 'p50', 'p95', 'p99', 'Throughput'],
    [
        ['Nominal', '20 (rampa 5/s, 60 s)', '1.996', '0', '12 ms', '56 ms', '200 ms', '33,75 req/s'],
        ['Estrés', '100 (rampa 20/s, 60 s)', '8.112', '0', '78 ms', '370 ms', '600 ms', '136,95 req/s'],
    ],
)
parrafo(
    'Durante la primera ejecución de estrés aparecieron 10 respuestas 500 por agotamiento de '
    'conexiones MariaDB (error 1040 Too many connections, max_connections=151). Véase '
    'evidencia/carga/CP_CARGA_01_max_conexiones.log. Trabajando con un solo proceso de desarrollo '
    'y sin pooler, el límite se alcanzó al superar 100 usuarios simultáneos.'
)
parrafo(
    'Se ajustó el parámetro del servidor MariaDB a max_connections=500 '
    '(evidencia/carga/mariadb_tuning.log) y se repitió el escenario de estrés: 8.112 solicitudes, '
    '0 fallos y p95 de 370 ms.'
)
parrafo(
    'Evidencia: evidencia/carga/nominal.html, nominal_stats.csv, estres.html, estres_stats.csv, '
    'estres_failures.csv y locustfile.py.'
)

titulo('7. Evidencia de interfaz', 1)
parrafo(
    'Se capturaron 27 pantallas con Playwright en modo headless y fullPage: true, cubriendo '
    'home, catálogo, servicio, programación, reserva, login, postulación, panel de organización, '
    'panel profesional y panel administrativo. Las imágenes originales están en evidencia/ui/.'
)
for i, archivo in enumerate(sorted((EVID / 'ui').glob('*.png')), start=1):
    with Image.open(archivo) as imagen:
        imagen = imagen.convert('RGB')
        escala = min(1400 / imagen.width, 1200 / imagen.height, 1)
        nueva = imagen.resize((int(imagen.width * escala), int(imagen.height * escala)))
        destino = THUMBS / archivo.name
        nueva.save(destino, optimize=True)
    doc.add_picture(str(destino), width=Inches(6.3))
    doc.add_paragraph(f'Figura {i}. {archivo.stem}', style='Caption')

titulo('8. Métricas de certificación', 1)
tabla(
    ['Métrica', 'Fórmula', 'Umbral', 'Obtenido', 'Resultado'],
    [
        ['IAF', 'Aprobadas / Ejecutadas × 100', '≥ 95 %', '35/35 = 100 %', 'CUMPLE'],
        ['IDDC', 'Defectos críticos abiertos', '0', '0', 'CUMPLE'],
        ['IEC', 'Sin error 5xx / Total nominal × 100', '100 % y p95 ≤ 500 ms', '100 %; p95 56 ms', 'CUMPLE'],
        ['CT', 'CU con normal y borde / Total CU × 100', '100 %', '7/7 = 100 %', 'CUMPLE'],
    ],
)
parrafo(
    'Las cuatro compuertas de calidad se cumplen. La certificación queda condicionada a la '
    'remediación de las vulnerabilidades conocidas de dependencias, que no bloquean el flujo '
    'funcional pero sí deben tratarse antes de un despliegue público.'
)

titulo('9. Conclusiones y plan de mejora', 1)
lista([
    'El flujo de reserva sin cuenta funciona de extremo a extremo y está protegido por token público.',
    'La corrección de H1 elimina el bloqueo de migraciones en MariaDB y cuenta con regresión automática.',
    'La regla de bloqueo de 3 horas y la idempotencia del retorno de pago se comportan según lo especificado.',
    'Bajo estrés real se detectó un límite operativo de conexiones; documentar max_connections y pool de conexiones en el despliegue.',
    'Actualizar dependencias con vulnerabilidades conocidas y configurar throttling en /api/auth/token/.',
    'Ejecutar migraciones siempre contra MariaDB en CI, no solo contra SQLite, para evitar regresiones de esquema.',
])

titulo('10. Inventario de evidencias', 1)
tabla(
    ['Categoría', 'Ruta', 'Contenido'],
    [
        ['API', 'evidencia/api/newman.html / newman.json / newman.log', 'Colección y resultados Newman'],
        ['Automatización', 'evidencia/automatizacion/pytest_full.log / pytest.xml', '570 pruebas'],
        ['Cobertura', 'evidencia/automatizacion/cobertura.log / cobertura/', '93 % de cobertura'],
        ['Funcional', 'evidencia/funcional/', 'H1 reproduction, fix y regresión'],
        ['Seguridad', 'evidencia/seguridad/', 'Bandit, pip-audit y check --deploy'],
        ['UI', 'evidencia/ui/', '27 capturas fullPage + capturas.log'],
        ['Carga', 'evidencia/carga/', 'Locust HTML/CSV y tuning de MariaDB'],
        ['Postman', 'evidencia/postman/', 'Colección, environment y archivo >5 MB'],
        ['Informe', 'evidencia/informe/', 'Este documento en DOCX y PDF'],
    ],
)

salida = OUT / 'Informe_Pruebas_Skilly_Latam.docx'
doc.save(salida)
print(salida)
