# Verificación oficial de Transbank Webpay Plus (Fase 0)

Fecha de verificación: 2026-11-05
SDK: `transbank-sdk==6.1.0` (PyPI), probado en Python 3.14.9.
Alcance: datos de la tabla §3 de `docs/PAGOS_TRANSBANK.md` y hallazgos que
afectan el diseño del módulo `pagos`.

Fuentes consultadas:

- <https://www.transbankdevelopers.cl/documentacion/webpay-plus>
- <https://www.transbankdevelopers.cl/documentacion/como_empezar>
- <https://www.transbankdevelopers.cl/producto/webpay>
- <https://github.com/TransbankDevelopers/transbank-sdk-python>
- Introspección del SDK instalado en `.venv` (firmas y constantes).

---

## 1. Resultado de la tabla §3

| Dato | Resultado confirmado | Fuente |
|---|---|---|
| SDK oficial de Python | Paquete `transbank-sdk`, instalado `6.1.0`. Requiere Python 3.12+. Instalación: `pip install transbank-sdk`. | PyPI / GitHub del SDK |
| Código de comercio de integración, Captura Diferida | `597055555540` (CLP). | `como_empezar#ambiente-de-integracion` |
| API Key Secret de integración | Publicada en la misma página para todos los códigos de comercio de integración. **No se transcribe en el repositorio**: se copia al `.env` local en `TRANSBANK_API_KEY_SECRET`. | `como_empezar#ambiente-de-integracion` |
| Longitud máxima de `buy_order` y `session_id` | 26 y 61 caracteres. | SDK 6.1.0: `ApiConstants.BUY_ORDER_LENGTH=26`, `SESSION_ID_LENGTH=61`; referencia del API REST |
| Plazo para confirmar (commit) tras el pago | El token de `create()` vive **5 minutos**. El formulario de Webpay permanece 4 minutos en producción y 10 minutos en integración; al excederse, la transacción se aborta. | `webpay-plus`, secciones "Crear una transacción" y "Flujo en caso de éxito" |
| Ventana para capturar una autorización | **7 días calendario**. Superado el plazo, la retención se reversa automáticamente y el cupo se libera. | `producto/webpay`, "Autorización y Captura" |
| Captura diferida con débito y prepago | **Solo aplica a crédito**. En débito Redcompra y prepago la autorización y captura son **siempre simultáneas**. | `producto/webpay`, "Autorización y Captura" |
| Reembolso parcial y reverso de una autorización sin captura | Reversa: antes de 3 horas de la confirmación, por el monto total, en crédito, débito o prepago. Pasadas 3 horas se ejecuta una anulación (plazo de 90 días). En crédito: anulación total para venta normal, cuotas emisor y cuotas comercio; anulación parcial solo para venta normal y cuotas emisor. En débito/prepago se permite anulación total y parcial (API v1.2+). **No se documenta un método explícito de anulación/reversa para una autorización con captura diferida sin capturar**; la documentación solo indica que la retención se libera sola a los 7 días. | `producto/webpay`, "Anulaciones y Reversas" |
| Método de retorno a `return_url` y parámetros de abandono | Flujo normal: GET con `token_ws` (API v1.1+). Abandono con "anular": GET con `TBK_TOKEN`, `TBK_ORDEN_COMPRA`, `TBK_ID_SESION` (en integración el retorno de abandono es POST). Timeout del formulario: `TBK_ID_SESION` y `TBK_ORDEN_COMPRA`, **sin token**. Error con "volver al sitio": llegan `token_ws`, `TBK_TOKEN`, `TBK_ID_SESION`, `TBK_ORDEN_COMPRA`. | `webpay-plus`, "Resumen de flujos" |
| Notificaciones servidor a servidor (webhooks) | **No existen** en Webpay Plus. El retorno es por redirección y la conciliación se hace con `commit`/`status`. `status` permite consultar la transacción durante 7 días desde su creación. | `webpay-plus`, flujo y sección de estado |
| Tarjetas de prueba | Ver tabla en la sección 3. | `como_empezar#ambiente-de-integracion` |

Datos adicionales confirmados:

- Host de integración: `https://webpay3gint.transbank.cl`
- Host de producción: `https://webpay3g.transbank.cl`
- `return_url`: máximo 255 caracteres.
- `token`: 64 caracteres; tratarlo como secreto.
- `authorization_code`: 6 caracteres.
- Código de comercio: 12 caracteres.
- En captura diferida **no se permite venta en cuotas con intereses**.
- Una autorización admite **una única captura**, por un monto menor o igual al autorizado.
- La captura puede ser total o parcial (el monto capturado no puede superar el autorizado).

---

## 2. Contrato del SDK 6.1.0 verificado en el entorno

```python
from transbank.webpay.webpay_plus.transaction import Transaction
from transbank.common.options import WebpayOptions
from transbank.common.integration_type import IntegrationType

tx = Transaction(
    WebpayOptions(
        commerce_code="597055555540",
        api_key="<TRANSBANK_API_KEY_SECRET>",
        integration_type=IntegrationType.TEST,
    )
)
# Alternativa equivalente:
tx = Transaction.build_for_integration("597055555540", "<TRANSBANK_API_KEY_SECRET>")
```

Firmas reales (introspección del paquete instalado):

```text
create(buy_order: str, session_id: str, amount: float, return_url: str)
commit(token: str)
status(token: str)
capture(token: str, buy_order: str, authorization_code: str, capture_amount: float)
refund(token: str, amount: float)
```

Hallazgos:

- **No existe `Transaction.cancel()`**. Para reversa/anulación se usa `refund(token, amount)`.
- `amount` y `capture_amount` son `float` en el SDK, pero el dominio de Skilly
  trabaja en **enteros CLP**. Convertir explícitamente y no aceptar decimales.
- Endpoints REST usados por el SDK:
  - `POST /rswebpaytransaction/api/webpay/v1.2/transactions/`
  - `PUT /rswebpaytransaction/api/webpay/v1.2/transactions/{token}`
  - `GET /rswebpaytransaction/api/webpay/v1.2/transactions/{token}`
  - `POST /rswebpaytransaction/api/webpay/v1.2/transactions/{token}/capture`
  - `POST /rswebpaytransaction/api/webpay/v1.2/transactions/{token}/refunds`
- `status(token)` devuelve el estado de la transacción. Una transacción se
  considera aprobada solo si `response_code == 0` y `status == "AUTHORIZED"`.
- El campo `type` aparece en la respuesta de `refund`, pero los valores
  `REVERSED`/`NULLIFIED` **no están enumerados** en la documentación consultada.
  No basar la lógica en ese campo; usar `response_code`.

---

## 3. Tarjetas de prueba oficiales

| Tipo | Número | CVV | Resultado |
|---|---|---|---|
| VISA | `4051 8856 0044 6623` | `123` | Aprobada |
| AMEX | `3700 0000 0002 032` | `1234` | Aprobada |
| MASTERCARD | `5186 0595 5959 0568` | `123` | Rechazada |
| Redcompra | `4051 8842 3993 7763` | — | Aprobada (débito Redcompra) |
| Redcompra | `4511 3466 6003 7060` | — | Aprobada (débito Redcompra) |
| Redcompra | `5186 0085 4123 3829` | — | Rechazada (débito Redcompra) |
| Prepago VISA | `4051 8860 0005 6590` | `123` | Aprobada |
| Prepago MASTERCARD | `5186 1741 1062 9480` | `123` | Rechazada |

Cualquier fecha de expiración futura sirve. Cuando aparezca autenticación
bancaria: RUT `11.111.111-1`, clave `123`.

---

## 4. Hallazgos que afectan el plan

1. **No hay `cancel` en el SDK.** La reversa/anulación se hace con `refund`.
   El plan debe hablar de "reversa/anulación vía `refund`", no de `cancel`.

2. **Token de 5 minutos vs. ventana de pago de 15 minutos.** El token de
   `create()` expira a los 5 minutos, pero el formulario de integración puede
   estar abierto 10 minutos. `MINUTOS_PAGO_PENDIENTE=15` se mantiene como
   ventana de la reserva sin pago iniciado. Para un `Pago` en `iniciado`, el
   commit debe manejar el error de token expirado y marcarlo `expirado` sin
   romper la idempotencia. No se debe asumir que un retorno tardío es inválido
   solo por superar los 5 minutos: la fuente de verdad es la respuesta de
   `commit`/`status`.

3. **Débito y prepago no usan captura diferida.** En esos medios la
   autorización y captura son simultáneas. El campo
   `Pago.capturado_en_autorizacion` debe quedar en `True` y no se debe llamar a
   `capture()` después. El estado interno `retenido` sigue siendo válido, pero
   significa "ya cobrado" para débito/prepago.

4. **Anulación de una autorización diferida sin capturar.** La documentación
   oficial no describe un método explícito para liberar una autorización
   diferida antes de los 7 días; solo dice que la retención se reversa sola al
   vencer. La reversa por `refund` está documentada para transacciones
   confirmadas (antes de 3 h) y la anulación después de 3 h, pero no se detalla
   su comportamiento sobre una autorización diferida no capturada. **Hay que
   probarlo en sandbox antes de implementar el rechazo del profesional como
   "refund inmediato"**. Si no funciona, la alternativa es no capturar y dejar
   que la retención expire a los 7 días, avisando al usuario.

5. **Sin webhooks.** La conciliación depende de `commit` y `status`. El retorno
   puede repetirse (doble clic/refresh), así que el commit debe ser idempotente
   y buscar el `Pago` por `token`, nunca por un id del cliente.

6. **Timeout sin token.** En timeout llegan `TBK_ID_SESION` y
   `TBK_ORDEN_COMPRA`, pero no `token_ws`. Hay que buscar el `Pago` por
   `buy_order` (`TBK_ORDEN_COMPRA`) y marcarlo `expirado`; no se puede hacer
   `commit`. En abandono con `TBK_TOKEN` sí se puede consultar con `status`,
   pero no es necesario confirmar.

7. **Captura diferida sin cuotas con interés.** Si el código de comercio está
   configurado para captura diferida, Webpay no ofrecerá cuotas con interés.
   No agregar lógica de cuotas en el MVP.

8. **Secretos.** La API key de integración es pública, pero la regla del
   proyecto es no versionarla. `settings.py` deja `TRANSBANK_API_KEY_SECRET`
   vacío por defecto y el valor se configura en `.env`. `ALLOW_FAKE_GATEWAY`
   evita que el gateway falso se use en producción por accidente.

---

## 5. Pendientes que requieren decisión o prueba en sandbox

1. Confirmar si `refund` libera una autorización de captura diferida **sin
   capturar** (hallazgo 4). Es el caso del profesional que rechaza la reserva.
2. Definir el texto/mensaje al usuario cuando el pago queda retenido y el
   profesional rechaza, si la liberación demora hasta 7 días.
3. Validar en sandbox el flujo completo con las tarjetas de prueba, incluyendo
   débito, prepago y crédito con captura diferida.
4. Confirmar el comportamiento de `commit` con un token vencido (5 minutos) y
   el manejo idempotente de un retorno repetido.

---

## 6. Implementación Fase 2 (adaptador real de integración)

Implementado el 2026-11-07:

- `apps/pagos/gateway/transbank.py` (`TransbankGateway`) con `crear`,
  `confirmar`, `estado`, `capturar` y `reembolsar`.
- Mapeo de estados Transbank → estados internos: `AUTHORIZED` → `AUTHORIZED`,
  `CAPTURED` → `CAPTURED`, `FAILED` → `REJECTED`, `NULLIFIED` → `REVERSED`.
- Saneo de respuestas antes de persistirlas (`card_number` se guarda como
  `***`; solo se conservan los últimos 4 dígitos en `tarjeta_ultimos4`).
- Errores del SDK/red se traducen a `ErrorPasarela`; la captura duplicada
  (`Transaction already captured`) se reporta con `ya_capturada=True` para que
  la conciliación la trate como éxito.
- `get_gateway()` valida credenciales, entorno y que el código de comercio
  corresponda al entorno de integración. `ALLOW_FAKE_GATEWAY` sigue exigiendo
  activación explícita del gateway simulado.
- Nuevo `TRANSBANK_TIMEOUT=10` (segundos) en `config/settings.py`.
- Ventana de reserva sin pago iniciado: `MINUTOS_PAGO_PENDIENTE=15`, según la
  spec. El token de Webpay expira a los 5 minutos; un pago ya `iniciado` se
  resuelve con `commit`/`status` y no con esta ventana.

### Credenciales de integración usadas

| Variable | Valor |
|---|---|
| `TRANSBANK_ENV` | `integration` |
| `TRANSBANK_COMMERCE_CODE` | `597055555540` (Webpay Plus Captura Diferida) |
| `TRANSBANK_API_KEY_SECRET` | API key pública de integración (en `.env`, no versionada) |

> `597055555536` corresponde a la sucursal 1 del Mall, **no** a Webpay Plus
> Captura Diferida. No usarlo para este flujo.

### Pruebas

- Unitarias con SDK mockeado: `apps/pagos/tests/test_transbank_gateway.py`
  (crear, confirmar aprobado/rechazado/capturado, estado, captura, captura
  duplicada, reembolso, errores de red y configuración TEST/LIVE).
- Integración real (create + status, sin commit):
  `apps/pagos/tests/test_sandbox_transbank.py`, marcada `sandbox` y excluida
  de la suite por defecto. Ejecutar con:

  ```bash
  .venv/bin/pytest apps/pagos/tests/test_sandbox_transbank.py -m sandbox -q
  ```

- El flujo completo con tarjeta de prueba (commit) sigue siendo una validación
  manual, porque requiere abrir el formulario de Webpay en el navegador.

### Validación manual con túnel

Webpay necesita una URL de retorno pública. Para probar en local sin dominio:

```bash
# Opción 1: Cloudflare Tunnel (sin cuenta)
cloudflared tunnel --url http://localhost:8000

# Opción 2: ngrok
ngrok http 8000
```

Luego, en `.env`:

1. `TRANSBANK_RETURN_URL=https://<host-publico>/api/pagos/transbank/retorno/`
2. Agregar `<host-publico>` a `ALLOWED_HOSTS` (sin esquema).
3. Reiniciar el backend y crear la reserva desde el frontend.
4. Pagar con una tarjeta de la tabla §3 (por ejemplo VISA
   `4051 8856 0044 6623`, CVV `123`, cualquier fecha futura).
5. Verificar el retorno en `FRONTEND_PAYMENT_RESULT_URL` y el estado final del
   `Pago`/`Reserva`.

El retorno llega por GET o POST a
`/api/pagos/transbank/retorno/`; la vista confirma siempre el token contra
Transbank (nunca confía en los parámetros del navegador).
