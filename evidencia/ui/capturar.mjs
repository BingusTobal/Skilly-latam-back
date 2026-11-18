import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'

const require = createRequire('/home/tobal/Proyectos/skilly_FRONT/package.json')
const { chromium, request } = require('@playwright/test')

const BASE = 'http://localhost:5173'
const API = 'http://127.0.0.1:8000/api'
const OUT = '/home/tobal/Proyectos/skilly_BACK/evidencia/ui'
mkdirSync(OUT, { recursive: true })

async function login(email, password) {
  const ctx = await request.newContext({ baseURL: API })
  const res = await ctx.post(`${API}/auth/token/`, { data: { email, password } })
  if (!res.ok()) throw new Error(`Login ${email}: ${res.status()} ${await res.text()}`)
  const data = await res.json()
  await ctx.dispose()
  return data
}

async function authContext(browser, tokens) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.addInitScript((t) => {
    localStorage.setItem('skilly_access', t.access)
    localStorage.setItem('skilly_refresh', t.refresh || '')
  }, tokens)
  return ctx
}

async function getData(ctx, url, headers = {}) {
  const res = await ctx.request.get(`${API}${url}`, { headers })
  if (!res.ok()) return []
  const data = await res.json()
  return Array.isArray(data) ? data : data.results || []
}

async function capturar(ctx, ruta, nombre) {
  const page = await ctx.newPage()
  await page.goto(`${BASE}${ruta}`, { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}/${nombre}.png`, fullPage: true })
  console.log(`${nombre}.png <- ${ruta}`)
  await page.close()
}

const browser = await chromium.launch({ headless: true })

const publico = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const servicios = await getData(publico, '/servicios/')
const servicioId = servicios[0]?.id
if (!servicioId) throw new Error('No hay servicios en el catálogo')
await capturar(publico, '/', '01_home')
await capturar(publico, '/catalogo', '02_catalogo')
await capturar(publico, `/servicios/${servicioId}`, '03_detalle_servicio')
await capturar(publico, `/servicios/${servicioId}/programar`, '04_programar_servicio')
await capturar(publico, `/servicios/${servicioId}/reservar`, '05_formulario_reserva')
await capturar(publico, '/login', '06_login_registro')
await capturar(publico, '/postular', '07_postular')
await publico.close()

const orgTokens = await login('org@test.skilly', 'OrgTest123!')
const org = await authContext(browser, orgTokens)
const orgHeaders = { Authorization: `Bearer ${orgTokens.access}` }
const reservasOrg = await getData(org, '/reservas/mias/', orgHeaders)
const reservaOrgId = reservasOrg[0]?.id
await capturar(org, '/mis-reservas', '08_mis_reservas')
if (reservaOrgId) {
  await capturar(org, `/reserva/${reservaOrgId}`, '09_detalle_reserva')
  await capturar(org, `/reserva/${reservaOrgId}/confirmar`, '10_confirmar_entrega')
}
await org.close()

const profTokens = await login('juan@test.skilly', 'ProfTest123!')
const prof = await authContext(browser, profTokens)
const profHeaders = { Authorization: `Bearer ${profTokens.access}` }
const reservasProf = await getData(prof, '/reservas/solicitudes/', profHeaders)
const reservaProfId = reservasProf[0]?.id
await capturar(prof, '/profesional/servicios', '11_mis_servicios')
await capturar(prof, '/profesional/servicios/nuevo', '12_publicar_servicio')
await capturar(prof, '/profesional/solicitudes', '13_mis_solicitudes')
if (reservaProfId) await capturar(prof, `/profesional/solicitudes/${reservaProfId}`, '14_solicitud_detalle')
await capturar(prof, '/profesional/horarios', '15_horarios')
await capturar(prof, '/profesional/postulacion', '16_mi_postulacion')
await capturar(prof, '/profesional/perfil', '17_mi_perfil')
await prof.close()

const adminTokens = await login('admin@skillylatam.com', 'SkillyAdmin2026!')
const admin = await authContext(browser, adminTokens)
const adminHeaders = { Authorization: `Bearer ${adminTokens.access}` }
const postulaciones = await getData(admin, '/postulaciones/admin/postulaciones/', adminHeaders)
const postulacionId = postulaciones[0]?.id
await capturar(admin, '/admin', '18_admin_resumen')
await capturar(admin, '/admin/postulaciones', '19_admin_postulaciones')
if (postulacionId) await capturar(admin, `/admin/postulaciones/${postulacionId}`, '20_admin_detalle_postulacion')
await capturar(admin, '/admin/certificados', '21_admin_certificados')
await capturar(admin, '/admin/disputas', '22_admin_disputas')
await capturar(admin, '/admin/profesionales', '23_admin_profesionales')
await capturar(admin, '/admin/organizaciones', '24_admin_organizaciones')
await capturar(admin, '/admin/comisiones', '25_admin_comisiones')
await capturar(admin, '/admin/comisiones/ganancias', '26_admin_ganancias')
await capturar(admin, '/admin/servicios', '27_admin_revision_servicios')
await admin.close()

await browser.close()
