/** «Emitir carta de porte»: el asistente que emite la CPE en ARCA desde una orden de carga (ADR-043).
 *
 *  Es un documento fiscal y de circulación: una vez emitido, sólo se puede anular. Por eso el asistente es lento a
 *  propósito, en cuatro pasos —titular, datos, revisar y confirmar, resultado— y cada decisión que puede salir cara
 *  tiene su freno:
 *
 *  🔑 **«A nombre de» no tiene valor por defecto**, ni siquiera con un solo titular (como «Consultar como» en
 *  `TraerCartasDePorte`): la carta queda a nombre de quien se elija, y un titular equivocado no es un error visible.
 *
 *  🔑 **En producción, un recuadro y un «Confirmo» obligatorio**: sin el check no se puede enviar (y el servidor
 *  tampoco lo acepta). En homologación se avisa que es de prueba.
 *
 *  🔑 **Una página y no un diálogo** (pedido del humano, 2026-10-09): es un formulario largo y un documento fiscal, y en un
 *  modal quedaba apretado. Vive en `/cartas-porte/emitir/:ordenId` (`pages/EmitirCartaDePorte.tsx`); «Cancelar» y
 *  «Cerrar» vuelven a la orden.
 *
 *  🔑 **Un solo envío.** Mientras se envía el botón está deshabilitado y salir de la página pide confirmación. Si el servidor contesta un
 *  502 (ARCA no contestó: puede haberla emitido) o un 500 («SE EMITIÓ… no la vuelvas a emitir»), o si la conexión se
 *  corta sin respuesta, el asistente pasa a un estado final en rojo **sin botón de reintento**: emitir de nuevo sería
 *  duplicar una carta de porte real. Lo único que se ofrece es ir a verificar en «Cartas de porte».
 *
 *  Los textos de error del servidor se muestran siempre tal cual: son los que dicen qué hacer.
 */
import { ApiError } from 'libra-ui/api-client'
import { TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import type {
  CartaPorte, EstadoDeEmision, ListadoDeTitulares, OpcionDeArca, Planta, Propuesta,
} from '@/api/cartas-porte'
import {
  cartasPorte, formatearCuit, formatearInstante, formatearKilos,
} from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { CompartirCartaDePorte } from '@/components/CompartirCartaDePorte'
import { Elegir } from '@/components/Elegir'
import {
  Campo, Casilla, Catalogo, Seccion, Texto, TextoCuit, TextoNumero,
} from '@/components/campos-cpe'
import { formatearImporte } from '@/components/esquema-orden'
import type { Borrador } from '@/components/emision-cpe'
import {
  INTERVINIENTES, MAX_DOMINIOS, borradorDe, datosDe, netoDe, problemasDe,
} from '@/components/emision-cpe'
import type { Orden } from '@/api/ordenes'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

type Paso = 'titular' | 'datos' | 'confirmar' | 'resultado' | 'incierto'

const PASOS: { paso: Paso; etiqueta: string }[] = [
  { paso: 'titular', etiqueta: 'Titular' },
  { paso: 'datos', etiqueta: 'Datos' },
  { paso: 'confirmar', etiqueta: 'Confirmar' },
  { paso: 'resultado', etiqueta: 'Resultado' },
]

const SIN_CATALOGO: OpcionDeArca[] = []
const nombreDel = (lista: OpcionDeArca[] | undefined, codigo: string) =>
  lista?.find((o) => String(o.codigo) === codigo)?.nombre ?? ''

/** Un 5xx o una respuesta que no llegó: no se sabe si ARCA emitió. Un 409/422 es un «no» claro, antes de emitir. */
function esIncierto(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status >= 500
}

/** A nombre de quién se puede emitir: los titulares cargados que son «nosotros» y están activos **y delegados en ARCA**,
 *  más los CUIT que ARCA trae y no están cargados (ADR-044). Estos últimos se ofrecen marcados: la delegación es lo que
 *  autoriza —y el servidor la vuelve a verificar al emitir—, y la lista de Titulares es una libreta que puede ir atrás
 *  (el primer cliente que delegó, antes de cargarlo). Lo que no se ofrece nunca: uno que emite él, uno dado de baja, ni
 *  uno cuya delegación ARCA todavía no informa. */
export function opcionesDeTitulares(l: ListadoDeTitulares | null): {
  cuit: string; nombre: string; etiqueta: string; sinCargar: boolean
}[] {
  if (!l || !l.verificado) return []
  const cargados = l.titulares
    .filter((t) => t.activo && t.emite === 'nosotros' && t.delegacion === 'delegado')
    .map((t) => ({ cuit: t.cuit, nombre: t.razon_social, etiqueta: t.razon_social, sinCargar: false }))
  const sinCargar = l.sin_cargar.map((s) => {
    const nombre = s.tercero?.razon_social ?? formatearCuit(s.cuit)
    return { cuit: s.cuit, nombre, etiqueta: `${nombre} · sin cargar en Titulares`, sinCargar: true }
  })
  return [...cargados, ...sinCargar]
}

// ── El asistente ──────────────────────────────────────────────────────────

function Asistente({ orden, alCerrar, alEmitida }: {
  orden: Orden
  alCerrar: () => void
  alEmitida?: (carta: CartaPorte) => void
}) {
  const [paso, setPaso] = useState<Paso>('titular')

  // Paso 1: titular
  const [titulares, setTitulares] = useState<ListadoDeTitulares | null>(null)
  const [errorDeAcceso, setErrorDeAcceso] = useState<string | null>(null)
  const [estado, setEstado] = useState<EstadoDeEmision | null>(null)
  const [errorDeEstado, setErrorDeEstado] = useState<string | null>(null)
  const [intento, setIntento] = useState(0)
  const [cuit, setCuit] = useState('')
  const [cargando, setCargando] = useState(false)
  const [errorDePaso, setErrorDePaso] = useState<string | null>(null)

  // Paso 2: datos
  const [propuesta, setPropuesta] = useState<Propuesta | null>(null)
  const [titularDeLaPropuesta, setTitularDeLaPropuesta] = useState('')
  const [b, setB] = useState<Borrador | null>(null)
  const [granos, setGranos] = useState<OpcionDeArca[]>(SIN_CATALOGO)
  const [provincias, setProvincias] = useState<OpcionDeArca[]>(SIN_CATALOGO)
  const [localidades, setLocalidades] = useState<Record<string, OpcionDeArca[]>>({})
  const [errorDeCatalogo, setErrorDeCatalogo] = useState<string | null>(null)
  const [plantas, setPlantas] = useState<{ cuit: string; lista: Planta[] | null } | null>(null)
  const pedidas = useRef(new Set<string>())

  // Pasos 3 y 4
  const [confirmo, setConfirmo] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const enviandoYa = useRef(false)
  const [errorDeEnvio, setErrorDeEnvio] = useState<string | null>(null)
  const [incierto, setIncierto] = useState<string | null>(null)
  const [emitida, setEmitida] = useState<CartaPorte | null>(null)

  // Mientras se envía, cerrar o recargar la pestaña pide confirmación: irse no frena el pedido, y no se sabría si ARCA la
  // emitió.
  useEffect(() => {
    if (!enviando) return
    const avisar = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', avisar)
    return () => window.removeEventListener('beforeunload', avisar)
  }, [enviando])

  // Al abrir (y al reintentar): por quién se puede emitir y si se puede emitir. Dos pedidos aparte: el estado es de este
  // sistema y se tiene que poder leer aunque ARCA no conteste a la lista de titulares.
  useEffect(() => {
    let vigente = true
    setTitulares(null); setErrorDeAcceso(null); setEstado(null); setErrorDeEstado(null)
    cartasPorte.estadoDeEmision()
      .then((r) => { if (vigente) setEstado(r) })
      .catch((e) => { if (vigente) setErrorDeEstado(mensajeDeError(e)) })
    cartasPorte.titulares()
      .then((r) => { if (vigente) setTitulares(r) })
      .catch((e) => { if (vigente) setErrorDeAcceso(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [intento])

  // Las localidades de ARCA se piden por provincia, la primera vez que se elige.
  const provinciaDeOrigen = b?.origenProvincia ?? ''
  const provinciaDeDestino = b?.destinoProvincia ?? ''
  useEffect(() => {
    if (!cuit || (paso !== 'datos' && paso !== 'confirmar')) return
    for (const provincia of new Set([provinciaDeOrigen, provinciaDeDestino])) {
      if (!provincia || pedidas.current.has(provincia)) continue
      pedidas.current.add(provincia)
      cartasPorte.localidades(cuit, Number(provincia))
        .then((lista) => setLocalidades((l) => ({ ...l, [provincia]: lista })))
        .catch((e) => {
          pedidas.current.delete(provincia)
          setErrorDeCatalogo(mensajeDeError(e))
        })
    }
  }, [cuit, paso, provinciaDeOrigen, provinciaDeDestino])

  // Las plantas inscriptas del destino, cuando ya hay un CUIT completo.
  const cuitDelDestino = (b?.destinoCuit ?? '').replace(/\D/g, '')
  useEffect(() => {
    if (!cuit || paso !== 'datos' || cuitDelDestino.length !== 11) return
    let vigente = true
    cartasPorte.plantas(cuit, cuitDelDestino)
      .then((lista) => { if (vigente) setPlantas({ cuit: cuitDelDestino, lista }) })
      .catch(() => { if (vigente) setPlantas({ cuit: cuitDelDestino, lista: null }) })
    return () => { vigente = false }
  }, [cuit, paso, cuitDelDestino])

  const problemas = useMemo(() => (b ? problemasDe(b) : {}), [b])
  const cantidadDeProblemas = Object.keys(problemas).length

  const opcionesDeTitular = useMemo(() => opcionesDeTitulares(titulares), [titulares])
  const titular = opcionesDeTitular.find((o) => o.cuit === cuit)
  const nombreDelTitular = titular ? titular.nombre : formatearCuit(cuit)
  const produccion = estado?.ambiente === 'produccion'
  const homologacion = estado?.ambiente === 'homologacion'

  function cambiar<K extends keyof Borrador>(campo: K, valor: Borrador[K]) {
    setB((actual) => (actual ? { ...actual, [campo]: valor } : actual))
  }

  async function irADatos() {
    if (!cuit) return
    // Volver al paso 1 y seguir con el mismo titular no vuelve a pedir la propuesta: se perderían las ediciones.
    if (propuesta && titularDeLaPropuesta === cuit && b) { setPaso('datos'); return }
    setErrorDePaso(null); setCargando(true)
    try {
      const [p, g, pr] = await Promise.all([
        cartasPorte.propuesta(orden.id, cuit), cartasPorte.granos(cuit), cartasPorte.provincias(cuit),
      ])
      pedidas.current = new Set()
      setLocalidades({}); setPlantas(null); setErrorDeCatalogo(null)
      setPropuesta(p); setTitularDeLaPropuesta(cuit); setGranos(g); setProvincias(pr)
      setB(borradorDe(p)); setConfirmo(false); setErrorDeEnvio(null)
      setPaso('datos')
    } catch (e) {
      setErrorDePaso(mensajeDeError(e))
    } finally {
      setCargando(false)
    }
  }

  function cambiarDestinoCuit(valor: string) {
    setB((actual) => {
      if (!actual) return actual
      const mismo = actual.cuitDestinatario === '' || actual.cuitDestinatario === actual.destinoCuit
      return {
        ...actual, destinoCuit: valor, cuitDestinatario: mismo ? valor : actual.cuitDestinatario,
        // Las plantas son de ese CUIT: con otro, la elegida ya no vale.
        destinoPlanta: valor === actual.destinoCuit ? actual.destinoPlanta : '',
      }
    })
  }

  async function emitir() {
    if (enviandoYa.current || !b) return
    enviandoYa.current = true
    setEnviando(true); setErrorDeEnvio(null)
    try {
      const carta = await cartasPorte.emitir(orden.id, confirmo, datosDe(b, cuit))
      setEmitida(carta); setPaso('resultado')
      alEmitida?.(carta)
    } catch (e) {
      const mensaje = mensajeDeError(e)
      if (esIncierto(e)) {
        setIncierto(e instanceof ApiError ? mensaje
          : `No se supo si ARCA recibió el pedido (${mensaje}). Verificá en Cartas de porte antes de intentar de nuevo.`)
        setPaso('incierto')
      } else {
        // 409/422: ARCA o el servidor dijeron que no ANTES de emitir. Se corrige y se vuelve a enviar.
        setErrorDeEnvio(mensaje)
      }
    } finally {
      enviandoYa.current = false
      setEnviando(false)
    }
  }

  const cartelDeEstado = estado && !estado.puede_emitir
    ? (estado.ambiente === null
      ? 'No hay un certificado de «CTG y Carta de Porte» cargado: cargalo en Configuración / ARCA.'
      : 'La emisión real está apagada. La habilita un administrador en Configuración / ARCA.')
    : null
  const puedeAvanzar = Boolean(cuit) && estado !== null && estado.puede_emitir && !cargando
  const puedeEmitir = !enviando && b !== null && cantidadDeProblemas === 0 && (!produccion || confirmo)

  // ── Pasos ──
  let cuerpo: React.ReactNode
  let pie: React.ReactNode

  if (paso === 'titular') {
    // Un titular al que se le puede emitir tiene que estar delegado en ARCA (ADR-044): el listado ya trae ese estado
    // leído del ticket. Si no se pudo leer, se dice por qué y no se ofrece a nadie: no se adivina una delegación.
    const sinOpciones = titulares !== null && titulares.verificado && opcionesDeTitular.length === 0
    // Sin certificado, la lista también viene sin verificar: lo dice el cartel de estado y no hace falta repetirlo.
    const errorVisible = (errorDeAcceso ?? (titulares && !titulares.verificado ? titulares.motivo : null))
    const mostrarError = errorVisible && estado?.ambiente !== null ? errorVisible : null
    cuerpo = (
      <div className="grid gap-3">
        <p className="text-sm">
          La carta de porte se emite <strong>a nombre de un titular</strong> que le delegó la emisión a este
          certificado en ARCA. Elegí a nombre de quién va: no se puede cambiar después.
        </p>
        {errorDeEstado && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeEstado}</p>}
        {cartelDeEstado && (
          <p role="alert" className="rounded border-2 border-destructive p-3 text-sm font-medium">{cartelDeEstado}</p>
        )}
        {mostrarError && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{mostrarError}</p>}
        {titulares === null && !errorDeAcceso ? (
          <p className="text-muted-foreground text-sm">Consultando a ARCA por quién se puede emitir…</p>
        ) : titulares && titulares.verificado && (
          <Elegir id="cpe-titular" etiqueta="A nombre de" vacio="Elegir…" valor={cuit}
                  opciones={opcionesDeTitular.map((o) => ({ id: o.cuit, etiqueta: o.etiqueta }))}
                  alCambiar={setCuit} />
        )}
        {titular?.sinCargar && (
          <p role="status" className="text-muted-foreground text-xs">
            Este CUIT le delegó la emisión a este certificado en ARCA, pero no está cargado en Cartas de porte →
            Titulares: cargalo ahí para guardar sus datos habituales.
          </p>
        )}
        {sinOpciones && (
          <p role="alert" className="text-destructive text-xs">
            Ningún titular activo le delegó la emisión a este certificado (o emiten ellos mismos): revisá la pestaña
            Titulares de Cartas de porte.
          </p>
        )}
        {produccion && <p className="text-muted-foreground text-xs">Ambiente: producción</p>}
        {homologacion && (
          <p className="text-xs font-medium text-amber-800 dark:text-amber-400">
            Ambiente: homologación (de prueba, sin efecto fiscal)
          </p>
        )}
        {errorDePaso && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDePaso}</p>}
      </div>
    )
    pie = (
      <>
        <Button variant="ghost" onClick={alCerrar}>Cancelar</Button>
        {(errorDeAcceso || errorDeEstado) && (
          <Button variant="outline" onClick={() => setIntento(intento + 1)}>Reintentar</Button>
        )}
        <Button onClick={irADatos} disabled={!puedeAvanzar}>
          {cargando ? 'Pidiendo los datos…' : 'Siguiente'}
        </Button>
      </>
    )
  } else if (paso === 'datos' && b && propuesta) {
    const locOrigen = localidades[b.origenProvincia] ?? SIN_CATALOGO
    const locDestino = localidades[b.destinoProvincia] ?? SIN_CATALOGO
    const neto = netoDe(b)
    const listaDePlantas = plantas?.cuit === cuitDelDestino ? plantas.lista : null
    const numerosDePlanta = new Set((listaDePlantas ?? []).map((p) => String(p.numero)))
    const opcionesDePlanta: OpcionDeArca[] = (listaDePlantas ?? []).map((p) => ({
      codigo: p.numero, nombre: `Planta ${p.numero}`,
    }))
    // Una planta que viene de la plantilla y ARCA no lista no se pierde en silencio: queda elegible, a la vista.
    if (b.destinoPlanta && !numerosDePlanta.has(b.destinoPlanta)) {
      opcionesDePlanta.push({ codigo: Number(b.destinoPlanta), nombre: `Planta ${b.destinoPlanta}` })
    }
    const hayIntervinientes = INTERVINIENTES.some((i) => b.intervinientes[i.clave])
      || b.remitenteProductor || b.cuitIntermediario

    cuerpo = (
      <form id="cpe-datos" className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (!cantidadDeProblemas) setPaso('confirmar') }}>
        {(propuesta.faltantes.length > 0) && (
          <section aria-label="Avisos" role="alert"
                   className="rounded-md border border-amber-600/50 bg-amber-500/10 p-3 text-sm">
            <p className="flex items-center gap-2 font-medium"><TriangleAlert className="size-4" /> Falta completar</p>
            <ul className="mt-1 list-disc pl-6">
              {propuesta.faltantes.map((f) => <li key={f}>{f}</li>)}
            </ul>
          </section>
        )}
        {propuesta.de_plantilla && (
          <p role="status" className="text-muted-foreground text-sm">
            Se completó con lo último emitido para este titular.
          </p>
        )}
        {errorDeCatalogo && (
          <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeCatalogo}</p>
        )}

        <Seccion titulo="Origen">
          <Campo id="cpe-origen-tipo" etiqueta="Tipo de origen">
            <select id="cpe-origen-tipo" className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
                    value={b.origenTipo}
                    onChange={(e) => cambiar('origenTipo', e.target.value === 'planta' ? 'planta' : 'campo')}>
              <option value="campo">Campo</option>
              <option value="planta">Planta</option>
            </select>
          </Campo>
          <Catalogo id="cpe-origen-provincia" etiqueta="Provincia de origen" valor={b.origenProvincia}
                    opciones={provincias} error={problemas.origenProvincia}
                    alCambiar={(v) => setB({ ...b, origenProvincia: v, origenLocalidad: '' })} />
          <Catalogo id="cpe-origen-localidad" etiqueta="Localidad de origen" valor={b.origenLocalidad}
                    opciones={locOrigen} error={problemas.origenLocalidad} deshabilitado={!b.origenProvincia}
                    alCambiar={(v) => cambiar('origenLocalidad', v)} />
          {b.origenTipo === 'planta' ? (
            <TextoNumero id="cpe-origen-planta" etiqueta="N.º de planta de origen" valor={b.origenPlanta}
                         error={problemas.origenPlanta} alCambiar={(v) => cambiar('origenPlanta', v)} />
          ) : (
            <Texto id="cpe-origen-renspa" etiqueta="RENSPA" valor={b.origenRenspa} ayuda="Opcional."
                   alCambiar={(v) => cambiar('origenRenspa', v)} />
          )}
        </Seccion>

        <Seccion titulo="Carga">
          <Catalogo id="cpe-grano" etiqueta="Grano" valor={b.codGrano} opciones={granos} error={problemas.codGrano}
                    alCambiar={(v) => cambiar('codGrano', v)} />
          <Texto id="cpe-cosecha" etiqueta="Cosecha" valor={b.cosecha} maxLength={4} inputMode="numeric"
                 ayuda="2526 = 2025/2026" error={problemas.cosecha}
                 alCambiar={(v) => cambiar('cosecha', v.replace(/\D/g, ''))} />
          <TextoNumero id="cpe-bruto" etiqueta="Peso bruto (kg)" valor={b.pesoBruto} error={problemas.pesoBruto}
                       alCambiar={(v) => cambiar('pesoBruto', v)} />
          <TextoNumero id="cpe-tara" etiqueta="Peso tara (kg)" valor={b.pesoTara} error={problemas.pesoTara}
                       alCambiar={(v) => cambiar('pesoTara', v)} />
          <p className="text-sm md:col-span-2" aria-live="polite">
            Neto: <strong className="tabular-nums">{neto != null && neto > 0 ? `${formatearKilos(neto)} kg` : '—'}</strong>
            <span className="text-muted-foreground"> (bruto menos tara)</span>
          </p>
        </Seccion>

        <Seccion titulo="Destino">
          <TextoCuit id="cpe-destino-cuit" etiqueta="CUIT del destino" valor={b.destinoCuit}
                     error={problemas.destinoCuit} alCambiar={cambiarDestinoCuit} />
          {opcionesDePlanta.length > 0 ? (
            <Catalogo id="cpe-destino-planta" etiqueta="N.º de planta de destino" valor={b.destinoPlanta}
                      opciones={opcionesDePlanta} alCambiar={(v) => cambiar('destinoPlanta', v)} />
          ) : (
            <TextoNumero id="cpe-destino-planta" etiqueta="N.º de planta de destino" valor={b.destinoPlanta}
                         ayuda={cuitDelDestino.length === 11 && plantas?.cuit === cuitDelDestino
                           ? 'ARCA no informó plantas para este CUIT: escribí el número.' : undefined}
                         alCambiar={(v) => cambiar('destinoPlanta', v)} />
          )}
          <Catalogo id="cpe-destino-provincia" etiqueta="Provincia de destino" valor={b.destinoProvincia}
                    opciones={provincias} error={problemas.destinoProvincia}
                    alCambiar={(v) => setB({ ...b, destinoProvincia: v, destinoLocalidad: '' })} />
          <Catalogo id="cpe-destino-localidad" etiqueta="Localidad de destino" valor={b.destinoLocalidad}
                    opciones={locDestino} error={problemas.destinoLocalidad} deshabilitado={!b.destinoProvincia}
                    alCambiar={(v) => cambiar('destinoLocalidad', v)} />
          <Casilla id="cpe-destino-campo" etiqueta="El destino es un campo" marcada={b.destinoEsCampo}
                   alCambiar={(v) => cambiar('destinoEsCampo', v)} />
          <TextoCuit id="cpe-destinatario" etiqueta="CUIT del destinatario" valor={b.cuitDestinatario}
                     ayuda="Por defecto, el del destino." error={problemas.cuitDestinatario}
                     alCambiar={(v) => cambiar('cuitDestinatario', v)} />
        </Seccion>

        <Seccion titulo="Transporte">
          <TextoCuit id="cpe-transportista" etiqueta="CUIT del transportista" valor={b.cuitTransportista}
                     ayuda="Por defecto, el fletero de la orden; puede ser la propia empresa u otro."
                     error={problemas.cuitTransportista} alCambiar={(v) => cambiar('cuitTransportista', v)} />
          <TextoCuit id="cpe-chofer" etiqueta="CUIT del chofer" valor={b.cuitChofer} error={problemas.cuitChofer}
                     alCambiar={(v) => cambiar('cuitChofer', v)} />
          <div className="grid gap-1 md:col-span-2">
            <div className="grid gap-3 sm:grid-cols-3">
              {Array.from({ length: MAX_DOMINIOS }, (_, i) => (
                <Texto key={i} id={`cpe-dominio-${i + 1}`}
                       etiqueta={i === 0 ? 'Dominio 1 (chasis)' : `Dominio ${i + 1} (acoplado)`}
                       valor={b.dominios[i] ?? ''} maxLength={7} autoCapitalize="characters"
                       aria-invalid={problemas.dominios && i === 0 ? true : undefined}
                       alCambiar={(v) => setB({
                         ...b, dominios: b.dominios.map((d, j) => (j === i ? v.toUpperCase().replace(/\s/g, '') : d)),
                       })} />
              ))}
            </div>
            {problemas.dominios
              ? <p className="text-destructive text-xs">{problemas.dominios}</p>
              : <p className="text-muted-foreground text-xs">De 1 a 3 dominios; cada uno de 6 o 7 caracteres.</p>}
          </div>
          <Texto id="cpe-partida" etiqueta="Fecha y hora de partida" type="datetime-local" valor={b.partida}
                 ayuda="Hora argentina. Se propone dentro de una hora."
                 error={problemas.partida} alCambiar={(v) => cambiar('partida', v)} />
          <TextoNumero id="cpe-km" etiqueta="Kilómetros a recorrer" valor={b.km} error={problemas.km}
                       alCambiar={(v) => cambiar('km', v)} />
          <TextoCuit id="cpe-pagador" etiqueta="CUIT del pagador del flete" valor={b.cuitPagador}
                     error={problemas.cuitPagador} alCambiar={(v) => cambiar('cuitPagador', v)} />
          <Texto id="cpe-tarifa" etiqueta="Tarifa por tonelada ($)" valor={b.tarifa} inputMode="decimal"
                 ayuda="Opcional." error={problemas.tarifa}
                 alCambiar={(v) => cambiar('tarifa', v.replace(/[^\d.,]/g, ''))} />
          <Casilla id="cpe-fumigada" etiqueta="Mercadería fumigada" marcada={b.fumigada}
                   alCambiar={(v) => cambiar('fumigada', v)} />
        </Seccion>

        <details open={Boolean(hayIntervinientes)} className="rounded-md border p-4">
          <summary className="cursor-pointer text-sm font-semibold">Intervinientes (opcionales)</summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {INTERVINIENTES.map(({ clave, etiqueta }) => (
              <TextoCuit key={clave} id={`cpe-int-${clave}`} etiqueta={etiqueta}
                         valor={b.intervinientes[clave] ?? ''} error={problemas[`interviniente:${clave}`]}
                         alCambiar={(v) => setB({ ...b, intervinientes: { ...b.intervinientes, [clave]: v } })} />
            ))}
            <TextoCuit id="cpe-remitente-productor" etiqueta="Remitente comercial productor (retira el productor)"
                       valor={b.remitenteProductor} error={problemas.remitenteProductor}
                       alCambiar={(v) => cambiar('remitenteProductor', v)} />
            <TextoCuit id="cpe-intermediario" etiqueta="Intermediario del flete" valor={b.cuitIntermediario}
                       error={problemas.cuitIntermediario} alCambiar={(v) => cambiar('cuitIntermediario', v)} />
          </div>
        </details>

        <Campo id="cpe-observaciones" etiqueta="Observaciones" error={problemas.observaciones}>
          <textarea id="cpe-observaciones" rows={2} value={b.observaciones}
                    onChange={(e) => cambiar('observaciones', e.target.value)}
                    className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm" />
        </Campo>
      </form>
    )
    pie = (
      <>
        {cantidadDeProblemas > 0 && (
          <p role="status" className="text-destructive mr-auto self-center text-sm">
            {cantidadDeProblemas === 1
              ? 'Hay 1 dato obligatorio o con error.' : `Hay ${cantidadDeProblemas} datos obligatorios o con error.`}
          </p>
        )}
        <Button variant="ghost" onClick={alCerrar}>Cancelar</Button>
        <Button variant="outline" onClick={() => setPaso('titular')}>Atrás</Button>
        <Button type="submit" form="cpe-datos" disabled={cantidadDeProblemas > 0}>Revisar</Button>
      </>
    )
  } else if (paso === 'confirmar' && b) {
    const nombreDeLoc = (prov: string, loc: string) => {
      const l = nombreDel(localidades[prov], loc)
      const p = nombreDel(provincias, prov)
      return [l || `Localidad ${loc}`, p].filter(Boolean).join(', ')
    }
    const neto = netoDe(b)
    const dominios = b.dominios.map((d) => d.trim()).filter(Boolean).join(', ')
    const filas: [string, React.ReactNode][] = [
      ['Titular', `${nombreDelTitular} (${formatearCuit(cuit)})`],
      ['Origen', `${b.origenTipo === 'planta' ? `Planta ${b.origenPlanta} · ` : ''}${nombreDeLoc(b.origenProvincia, b.origenLocalidad)}`],
      ['Destino', `${nombreDeLoc(b.destinoProvincia, b.destinoLocalidad)}${b.destinoPlanta ? ` · Planta ${b.destinoPlanta}` : ''}${b.destinoEsCampo ? ' · Campo' : ''}`],
      ['Destinatario', `${formatearCuit(b.cuitDestinatario)}${b.destinoCuit !== b.cuitDestinatario ? '' : ' (el destino)'}`],
      ['Grano', `${nombreDel(granos, b.codGrano) || b.codGrano} · cosecha ${b.cosecha}`],
      ['Kilos', `${formatearKilos(Number(b.pesoBruto))} bruto − ${formatearKilos(Number(b.pesoTara))} tara = ${neto != null ? formatearKilos(neto) : '—'} neto`],
      ['Transportista', formatearCuit(b.cuitTransportista)],
      ['Chofer', formatearCuit(b.cuitChofer)],
      ['Dominios', dominios],
      ['Partida', formatearInstante(`${b.partida}:00-03:00`)],
      ['Kilómetros', formatearKilos(Number(b.km))],
      ['Pagador del flete', formatearCuit(b.cuitPagador)],
      ['Tarifa por tonelada', b.tarifa.trim() ? formatearImporte(b.tarifa.trim().replace(',', '.')) : '—'],
      ['Mercadería fumigada', b.fumigada ? 'Sí' : 'No'],
    ]
    if (b.observaciones.trim()) filas.push(['Observaciones', b.observaciones.trim()])

    cuerpo = (
      <div className="grid gap-4">
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
          {filas.map(([etiqueta, valor]) => (
            <div key={etiqueta} className="min-w-0">
              <dt className="text-muted-foreground text-xs">{etiqueta}</dt>
              <dd className="font-medium break-words">{valor}</dd>
            </div>
          ))}
        </dl>
        {produccion && (
          <div role="alert" className="border-destructive bg-destructive/10 grid gap-3 rounded-md border-2 p-4">
            <p className="font-semibold">
              Vas a emitir una Carta de Porte REAL ante ARCA a nombre de {nombreDelTitular}. Queda registrada y sólo
              se puede anular.
            </p>
            <div className="flex items-center gap-2">
              <input id="cpe-confirmo" type="checkbox" checked={confirmo} disabled={enviando}
                     onChange={(e) => setConfirmo(e.target.checked)} className="size-4" />
              <Label htmlFor="cpe-confirmo" className="font-semibold">Confirmo</Label>
            </div>
          </div>
        )}
        {homologacion && (
          <p role="status" className="rounded-md border border-amber-600/50 bg-amber-500/10 p-3 text-sm font-medium">
            Homologación: es de prueba, no tiene efecto fiscal.
          </p>
        )}
        {errorDeEnvio && (
          <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeEnvio}</p>
        )}
      </div>
    )
    pie = (
      <>
        <Button variant="ghost" onClick={alCerrar} disabled={enviando}>Cancelar</Button>
        <Button variant="outline" onClick={() => setPaso('datos')} disabled={enviando}>Atrás</Button>
        <Button onClick={emitir} disabled={!puedeEmitir} variant={produccion ? 'destructive' : 'default'}>
          {enviando ? 'Emitiendo…' : 'Emitir ahora'}
        </Button>
      </>
    )
  } else if (paso === 'resultado' && emitida && b) {
    cuerpo = (
      <div className="grid gap-4">
        <p role="status" className="text-sm font-medium">
          {emitida.ambiente === 'homologacion'
            ? 'La carta de porte se emitió en homologación: es de prueba, no tiene efecto fiscal.'
            : 'La carta de porte se emitió en ARCA.'}
        </p>
        <div className="grid gap-4 rounded-md border p-4 sm:grid-cols-2">
          <div>
            <p className="text-muted-foreground text-xs">CTG</p>
            <p className="text-3xl font-semibold tabular-nums">{emitida.nro_ctg}</p>
          </div>
          <div>
            <p className="text-muted-foreground text-xs">N.º de carta de porte</p>
            <p className="text-3xl font-semibold tabular-nums">{emitida.numero}</p>
          </div>
        </div>
        {emitida.tiene_pdf ? (
          <div className="grid gap-3">
            <div className="flex flex-wrap gap-2">
              {emitida.id !== null && (
                <Button asChild>
                  <a href={cartasPorte.urlDelPdf(emitida.id)} target="_blank" rel="noreferrer">Ver PDF</a>
                </Button>
              )}
            </div>
            <CompartirCartaDePorte
              carta={emitida}
              origen={nombreDel(localidades[b.origenProvincia], b.origenLocalidad) || undefined}
              destino={nombreDel(localidades[b.destinoProvincia], b.destinoLocalidad) || undefined} />
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">
            ARCA todavía no devolvió el PDF. Cuando lo tenga, lo vas a encontrar en Cartas de porte.
          </p>
        )}
      </div>
    )
    pie = <Button onClick={alCerrar}>Cerrar</Button>
  } else if (paso === 'incierto') {
    cuerpo = (
      <div role="alert" className="border-destructive bg-destructive/10 grid gap-3 rounded-md border-2 p-4">
        <p className="flex items-center gap-2 text-base font-semibold">
          <TriangleAlert className="size-5" /> No se sabe si la carta de porte se emitió
        </p>
        <p className="text-sm font-medium">{incierto}</p>
        <p className="text-sm">
          <strong>No la vuelvas a emitir.</strong> Primero verificá en Cartas de porte (con «Traer de ARCA» y el CTG)
          si quedó emitida: emitirla de nuevo puede duplicar una carta de porte real.
        </p>
      </div>
    )
    pie = (
      <>
        <Button variant="ghost" onClick={alCerrar}>Cerrar</Button>
        <Button asChild variant="outline"><Link to="/cartas-porte">Ir a Cartas de porte</Link></Button>
      </>
    )
  } else {
    cuerpo = null
    pie = <Button onClick={alCerrar}>Cerrar</Button>
  }

  return (
    <div className="grid gap-4">
      {paso !== 'incierto' && (
        <ol aria-label="Pasos" className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {PASOS.map(({ paso: p, etiqueta }, i) => (
            <li key={p} aria-current={p === paso ? 'step' : undefined}
                className={cn(p === paso && 'text-foreground font-semibold')}>
              {i + 1}. {etiqueta}
            </li>
          ))}
        </ol>
      )}
      {cuerpo}
      <div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-end">{pie}</div>
    </div>
  )
}

/** El asistente, sin título: el título y la carga de la orden son de la página. `alSalir` es lo que hacen «Cancelar» y
 *  «Cerrar» (volver a la orden). */
export function EmitirCartaDePorte({ orden, alSalir, alEmitida }: {
  orden: Orden
  alSalir: () => void
  /** Se llama con la carta emitida, por si la pantalla de atrás quiere refrescarse. */
  alEmitida?: (carta: CartaPorte) => void
}) {
  return <Asistente orden={orden} alCerrar={alSalir} alEmitida={alEmitida} />
}
