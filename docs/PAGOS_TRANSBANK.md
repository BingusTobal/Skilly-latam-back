# Especificación del módulo de pagos — Transbank Webpay Plus (Sprint 4)

> **Para el agente (opencode):** lee primero `AGENTS.md` y luego este documento completo.
> Para todo lo relacionado con pagos, **este documento prevalece** sobre cualquier otro.
> No avances de fase sin que el usuario lo autorice. Si algo es ambiguo o no puedes
> verificarlo en la documentación oficial, **detente y pregunta**; no inventes.

---

## 1. Alcance

**Entra en este sprint**
- Modelo `Pago` con máquina de estados y bitácora inmutable (`PagoEvento`).
- Pasarela detrás de una interfaz (puerto): `FakeGateway` y `TransbankGateway`.
- Flujo con **Webpay Plus Captura Diferida** (autorizar al reservar, capturar al aceptar el profesional).
- Retorno desde Webpay, captura, reembolso/reversa y tareas de conciliación (Celery).
- Pruebas automatizadas con pasarela simulada y un set opcional contra el ambiente de integración.

**No entra**
- Pago por transferencia bancaria (Webpay no lo ofrece; queda deshabilitado en el MVP).
- Mercado Pago (futuro: será otro adaptador de la misma interfaz).
- Pago real al profesional (liquidación). `liberado` solo registra la obligación; ver §9.
- Ambiente de producción. Transbank solo valida integraciones con un código de comercio
  productivo propio; el proyecto opera **siempre en ambiente de integración**.

---

## 2. Prerrequisitos (hacer ANTES de conectar Transbank)

1. **Corregir la doble reserva del mismo horario.** En `reservas/services.py`, `crear_reserva`
   revisa el slot y luego inserta, sin bloqueo. Al inicio de la transacción, bloquear la fila del
   profesional: `Profesional.objects.select_for_update().get(pk=servicio.profesional_id)`.
   Agregar prueba de concurrencia. Con pagos reales, una doble reserva obliga a reembolsos.
2. **Montos en CLP enteros.** Transbank recibe CLP sin decimales; el modelo usa `DecimalField(10, 2)`.
   Regla: el precio de un `Servicio` debe ser entero y ≥ $5.000 (validador + migración). Convertir con
   `int(valor.to_integral_exact())` y **fallar** si el decimal no es entero.
3. **Decisión de plazo de respuesta del profesional** (hoy 6 h en settings; los mockups dicen 24 h).
   Esperar la decisión del usuario; no tocar ese valor por iniciativa propia.

---

## 3. Datos a verificar en la documentación oficial (obligatorio, antes de codificar)

Fuente: https://www.transbankdevelopers.cl (sección Webpay Plus, API REST y SDK de Python).
Escribe los resultados en `docs/PAGOS_TRANSBANK_VERIFICACION.md`, con la URL de cada dato.

| Dato | Lo que se cree hoy | Confirmar |
|---|---|---|
| SDK oficial de Python | paquete `transbank-sdk` (usar solo el oficial; **no** clientes de terceros) | Nombre exacto y versión en PyPI |
| Código de comercio de integración, Captura Diferida | `597055555540` (CLP) | Página de documentación |
| API Key Secret de integración | publicada en la documentación oficial | Copiarla desde allí al `.env`, nunca al repositorio |
| Longitud máxima de `buy_order` y `session_id` | 26 y 61 caracteres | Referencia de "crear transacción" |
| Plazo para confirmar (commit) tras el pago | del orden de minutos | Referencia de "confirmar transacción" |
| Ventana para capturar una autorización | 7 días (ya en `DIAS_VENTANA_AUTORIZACION_WEBPAY`) | Referencia de captura diferida |
| Captura diferida con débito y prepago | se cree que **solo aplica a crédito** | Documentación del producto |
| Reembolso parcial y reverso de una autorización sin captura | puede variar según tipo de tarjeta | Referencia de "reembolsar" |
| Método de retorno a `return_url` (GET o POST) y parámetros de abandono (`TBK_TOKEN`, `TBK_ORDEN_COMPRA`, `TBK_ID_SESION`) | ambos métodos, según el caso | Documentación del flujo |
| Notificaciones servidor a servidor (webhooks) | se cree que **no existen** | Documentación del flujo |
| Tarjetas de prueba | las oficiales | Documentación oficial; no inventar números |

Si algún dato difiere de lo supuesto aquí, **gana la documentación oficial** y se avisa al usuario.

---

## 4. Modelo de dominio

### 4.1 `Pago` (app `pagos`)
Relación con `Reserva`: una reserva puede tener varios intentos (`Pago`), pero **a lo más uno activo**.
MariaDB **no soporta índices únicos parciales**: no uses `UniqueConstraint(condition=...)`.
Garantiza la unicidad del pago activo bloqueando la fila de la `Reserva` con `select_for_update`.

Campos mínimos:
- `reserva` (FK), `referencia_publica` (UUID, único; es lo único que sale hacia el frontend)
- `estado`, `pasarela` (`fake` | `transbank`)
- `monto_total`, `monto_comision`, `monto_neto` (enteros CLP; se calculan **una vez**, al crear el pago,
  con redondeo `ROUND_HALF_UP`, y siempre se cumple `neto + comisión == total`)
- `buy_order` (único), `session_id`, `token` (único, indexado; trátalo como secreto)
- `codigo_autorizacion`, `tipo_pago` (`payment_type_code`), `cuotas`, `tarjeta_ultimos4`, `codigo_respuesta`
- `capturado_en_autorizacion` (booleano; ver §4.3)
- `monto_reembolsado`, marcas de tiempo por hito y `respuesta_pasarela` (JSON **sanitizado**)

### 4.2 `PagoEvento` (bitácora inmutable)
Una fila por cada transición o llamada a la pasarela: `pago`, `de_estado`, `a_estado`, `motivo`,
`actor` (`usuario` | `profesional` | `sistema` | `admin`), `datos` (JSON sanitizado), `creado_en`.
Sin `update` ni `delete` (sobrescribir `save`/`delete` para que lancen error y no registrarlo en el admin como editable).

### 4.3 Estados y transiciones

| Estado | Significado |
|---|---|
| `iniciado` | Token creado en Transbank; el usuario está en Webpay. |
| `autorizado` | Commit exitoso con tarjeta de crédito: cupo reservado, **sin cobrar**. |
| `capturando` | Transitorio: captura en curso (evita mantener bloqueos durante la llamada HTTP). |
| `retenido` | Capturado: el dinero está en la cuenta de Skilly. |
| `liberado` | Entrega confirmada: el neto corresponde al profesional. |
| `reembolsado` | Reembolso total o parcial ejecutado en Transbank. |
| `cancelado` | Autorización revocada sin cargo. |
| `rechazado` | Transbank rechazó, o el usuario abandonó el pago. |
| `expirado` | Token sin completar, o autorización vencida sin captura. |
| `revision_manual` | Error irrecuperable o inconsistencia; requiere a un humano. |

Transiciones permitidas (cualquier otra lanza `TransicionInvalida`):

```
iniciado   -> autorizado | rechazado | expirado
autorizado -> capturando | cancelado | expirado
capturando -> retenido | autorizado (si la captura falla y se puede reintentar) | revision_manual
retenido   -> liberado | reembolsado | revision_manual
liberado   -> reembolsado   (solo vía disputa resuelta por un administrador)
```

**Débito y prepago.** Según la documentación (verificar en §3), solo el crédito admite captura diferida;
el débito se cobra al confirmar. Si `tipo_pago` es débito o prepago: marcar `capturado_en_autorizacion=True`,
pasar directo a `retenido` y, si luego el profesional rechaza o vence, **reembolsar** (no "cancelar").
Cubrir ambos caminos con pruebas.

---

## 5. Arquitectura

```
apps/pagos/
├── models.py            # Pago, PagoEvento
├── estados.py           # constantes y tabla de transiciones
├── services.py          # único lugar con lógica: iniciar, confirmar, capturar, reembolsar, liberar
├── gateway/
│   ├── base.py          # PaymentGateway (ABC): crear, confirmar, estado, capturar, reembolsar
│   ├── fake.py          # simulada y configurable (reemplaza apps/reservas/pagos.py)
│   └── transbank.py     # adaptador del SDK oficial
├── views.py             # iniciar pago, retorno y consulta de estado
├── tasks.py             # Celery: expirar, conciliar
├── throttles.py
└── tests/
```

- `reservas/services.py` **solo** llama a `pagos.services`; nunca a la pasarela ni al SDK.
- La pasarela se elige con `PAYMENT_GATEWAY` (`fake` | `transbank`). Un adaptador nuevo (Mercado Pago)
  no debe requerir cambios en `reservas`.
- Eliminar `apps/reservas/pagos.py` cuando todas sus llamadas migren. Buscar los usos con `grep`.

### Variables de entorno (agregar a `.env.example`, sin valores reales)
`PAYMENT_GATEWAY`, `TRANSBANK_ENV` (`integration` | `production`), `TRANSBANK_COMMERCE_CODE`,
`TRANSBANK_API_KEY_SECRET`, `TRANSBANK_RETURN_URL`, `FRONTEND_PAYMENT_RESULT_URL`,
`MINUTOS_PAGO_PENDIENTE` (por defecto 15).

**Validaciones al arrancar** (fallar con `ImproperlyConfigured`):
- `DEBUG=False` con `PAYMENT_GATEWAY=fake`.
- `PAYMENT_GATEWAY=transbank` sin código de comercio o sin secreto.
- `TRANSBANK_ENV=production` con un código de comercio de integración.

---

## 6. Flujos

### 6.1 Cambio en la reserva: nuevo estado `pendiente_pago`
Con pago real, la reserva se crea **antes** de que el usuario pague.
- Agregar `pendiente_pago` a los estados de `Reserva`. **Bloquea el horario** durante `MINUTOS_PAGO_PENDIENTE`.
- El reloj de respuesta del profesional **empieza al autorizarse el pago**, no al crear la reserva.
- Si el pago no se autoriza a tiempo: la reserva pasa a `cancelada`, se libera el horario y el pago a `expirado`.

### 6.2 Iniciar el pago — `POST /api/reservas/{ref}/pago/iniciar/`
1. Permiso: dueño de la reserva (JWT) o portador del enlace de acceso de invitado. Verificar propiedad.
2. Bloquear la `Reserva` (`select_for_update`). Debe estar en `pendiente_pago`. Si ya hay un `Pago` en `iniciado`
   y vigente, devolver el mismo; si no, crear uno nuevo.
3. El **monto sale del servidor** (snapshot de la reserva). Nunca aceptar monto, moneda ni descripción del cliente.
4. `buy_order` = prefijo + id + sufijo aleatorio, respetando el largo máximo. No usar un correlativo adivinable solo.
5. Crear la transacción en la pasarela (**fuera** de la transacción de base de datos). Guardar el token y devolver `{url, token}`.

### 6.3 Retorno desde Webpay — `GET|POST /api/pagos/transbank/retorno/`
Vista pública, exenta de CSRF **solo esta**, con throttling. Lo único que lee del request es el token.
Casos:
- **Con `token_ws`:** llamar a *confirmar* en la pasarela. Es obligatorio, nunca asumir que el pago salió bien.
- **Abandono** (`TBK_TOKEN` sin `token_ws`): `rechazado`.
- **Timeout o error de formulario:** ver la documentación; tratar como `rechazado` o `expirado`.

Reglas del commit:
1. Buscar el `Pago` **por token** y bloquearlo (`select_for_update`). Nunca por un id enviado por el cliente.
2. **Idempotente:** si el pago ya no está en `iniciado`, no volver a confirmar; redirigir con el estado guardado
   (refrescar la página o doble clic no debe romper nada). Si Transbank dice "ya confirmada", consultar `estado`.
3. Validar de la respuesta: código de respuesta de aprobación, `amount == pago.monto_total`, `buy_order` y `session_id`
   propios. **Cualquier discrepancia** => no activar la reserva, revertir la transacción en Transbank y dejar
   `revision_manual` con alerta.
4. Éxito con crédito => `autorizado`; con débito/prepago => `retenido` (ver §4.3). La reserva pasa a
   `pendiente_aceptacion`, se inicia el reloj del profesional y se envían los correos (con `transaction.on_commit`).
5. Responder con **302** a `FRONTEND_PAYMENT_RESULT_URL?ref=<referencia_publica>&estado=<ok|fallo|abandono>`.
   **No** poner token, `buy_order` ni montos en la URL.

### 6.4 Aceptación del profesional => captura (patrón obligatorio)
No mantener bloqueos de base de datos durante una llamada HTTP externa. Tres fases:

```python
def aceptar_y_capturar(reserva_id, profesional):
    # Fase 1: validar y marcar (corta, con bloqueo)
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
        pago = Pago.objects.select_for_update().get(reserva=reserva, estado__in=ACTIVOS)
        validar_puede_aceptar(reserva, pago, profesional)   # dueño, plazo vigente, estado correcto
        if not pago.capturado_en_autorizacion:
            pago.pasar_a(CAPTURANDO, actor="profesional", motivo="inicio de captura")

    # Fase 2: llamada externa (SIN transacción abierta)
    resultado = None if pago.capturado_en_autorizacion else gateway.capturar(pago)

    # Fase 3: confirmar el resultado (corta, con bloqueo)
    with transaction.atomic():
        reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
        pago = Pago.objects.select_for_update().get(pk=pago.pk)
        if resultado is None or resultado.ok:
            pago.pasar_a(RETENIDO, actor="profesional", motivo="capturado")
            transicionar(reserva, EN_CURSO)
        else:
            pago.pasar_a(AUTORIZADO, actor="sistema", motivo="captura fallida")  # o revision_manual
            # la reserva se mantiene; notificar a organización y profesional
```

Una autorización admite **una sola captura**. Si la captura devuelve "ya capturada", consultar el estado en
Transbank y reconciliar; no reintentar a ciegas.

### 6.5 Liberación (organización confirma, o auto-liberación a los 5 días)
`retenido => liberado`, en la misma transacción que `reserva => finalizada`. No hay llamada a Transbank.
Si existe una disputa abierta, la auto-liberación **no** ocurre. Ver §9 sobre el pago al profesional.

### 6.6 Rechazo, vencimiento y cancelación
| Situación | Pago en `autorizado` (crédito) | Pago en `retenido` |
|---|---|---|
| Profesional rechaza o vence | Revocar autorización => `cancelado` | Reembolso total => `reembolsado` |
| Organización cancela antes de aceptar | Revocar => `cancelado` | — |
| Cancela con ≥ 24 h de anticipación | — | Reembolso 100 % |
| Cancela con < 24 h | — | Reembolso 90 % (el saldo queda para el profesional) |
| Disputa resuelta a favor de la organización | — | Reembolso según la resolución |

El monto del reembolso lo calcula `pagos.services` con una función pura y probada, en CLP enteros.
Si la pasarela falla al reembolsar, el pago queda en `revision_manual` con evento y alerta; **nunca**
marcar `reembolsado` sin confirmación de Transbank. Revisar en §3 cómo se revoca una autorización
sin captura y si el reembolso parcial está permitido para el tipo de tarjeta.

### 6.7 Tareas Celery
- **Cada minuto:** expirar reservas en `pendiente_pago` vencidas (libera horario, pago a `expirado`).
- **Cada 5 minutos (conciliación):** para pagos en `iniciado` o `capturando` con antigüedad mayor a un umbral,
  consultar `estado` en Transbank y corregir. Es la red de seguridad porque no hay webhooks.
- **Diaria:** alertar autorizaciones próximas a vencer su ventana de captura.
- Todas idempotentes, con bloqueo por fila, y registran evento por cada cambio.

---

## 7. Reglas de seguridad (checklist obligatorio)

**Datos de tarjeta**
1. La tarjeta se ingresa **solo en Webpay**. Ningún endpoint, formulario ni log de Skilly recibe número, CVV ni vencimiento.
2. Guardar solo los **últimos 4 dígitos** que devuelve Transbank. Nunca el número completo.
3. `respuesta_pasarela` y los logs pasan por una función `sanear()` que elimina número de tarjeta, token y secretos.

**Integridad del monto**
4. El monto siempre sale del servidor. Se compara con el monto de la respuesta de Transbank antes de activar nada.
5. Montos en enteros CLP; conversión estricta; los tres montos de la reserva se calculan una vez y se guardan.

**Autenticidad y autorización**
6. Ningún cambio de estado se basa en el navegador del usuario: solo en **confirmar** y **estado** contra Transbank.
7. El token es secreto y de un solo uso: no va en URLs del frontend, no se registra completo en logs (solo los primeros 6 caracteres).
8. Cada endpoint verifica propiedad: el pago se busca por token o `referencia_publica`, nunca por un id incremental.
9. La vista de retorno está exenta de CSRF **únicamente** ella, con throttling, y es segura porque valida todo con Transbank.
10. Iniciar pago tiene throttling por usuario/IP para evitar creación masiva de transacciones.

**Concurrencia**
11. Toda transición de `Pago` y `Reserva` usa `select_for_update` dentro de `transaction.atomic`.
12. Nunca se hace una llamada HTTP a la pasarela con una transacción de base de datos abierta (patrón de §6.4).
13. Todas las operaciones son idempotentes: repetir el retorno, la captura o una tarea no duplica efectos.

**Secretos y entorno**
14. Código de comercio y secreto solo por variables de entorno. Nada en el repositorio, ni en pruebas, ni en capturas.
15. El arranque falla con configuraciones inseguras (§5).
16. `PagoEvento` es inmutable y registra actor, motivo y datos sanitizados de cada transición.

**Sin atajos**
17. Prohibido un endpoint "marcar como pagado" accesible desde el frontend o el panel, salvo una acción de administrador
    auditada que pase por `pagos.services` y deje evento.
18. Si una respuesta de Transbank es inesperada: `revision_manual` y alerta, no suposiciones.

---

## 8. Pruebas

Usar `FakeGateway` configurable (aprueba, rechaza, falla, tarda, devuelve montos distintos). Cobertura mínima de
**90 %** en `apps/pagos`. Casos obligatorios:

- Recorrido completo: iniciar => retorno => aceptar => capturar => entregar => liberar.
- Retorno repetido (doble clic o refresco): un solo efecto.
- Monto de la respuesta distinto del esperado: no activa la reserva y deja `revision_manual`.
- Abandono, timeout y rechazo de la tarjeta.
- Captura que falla, y captura "ya realizada".
- Débito: se cobra al confirmar; el rechazo del profesional genera un reembolso, no una cancelación.
- Reembolso 100 % y 90 %, con redondeo en CLP y `neto + comisión == total`.
- Vencimiento de `pendiente_pago` libera el horario.
- Transiciones inválidas lanzan `TransicionInvalida`.
- Seguridad: la URL de redirección no contiene token ni monto; los logs no contienen número de tarjeta; un usuario
  ajeno no puede iniciar el pago de otra reserva.
- Concurrencia (marcar `@pytest.mark.mariadb`, ya que SQLite no prueba bien los bloqueos): dos retornos simultáneos y
  dos reservas simultáneas del mismo horario.

Pruebas contra el ambiente de integración de Transbank: marcar `@pytest.mark.sandbox`, **excluidas por defecto**, ejecución manual.
Las tarjetas de prueba salen de la documentación oficial.

---

## 9. Fuera de alcance, pero con su gancho

- **Pago al profesional.** `liberado` solo significa que el neto le corresponde. No automatices transferencias en este
  sprint: crea el estado de liquidación (`pendiente` | `pagada`) y una acción de administrador auditada para marcarla.
- **Boleta de honorarios y factura:** se generan a partir de los montos guardados en `Pago`, en un sprint posterior.
- **Operación con dinero real:** antes de ello, el equipo debe consultar a Transbank y a un asesor legal sobre el rol de
  intermediario que retiene fondos de terceros.

---

## 10. Plan por fases (no avanzar sin autorización del usuario)

| Fase | Entregable | Criterio de aceptación |
|---|---|---|
| **0** | Prerrequisitos de §2 y verificación de §3 | Doble reserva corregida con prueba; documento de verificación completo |
| **1** | Modelo `Pago` + `PagoEvento`, estados, `FakeGateway`, estado `pendiente_pago`, refactor de `reservas` hacia `pagos.services` | Suite verde con la pasarela simulada; `apps/reservas/pagos.py` eliminado |
| **2** | `TransbankGateway` (ambiente de integración), iniciar pago y retorno | Pago de prueba completo en integración; pruebas `sandbox` documentadas |
| **3** | Captura, reembolsos y tareas Celery | Flujos de §6.4 a §6.7 con pruebas, incluida la concurrencia |
| **4** | Endurecimiento | Checklist de §7 verificada punto por punto, con evidencia, y revisión con Sonar |

---

## 11. Instrucción inicial para pegar en opencode

```
Lee AGENTS.md y docs/PAGOS_TRANSBANK.md completos.
Trabaja SOLO la Fase 0.
1) Corrige la doble reserva (select_for_update en crear_reserva) con su prueba.
2) Verifica en transbankdevelopers.cl cada fila de la sección 3 y escribe los resultados,
   con la URL de cada dato, en docs/PAGOS_TRANSBANK_VERIFICACION.md.
3) Antes de escribir código de la Fase 1, muéstrame el plan de archivos y espera mi aprobación.
Reglas: no instales paquetes sin preguntarme; no toques apps ajenas a pagos y reservas;
no inventes datos de la API de Transbank (si no lo encuentras, dilo); no avances de fase
sin mi autorización; cada fase termina con la suite en verde.
```
