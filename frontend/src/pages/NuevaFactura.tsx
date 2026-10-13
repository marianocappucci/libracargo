/** Nueva factura: conceptos libres, sin órdenes ni remitos, **directo por ARCA** (ADR-048).
 *
 * Es la otra mitad de «Facturar pendientes»: cuando lo que se cobra no sale de unas órdenes (un servicio, un gasto
 * que se refactura, una diferencia). Se elige el cliente, se cargan los conceptos —descripción, cantidad, precio y
 * alícuota de IVA— y se emite: el CAE sale en el momento. Como no se deshace (se corrige con una nota de crédito),
 * el botón pide una confirmación.
 *
 * 🔑 **Los importes los calcula el servidor.** Lo que se ve abajo es sólo la vista previa, en centavos enteros
 * (`previsualizarFactura`): el IVA se calcula una vez sobre el neto, como lo hace el servidor, y el comprobante que
 * queda es el que éste armó. Tampoco hay punto de venta ni número: los pone ARCA.
 *
 * 🔑 **La clase la decide la empresa y el cliente**, no el operador (`GET /api/comprobantes/tipos`): un monotributista
 * emite C, un inscripto A o B según a quién le factura. Sólo se ofrecen las que ARCA acepta; el servidor las vuelve a
 * validar.
 *
 * 🔑 **Todos los conceptos de una factura llevan la misma alícuota**: ARCA recibe un solo bloque de IVA por comprobante.
 * La pantalla lo dice y no deja emitir con alícuotas mezcladas (para eso, una factura por alícuota).
 */
import { ArrowLeft, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import type { Concepto, CuentasFce, OpcionesDeTipo, TipoComprobante } from '@/api/comprobantes'
import {
  ALICUOTAS_DE_IVA, NOMBRE_DE_TIPO, comprobantes, etiquetaDeCuenta, previsualizarFactura,
} from '@/api/comprobantes'
import { cargarOpciones } from '@/api/ordenes'
import type { Opciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { formatearImporte, hoyEnArgentina } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ICONOS_LC } from '@/iconos'
import { irA } from '@/navegacion'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

type Renglon = Concepto & { clave: number }

const RENGLON_VACIO = { descripcion: '', cantidad: '1', precio_unitario: '', alicuota_iva: '21' }

/** Una fecha `AAAA-MM-DD` más `dias`, por componentes: ni zona horaria ni `toISOString`. */
function masDias(iso: string, dias: number): string {
  const [a, m, d] = iso.split('-').map(Number)
  const f = new Date(Date.UTC(a, m - 1, d + dias))
  const dos = (n: number) => String(n).padStart(2, '0')
  return `${f.getUTCFullYear()}-${dos(f.getUTCMonth() + 1)}-${dos(f.getUTCDate())}`
}

const esFce = (tipo: string) => tipo.startsWith('fce_')
const esClaseC = (tipo: string) => tipo.endsWith('_c')

/** Lo que falta para poder emitir, dicho en una frase; `null` si está todo. */
function queFalta(c: Concepto, claseC: boolean): string | null {
  if (!c.descripcion.trim()) return 'Falta la descripción de un concepto.'
  if (!/^\d+([.,]\d{1,3})?$/.test(c.cantidad.trim()) || Number(c.cantidad.replace(',', '.')) <= 0) {
    return 'La cantidad de cada concepto tiene que ser mayor que cero, con hasta tres decimales.'
  }
  if (!/^\d+([.,]\d{1,2})?$/.test(c.precio_unitario.trim()) || Number(c.precio_unitario.replace(',', '.')) <= 0) {
    return claseC
      ? 'El importe de cada concepto tiene que ser mayor que cero, con hasta dos decimales.'
      : 'El precio de cada concepto tiene que ser mayor que cero, con hasta dos decimales.'
  }
  return null
}

function Campo({ id, etiqueta, valor, alCambiar, tipo = 'text' }: {
  id: string; etiqueta: string; valor: string; alCambiar: (v: string) => void; tipo?: string
}) {
  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <Input id={id} type={tipo} value={valor} onChange={(e) => alCambiar(e.target.value)} />
    </div>
  )
}

export default function NuevaFactura() {
  const [params, setParams] = useSearchParams()
  const navegar = useNavigate()
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [fecha, setFecha] = useState(hoyEnArgentina())
  const [tipo, setTipo] = useState<TipoComprobante | ''>('')
  const [vencimiento, setVencimiento] = useState('')
  const [cuenta, setCuenta] = useState('')
  const [observaciones, setObservaciones] = useState('')
  const [siguiente, setSiguiente] = useState(2)
  const [renglones, setRenglones] = useState<Renglon[]>([{ clave: 1, ...RENGLON_VACIO }])
  const [disponibles, setDisponibles] = useState<OpcionesDeTipo | null>(null)
  const [cuentasFce, setCuentasFce] = useState<CuentasFce | null>(null)
  const [enviando, setEnviando] = useState(false)
  // Emitir por ARCA no se deshace: el primer click pide confirmar, el segundo emite.
  const [confirmando, setConfirmando] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const clienteId = params.get('cliente') ?? ''
  const fce = tipo !== '' && esFce(tipo)
  const claseC = tipo !== '' && esClaseC(tipo)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // Qué clases ofrece la empresa a este cliente. Sin cliente, las de la empresa (las dos si es inscripta).
  useEffect(() => {
    let vigente = true
    comprobantes.tipos(clienteId ? Number(clienteId) : undefined)
      .then((respuesta) => {
        if (!vigente) return
        // Una respuesta sin lista (un servidor viejo) es «no hay clases», no un error de pantalla.
        const o: OpcionesDeTipo = {
          tipos: Array.isArray(respuesta?.tipos) ? respuesta.tipos : [], sugerido: respuesta?.sugerido ?? null,
          fce_habilitada: Boolean(respuesta?.fce_habilitada), problema: respuesta?.problema ?? null,
        }
        setDisponibles(o)
        // Se mantiene la elegida si sigue valiendo; si no, la sugerida o la primera.
        setTipo((actual) => (actual && o.tipos.includes(actual) ? actual : (o.sugerido ?? o.tipos[0] ?? '')))
      })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [clienteId])

  // En qué cuenta se cobra la FCE: se piden una vez, cuando hace falta elegir.
  useEffect(() => {
    if (!fce || cuentasFce) return
    let vigente = true
    comprobantes.fceCuentas()
      .then((r) => {
        if (vigente) setCuentasFce(r && Array.isArray(r.cuentas) ? r : { cuentas: [], predeterminada: '', transmision: '' })
      })
      .catch(() => { if (vigente) setCuentasFce({ cuentas: [], predeterminada: '', transmision: '' }) })
    return () => { vigente = false }
  }, [fce, cuentasFce])
  const cuentaElegida = cuenta || cuentasFce?.predeterminada || ''

  const conceptos: Concepto[] = renglones.map(({ clave: _clave, ...c }) => c)
  const vista = useMemo(
    () => previsualizarFactura(conceptos, claseC),
    // `conceptos` se rearma en cada render: la dependencia es el contenido.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(conceptos), claseC],
  )

  const cambiar = (clave: number, cambios: Partial<Concepto>) => {
    setConfirmando(false)
    setRenglones((previos) => previos.map((r) => (r.clave === clave ? { ...r, ...cambios } : r)))
  }
  const agregar = () => {
    setConfirmando(false)
    setRenglones((previos) => [...previos, { clave: siguiente, ...RENGLON_VACIO, alicuota_iva: previos[0]?.alicuota_iva ?? '21' }])
    setSiguiente((n) => n + 1)
  }
  const quitar = (clave: number) => {
    setConfirmando(false)
    setRenglones((previos) => (previos.length > 1 ? previos.filter((r) => r.clave !== clave) : previos))
  }

  const alicuotasMezcladas = !claseC && vista.alicuotas.length > 1
  const faltan = !clienteId ? 'Elegí el cliente.'
    : disponibles?.problema ? disponibles.problema
    : !tipo ? 'Elegí la clase de comprobante.'
    : fce && !vencimiento ? 'Falta el vencimiento de pago.'
    : fce && vencimiento < fecha ? 'El vencimiento de pago no puede ser anterior a la fecha del comprobante.'
    : conceptos.map((c) => queFalta(c, claseC)).find((m) => m !== null) ?? null
  const impedimento = faltan ?? (alicuotasMezcladas
    ? 'Todos los conceptos llevan la misma alícuota de IVA: emití una factura por alícuota.' : null)

  async function emitir() {
    if (!tipo) return
    setError(null)
    setAviso(null)
    setEnviando(true)
    try {
      const hecho = await comprobantes.facturarDirecta({
        cliente_id: Number(clienteId),
        tipo,
        fecha,
        // Sólo la FCE lleva vencimiento de pago y cuenta de cobro; `undefined` no viaja en el JSON.
        fecha_vencimiento_pago: fce ? vencimiento : undefined,
        fce_cbu: fce ? cuenta : undefined,
        conceptos: conceptos.map((c) => ({
          ...c, descripcion: c.descripcion.trim(),
          cantidad: c.cantidad.trim().replace(',', '.'), precio_unitario: c.precio_unitario.trim().replace(',', '.'),
        })),
        observaciones: observaciones.trim() || undefined,
      })
      if (hecho && 'ensayo' in hecho) {
        // Homologación: se corrió todo contra ARCA y no se guardó nada.
        setAviso(`Ensayo contra ${hecho.ambiente}: ARCA autorizó una factura de prueba `
          + `(CAE ${hecho.cae ?? 's/n'}) y no se guardó nada.`)
        setConfirmando(false)
        setEnviando(false)
        return
      }
      navegar(hecho?.id ? irA.comprobante(hecho.id) : '/comprobantes')
    } catch (e) {
      setError(mensajeDeError(e))
      setConfirmando(false)
      setEnviando(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="Volver a Comprobantes">
          <Link to="/comprobantes"><ArrowLeft className="size-4" /></Link>
        </Button>
        <TituloPantalla icono={ICONOS_LC.comprobantes}>Nueva factura</TituloPantalla>
      </div>

      <p className="text-muted-foreground mb-4 text-sm">
        Una factura de conceptos libres, <strong>sin órdenes ni remitos</strong>, directo por ARCA: el CAE sale en el
        momento y no se puede deshacer (se corrige con una nota de crédito). Los importes los calcula el servidor; el
        punto de venta y el número los pone ARCA. ¿Facturás viajes? Usá{' '}
        <Link className="underline" to={irA.facturarPendientes(clienteId ? Number(clienteId) : undefined)}>
          Facturar pendientes</Link>.
      </p>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">{error}</p>
      )}
      {aviso && <p role="status" className="mb-4 rounded border p-3 text-sm font-semibold">{aviso}</p>}

      <section className="mb-6 rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Datos del comprobante</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <Campo id="nf-fecha" etiqueta="Fecha" tipo="date" valor={fecha}
                 alCambiar={(v) => { setConfirmando(false); setFecha(v) }} />
          <Elegir id="nf-cliente" etiqueta="Cliente" vacio="Elegir…"
                  valor={clienteId} opciones={opciones?.clientes ?? []}
                  alCambiar={(v) => {
                    setConfirmando(false)
                    setParams(v ? { cliente: v } : {}, { replace: true })
                  }} />
          <div className="grid min-w-0 gap-1">
            <Label htmlFor="nf-tipo">Tipo</Label>
            {/* select-cerrado: las clases de comprobante que ARCA acepta para esta empresa y este cliente (dos o tres). */}
            <select id="nf-tipo" className="h-9 w-full min-w-0 rounded-md border px-2 text-sm" value={tipo}
                    onChange={(e) => {
                      const nuevo = e.target.value as TipoComprobante
                      setConfirmando(false)
                      setTipo(nuevo)
                      // Al pasar a FCE se propone 30 días: se puede cambiar.
                      if (esFce(nuevo) && !vencimiento) setVencimiento(masDias(fecha, 30))
                    }}>
              {(disponibles?.tipos ?? []).map((t) => <option key={t} value={t}>{NOMBRE_DE_TIPO[t]}</option>)}
            </select>
          </div>
          {fce && (
            <Campo id="nf-vencimiento" etiqueta="Vencimiento de pago" tipo="date" valor={vencimiento}
                   alCambiar={(v) => { setConfirmando(false); setVencimiento(v) }} />
          )}
          {fce && cuentasFce && (cuentasFce.cuentas.length > 0 ? (
            <Elegir id="nf-cuenta" etiqueta="Cobrar en" vacio="La predeterminada" valor={cuentaElegida}
                    opciones={cuentasFce.cuentas.map((c) => ({
                      id: c.cbu,
                      etiqueta: c.cbu === cuentasFce.predeterminada
                        ? `${etiquetaDeCuenta(c)} (predeterminada)` : etiquetaDeCuenta(c),
                    }))}
                    alCambiar={(v) => { setConfirmando(false); setCuenta(v === cuentasFce.predeterminada ? '' : v) }} />
          ) : (
            <p role="status" className="text-muted-foreground self-end text-sm md:col-span-3">
              No hay cuentas para cobrar la factura de crédito: cargalas en Configuración → ARCA.
            </p>
          ))}
        </div>
        {disponibles?.problema && (
          <p role="alert" className="mt-3 rounded border border-destructive/40 p-3 text-sm">{disponibles.problema}</p>
        )}
      </section>

      <section className="mb-6">
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Conceptos</h2>
          <span className="text-muted-foreground text-xs">
            {claseC ? 'Clase C: el importe es el total, sin IVA discriminado.' : 'El precio es neto, sin IVA.'}
          </span>
        </div>
        <ul className="grid gap-3">
          {renglones.map((r, i) => {
            const n = i + 1
            return (
              <li key={r.clave} className="grid gap-2 rounded border p-3 md:grid-cols-12 md:items-end">
                <div className="grid min-w-0 gap-1 md:col-span-5">
                  <Label htmlFor={`nf-d-${r.clave}`} className={i > 0 ? 'md:sr-only' : ''}>Descripción</Label>
                  <Input id={`nf-d-${r.clave}`} aria-label={`Descripción del concepto ${n}`} value={r.descripcion}
                         maxLength={200} onChange={(e) => cambiar(r.clave, { descripcion: e.target.value })} />
                </div>
                <div className="grid min-w-0 gap-1 md:col-span-1">
                  <Label htmlFor={`nf-c-${r.clave}`} className={i > 0 ? 'md:sr-only' : ''}>Cantidad</Label>
                  <Input id={`nf-c-${r.clave}`} aria-label={`Cantidad del concepto ${n}`} inputMode="decimal"
                         value={r.cantidad} onChange={(e) => cambiar(r.clave, { cantidad: e.target.value })} />
                </div>
                <div className="grid min-w-0 gap-1 md:col-span-2">
                  <Label htmlFor={`nf-p-${r.clave}`} className={i > 0 ? 'md:sr-only' : ''}>
                    {claseC ? 'Importe' : 'Precio unitario'}
                  </Label>
                  <Input id={`nf-p-${r.clave}`} aria-label={`${claseC ? 'Importe' : 'Precio'} del concepto ${n}`}
                         inputMode="decimal" value={r.precio_unitario}
                         onChange={(e) => cambiar(r.clave, { precio_unitario: e.target.value })} />
                </div>
                {!claseC && (
                  <div className="grid min-w-0 gap-1 md:col-span-2">
                    <Label htmlFor={`nf-a-${r.clave}`} className={i > 0 ? 'md:sr-only' : ''}>IVA</Label>
                    {/* select-cerrado: las cuatro alícuotas que recibe ARCA. */}
                    <select id={`nf-a-${r.clave}`} aria-label={`Alícuota de IVA del concepto ${n}`}
                            className="h-9 w-full min-w-0 rounded-md border px-2 text-sm" value={r.alicuota_iva}
                            onChange={(e) => cambiar(r.clave, { alicuota_iva: e.target.value })}>
                      {ALICUOTAS_DE_IVA.map((a) => <option key={a} value={a}>{a}%</option>)}
                    </select>
                  </div>
                )}
                <div className={`flex items-end justify-end md:col-span-${claseC ? 4 : 2}`}>
                  <Button variant="ghost" size="icon" aria-label={`Quitar el concepto ${n}`}
                          disabled={renglones.length === 1} onClick={() => quitar(r.clave)}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
        <Button variant="outline" size="sm" className="mt-3" onClick={agregar}>
          <Plus className="size-4" /> Agregar concepto
        </Button>
        {alicuotasMezcladas && (
          <p role="alert" className="mt-3 rounded border border-destructive/40 p-3 text-sm">
            Los conceptos tienen alícuotas distintas ({vista.alicuotas.map((a) => `${a}%`).join(', ')}). ARCA recibe un
            solo bloque de IVA por comprobante: emití una factura por alícuota.
          </p>
        )}
      </section>

      <section className="mb-6">
        <Campo id="nf-observaciones" etiqueta="Observaciones (salen en el comprobante)" valor={observaciones}
               alCambiar={(v) => { setConfirmando(false); setObservaciones(v.slice(0, 500)) }} />
      </section>

      {/* Pegado abajo: el total se mira antes de confirmar. */}
      <div className="bg-background sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t py-3">
        <span className="text-sm">
          {claseC ? null : <>Neto {formatearImporte(vista.neto)} · IVA {formatearImporte(vista.iva)}</>}
        </span>
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-lg font-semibold">Total: {formatearImporte(vista.total)}</span>
          {confirmando ? (
            <>
              <span className="text-sm">Se emite por ARCA ahora y no se deshace.</span>
              <Button variant="ghost" onClick={() => setConfirmando(false)} disabled={enviando}>No</Button>
              <Button onClick={emitir} disabled={enviando}>
                {enviando ? 'Emitiendo…' : 'Confirmar y emitir'}
              </Button>
            </>
          ) : (
            <Button onClick={() => setConfirmando(true)} disabled={impedimento != null || enviando}>
              Emitir factura
            </Button>
          )}
        </div>
      </div>
      {impedimento && (
        // Decir POR QUÉ no se puede: un botón gris sin motivo obliga a adivinar cuál de los campos falta.
        <p className="text-muted-foreground pb-2 text-right text-xs">{impedimento}</p>
      )}
    </div>
  )
}
