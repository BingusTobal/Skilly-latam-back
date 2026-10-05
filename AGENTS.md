# Skilly Latam — Instrucciones del proyecto para el agente

Este archivo es la fuente de verdad del stack y las reglas de negocio. Si algo en
`docs/informe.md` contradice lo que dice aquí, **gana lo que dice este archivo**.

## Qué es Skilly

Marketplace de servicios con precio fijo que conecta organizaciones con profesionales independientes, bajo el modelo "Talent as a Service".
La organización reserva un servicio del catálogo; un profesional lo ejecuta; el pago
queda en custodia (escrow) hasta confirmar la entrega. Los servicios son publicados directamente por los profesionales.

Documentación de referencia (no reescribir el stack desde ahí, solo consultar
requerimientos, actores y casos de uso):
- `docs/informe_sistema.xlsx` — actores, interfaces, RF, checklist IEEE830, casos de uso
- `docs/mockups/` — HTML de referencia visual para cada pantalla (usar sus clases/estructura
  como base del diseño de los componentes React, no reinventar el layout)

## Stack final (no usar nada fuera de esta lista)

| Capa | Tecnología |
|---|---|
| Frontend | React 18 + Vite (sin Next.js) |
| Estilos | Tailwind CSS |
| Backend | Django + Django REST Framework |
| Auth | `djangorestframework-simplejwt` (JWT) |
| Base de datos | MariaDB |
| Almacenamiento de archivos | Amazon S3 (`django-storages`) — local en desarrollo |
| Pasarela de pago | Transbank Webpay Plus (sandbox de integración) — Mercado Pago queda solo
  contemplado para expansión futura, **no implementar en el MVP** |
| Correo transaccional | Amazon SES (`django-anymail`) — usar consola/log de Django en desarrollo |
| Gráficos | Recharts |
| Routing frontend | `react-router-dom` |
| HTTP client | `axios` |

No usar: Spring Boot, Java, NestJS/Node.js como backend, PostgreSQL, MongoDB, MinIO.
Esas tecnologías aparecen en versiones viejas de `docs/informe.md` y ya no aplican.

## Estructura de carpetas

### Backend (`skilly-backend/`)
```
skilly-backend/
├── manage.py
├── requirements.txt
├── .env
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── apps/
    ├── usuarios/          # Organizacion, Profesional, auth custom user
    ├── catalogo/          # Servicio, Categoria, Entregable
    ├── reservas/          # Reserva y su máquina de estados
    ├── pagos/             # Pago (autorizado/retenido/liberado/reembolsado)
    ├── postulaciones/     # Postulacion, Certificado
    ├── disputas/          # Disputa
    └── comisiones/        # TasaComision, reportes de comisión
```

### Frontend (`skilly-frontend/`)
```
skilly-frontend/
├── .env                      # VITE_API_URL=http://localhost:8000/api
└── src/
    ├── api/                   # axios.js + un archivo por recurso (catalogo.js, reservas.js...)
    ├── context/AuthContext.jsx
    ├── components/            # compartidos: Navbar, Card, StatusBadge
    └── pages/
        ├── organizacion/      # Home, Catalogo, DetalleServicio, ProgramaServicio,
        │                      # FormularioReserva, MisReservas, ConfirmarEntrega
        ├── profesional/       # MisServicios, PublicarServicio, MisSolicitudes, Solicitud
        └── admin/             # Resumen, Postulaciones, DetallePostulacion, Disputas,
                               # Profesionales, Organizaciones, Comisiones
```

## Orden de construcción (no te saltes el orden)

Sigue la tabla de priorización NEC del informe. En este orden exacto:

1. **`catalogo` + `reservas`** — CRUD de servicios y flujo de reserva completo.
2. **`usuarios`** — registro/login de organización y profesional, configuración de horarios, JWT. Sin esto no se protege nada.
3. **`pagos`** — máquina de estados interna (ver regla de negocio abajo). Conectar
   Transbank sandbox recién cuando los estados internos ya funcionen simulados a mano.
4. **`postulaciones` + `disputas` + `comisiones`** — panel admin, revisión de servicios publicados por profesionales, al final.

No implementar disputas o comisiones antes que el flujo de reserva base funcione
de punta a punta.

## Reglas de negocio que el código debe reflejar exactamente

- **Escrow es un estado interno, no una custodia bancaria real.** El modelo `Pago` tiene
  un campo `estado` con valores: `autorizado → retenido → liberado` o `reembolsado`.
  Transbank cobra en el paso "retenido" (no antes); "liberado" es una transferencia
  posterior de Skilly al profesional, no algo que haga el banco automáticamente.
- **El profesional ve el monto neto, nunca el desglose bruto + comisión.** Calcular
  `monto_neto = precio_servicio * (1 - tasa_comision)` y mostrar solo ese número.
- **Sin calificación por estrellas, en ningún lado.** Los comentarios post-servicio son
  texto libre, sin campo de puntaje numérico.
- **Publicación y Revisión de Servicios**: Los profesionales crean y postean sus propios servicios. Al publicar, el servicio pasa a estado "En revisión". Un administrador debe revisar, puede editar ciertos campos si es necesario, y luego aprueba o devuelve con comentarios para que el profesional vea los cambios/sugerencias.
- **Formatos de Ejecución**: Considerar únicamente los formatos: Remoto, Presencial o Semipresencial (Híbrido)[cite: 98].
- **Horarios Personalizados**: El profesional puede establecer su propio horario y disponibilidad según su preferencia.
- **Comunicación Directa**: Tras la reserva, la organización se comunica y coordina directamente con el profesional asignado.
- **Sugerencias en Detalle de Servicio**: En la vista de un servicio, no se sugieren otros profesionales, sino que se muestran otras sugerencias de servicios de la misma categoría o relacionados.
- **Certificados del profesional**: LinkedIn se valida automático; cualquier otro
  documento queda en estado "sin revisar" hasta que un admin lo apruebe manualmente
  desde `DetallePostulacion`.
- **Reserva sin cuenta es el camino principal**, no una excepción: el formulario de
  reserva pide datos de contacto directamente; iniciar sesión es la alternativa para
  quien ya tiene cuenta, no un muro obligatorio antes de reservar.

## Convenciones

- Apps y modelos de Django en español, siguiendo los nombres ya usados en el informe
  (`Servicio`, `Reserva`, `Postulacion`, no traducir a inglés).
- Componentes React en PascalCase, un archivo por página dentro de su carpeta de rol
  (`organizacion/`, `profesional/`, `admin/`).
- IDs de requerimiento (`RF-XX`) y de interfaz (`INTXX`) del Excel van como comentario
  en el código donde se implementan, para mantener trazabilidad.
