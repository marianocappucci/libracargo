/** La plantilla de un titular: sus datos habituales para emitir la carta de porte (ADR-043, ADR-044).
 *
 *  «Emitir carta de porte» la llena sola con lo último emitido a nombre del titular; acá se puede mirar y corregir antes de
 *  la primera carta, o cuando algo cambia (otra planta, otro grano, otro corredor).
 *
 *  🔑 **Mismas claves, mismas reglas y mismos campos que el asistente.** El borrador, el formato válido de cada dato y los
 *  campos son los de `emision-cpe.ts` y `campos-cpe.tsx`; lo que se guarda es lo que `propuesta()` del servidor lee de la
 *  plantilla. La diferencia es una sola: acá **nada es obligatorio**, porque una plantilla puede ser parcial y lo que
 *  falte lo completa quien emite (el viaje —chofer, dominios, kilos, partida— nunca va en la plantilla).
 *
 *  🔑 **Los catálogos son de ARCA** (grano, provincia, localidad, planta) y se piden "en nombre de" un CUIT delegado. Un
 *  titular que todavía no está delegado no puede pedirlos con el suyo: se usa otro por el que el ticket deja operar
 *  (`cuit_para_catalogos`), porque son los mismos para todos. Sin ninguno, o si ARCA no contesta, se dice y lo ya guardado
 *  se conserva a la vista: un dato de la plantilla no se pierde en silencio por no estar en una lista.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import type { OpcionDeArca, Planta, PlantillaGuardada, Titular } from '@/api/cartas-porte'
import { cartasPorte, formatearInstante } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import {
  Campo, Casilla, Catalogo, Seccion, Texto, TextoCuit, TextoNumero,
} from '@/components/campos-cpe'
import type { BorradorDePlantilla } from '@/components/emision-cpe'
import {
  INTERVINIENTES, borradorDePlantilla, datosDePlantilla, problemasDePlantilla,
} from '@/components/emision-cpe'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/confirm-dialog'

const SIN_CATALOGO: OpcionDeArca[] = []

/** El catálogo, más el valor ya elegido si no está: un código guardado que ARCA no lista no desaparece. */
function conActual(lista: OpcionDeArca[], valor: string, rotulo: string): OpcionDeArca[] {
  if (!valor || lista.some((o) => String(o.codigo) === valor)) return lista
  return [...lista, { codigo: Number(valor), nombre: `${rotulo} ${valor}` }]
}

export function PlantillaDeTitular({ titular, cuitParaCatalogos, puedeEditar, alCambiar }: {
  titular: Titular
  /** Un CUIT por el que el ticket deja operar, si el del titular todavía no está delegado. */
  cuitParaCatalogos: string | null
  puedeEditar: boolean
  /** Se llama tras guardar o borrar, para que el listado refleje «tiene plantilla». */
  alCambiar?: () => void
}) {
  const [guardada, setGuardada] = useState<PlantillaGuardada | null>(null)
  const [b, setB] = useState<BorradorDePlantilla | null>(null)
  const [errorDeCarga, setErrorDeCarga] = useState<string | null>(null)
  const [errorDeGuardar, setErrorDeGuardar] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [confirmandoBorrar, setConfirmandoBorrar] = useState(false)
  const [granos, setGranos] = useState<OpcionDeArca[]>(SIN_CATALOGO)
  const [provincias, setProvincias] = useState<OpcionDeArca[]>(SIN_CATALOGO)
  const [localidades, setLocalidades] = useState<Record<string, OpcionDeArca[]>>({})
  const [errorDeCatalogo, setErrorDeCatalogo] = useState<string | null>(null)
  const [plantas, setPlantas] = useState<{ cuit: string; lista: Planta[] | null } | null>(null)
  const pedidas = useRef(new Set<string>())

  const cuitDeCatalogos = titular.delegacion === 'delegado' ? titular.cuit : cuitParaCatalogos

  // La plantilla guardada.
  useEffect(() => {
    let vigente = true
    setGuardada(null); setB(null); setErrorDeCarga(null); setAviso(null)
    cartasPorte.plantilla(titular.id)
      .then((r) => { if (vigente) { setGuardada(r); setB(borradorDePlantilla(r.datos)) } })
      .catch((e) => { if (vigente) setErrorDeCarga(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [titular.id])

  // Los catálogos de ARCA que no dependen de la provincia.
  useEffect(() => {
    let vigente = true
    pedidas.current = new Set(); setLocalidades({}); setPlantas(null); setGranos(SIN_CATALOGO); setProvincias(SIN_CATALOGO)
    if (!cuitDeCatalogos) {
      setErrorDeCatalogo('Los catálogos de ARCA se piden con un titular delegado y todavía no hay ninguno: '
        + 'lo ya guardado se ve, pero no se puede elegir otra cosa.')
      return
    }
    setErrorDeCatalogo(null)
    Promise.all([cartasPorte.granos(cuitDeCatalogos), cartasPorte.provincias(cuitDeCatalogos)])
      .then(([g, p]) => { if (vigente) { setGranos(g); setProvincias(p) } })
      .catch((e) => { if (vigente) setErrorDeCatalogo(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [cuitDeCatalogos])

  // Las localidades se piden por provincia, la primera vez que se elige.
  const provinciaDeOrigen = b?.origenProvincia ?? ''
  const provinciaDeDestino = b?.destinoProvincia ?? ''
  useEffect(() => {
    if (!cuitDeCatalogos) return
    for (const provincia of new Set([provinciaDeOrigen, provinciaDeDestino])) {
      if (!provincia || pedidas.current.has(provincia)) continue
      pedidas.current.add(provincia)
      cartasPorte.localidades(cuitDeCatalogos, Number(provincia))
        .then((lista) => setLocalidades((l) => ({ ...l, [provincia]: lista })))
        .catch((e) => { pedidas.current.delete(provincia); setErrorDeCatalogo(mensajeDeError(e)) })
    }
  }, [cuitDeCatalogos, provinciaDeOrigen, provinciaDeDestino])

  // Las plantas inscriptas del destino, cuando ya hay un CUIT completo.
  const cuitDelDestino = (b?.destinoCuit ?? '').replace(/\D/g, '')
  useEffect(() => {
    if (!cuitDeCatalogos || cuitDelDestino.length !== 11) return
    let vigente = true
    cartasPorte.plantas(cuitDeCatalogos, cuitDelDestino)
      .then((lista) => { if (vigente) setPlantas({ cuit: cuitDelDestino, lista }) })
      .catch(() => { if (vigente) setPlantas({ cuit: cuitDelDestino, lista: null }) })
    return () => { vigente = false }
  }, [cuitDeCatalogos, cuitDelDestino])

  const problemas = useMemo(() => (b ? problemasDePlantilla(b) : {}), [b])
  const cantidadDeProblemas = Object.keys(problemas).length

  function cambiar<K extends keyof BorradorDePlantilla>(campo: K, valor: BorradorDePlantilla[K]) {
    setB((actual) => (actual ? { ...actual, [campo]: valor } : actual))
    setAviso(null)
  }

  async function guardar() {
    if (!b || ocupado || cantidadDeProblemas > 0) return
    setErrorDeGuardar(null); setAviso(null); setOcupado(true)
    try {
      const r = await cartasPorte.guardarPlantilla(titular.id, datosDePlantilla(b))
      setGuardada(r); setB(borradorDePlantilla(r.datos))
      setAviso('Plantilla guardada. La próxima carta de este titular arranca con estos datos.')
      alCambiar?.()
    } catch (e) {
      setErrorDeGuardar(mensajeDeError(e))
    } finally {
      setOcupado(false)
    }
  }

  async function borrar() {
    setConfirmandoBorrar(false)
    setErrorDeGuardar(null); setAviso(null); setOcupado(true)
    try {
      await cartasPorte.borrarPlantilla(titular.id)
      const vacia = { datos: {}, existe: false, actualizada: null }
      setGuardada(vacia); setB(borradorDePlantilla(vacia.datos))
      setAviso('Plantilla borrada.')
      alCambiar?.()
    } catch (e) {
      setErrorDeGuardar(mensajeDeError(e))
    } finally {
      setOcupado(false)
    }
  }

  if (errorDeCarga) {
    return <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeCarga}</p>
  }
  if (!b || !guardada) return <p className="text-muted-foreground text-sm">Cargando la plantilla…</p>

  const listaDePlantas = plantas?.cuit === cuitDelDestino ? plantas.lista : null
  const opcionesDePlanta = conActual(
    (listaDePlantas ?? []).map((p) => ({ codigo: p.numero, nombre: `Planta ${p.numero}` })), b.destinoPlanta, 'Planta')
  const hayIntervinientes = INTERVINIENTES.some((i) => b.intervinientes[i.clave]) || b.remitenteProductor

  return (
    <section aria-label="Datos habituales para emitir" className="grid gap-3">
      <div>
        <h3 className="text-sm font-semibold">Datos habituales para emitir</h3>
        <p className="text-muted-foreground text-xs">
          «Emitir carta de porte» arranca con esto para {titular.razon_social}. Se actualiza solo con lo último que se
          emite a su nombre. Todo es opcional: el viaje (chofer, dominios, kilos, partida) se completa en cada carta.
          {guardada.existe && guardada.actualizada && ` Última actualización: ${formatearInstante(guardada.actualizada)}.`}
        </p>
      </div>
      {errorDeCatalogo && (
        <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeCatalogo}</p>
      )}
      {/* Un staff mira y no toca: el `fieldset` apaga todos los campos de adentro. */}
      <fieldset disabled={!puedeEditar || ocupado} className="grid min-w-0 gap-4">
        <Seccion titulo="Origen">
          <Campo id="pl-origen-tipo" etiqueta="Tipo de origen">
            <select id="pl-origen-tipo" className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
                    value={b.origenTipo}
                    onChange={(e) => cambiar('origenTipo', e.target.value === 'planta' ? 'planta' : 'campo')}>
              <option value="campo">Campo</option>
              <option value="planta">Planta</option>
            </select>
          </Campo>
          <Catalogo id="pl-origen-provincia" etiqueta="Provincia de origen" valor={b.origenProvincia}
                    opciones={conActual(provincias, b.origenProvincia, 'Provincia')}
                    alCambiar={(v) => setB({ ...b, origenProvincia: v, origenLocalidad: '' })} />
          <Catalogo id="pl-origen-localidad" etiqueta="Localidad de origen" valor={b.origenLocalidad}
                    opciones={conActual(localidades[b.origenProvincia] ?? SIN_CATALOGO, b.origenLocalidad, 'Localidad')}
                    deshabilitado={!b.origenProvincia} alCambiar={(v) => cambiar('origenLocalidad', v)} />
          {b.origenTipo === 'planta' ? (
            <TextoNumero id="pl-origen-planta" etiqueta="N.º de planta de origen" valor={b.origenPlanta}
                         alCambiar={(v) => cambiar('origenPlanta', v)} />
          ) : (
            <Texto id="pl-origen-renspa" etiqueta="RENSPA" valor={b.origenRenspa} maxLength={30}
                   ayuda="Opcional." alCambiar={(v) => cambiar('origenRenspa', v)} />
          )}
        </Seccion>

        <Seccion titulo="Carga">
          <Catalogo id="pl-grano" etiqueta="Grano" valor={b.codGrano} opciones={conActual(granos, b.codGrano, 'Grano')}
                    alCambiar={(v) => cambiar('codGrano', v)} />
          <Texto id="pl-cosecha" etiqueta="Cosecha" valor={b.cosecha} maxLength={4} inputMode="numeric"
                 ayuda="2526 = 2025/2026" error={problemas.cosecha}
                 alCambiar={(v) => cambiar('cosecha', v.replace(/\D/g, ''))} />
        </Seccion>

        <Seccion titulo="Destino">
          <TextoCuit id="pl-destino-cuit" etiqueta="CUIT del destino" valor={b.destinoCuit}
                     error={problemas.destinoCuit}
                     alCambiar={(v) => setB({
                       ...b, destinoCuit: v,
                       cuitDestinatario: b.cuitDestinatario === '' || b.cuitDestinatario === b.destinoCuit
                         ? v : b.cuitDestinatario,
                       destinoPlanta: v === b.destinoCuit ? b.destinoPlanta : '',
                     })} />
          {opcionesDePlanta.length > 0 ? (
            <Catalogo id="pl-destino-planta" etiqueta="N.º de planta de destino" valor={b.destinoPlanta}
                      opciones={opcionesDePlanta} alCambiar={(v) => cambiar('destinoPlanta', v)} />
          ) : (
            <TextoNumero id="pl-destino-planta" etiqueta="N.º de planta de destino" valor={b.destinoPlanta}
                         alCambiar={(v) => cambiar('destinoPlanta', v)} />
          )}
          <Catalogo id="pl-destino-provincia" etiqueta="Provincia de destino" valor={b.destinoProvincia}
                    opciones={conActual(provincias, b.destinoProvincia, 'Provincia')}
                    alCambiar={(v) => setB({ ...b, destinoProvincia: v, destinoLocalidad: '' })} />
          <Catalogo id="pl-destino-localidad" etiqueta="Localidad de destino" valor={b.destinoLocalidad}
                    opciones={conActual(localidades[b.destinoProvincia] ?? SIN_CATALOGO, b.destinoLocalidad, 'Localidad')}
                    deshabilitado={!b.destinoProvincia} alCambiar={(v) => cambiar('destinoLocalidad', v)} />
          <Casilla id="pl-destino-campo" etiqueta="El destino es un campo" marcada={b.destinoEsCampo}
                   alCambiar={(v) => cambiar('destinoEsCampo', v)} />
          <TextoCuit id="pl-destinatario" etiqueta="CUIT del destinatario" valor={b.cuitDestinatario}
                     ayuda="Por defecto, el del destino." error={problemas.cuitDestinatario}
                     alCambiar={(v) => cambiar('cuitDestinatario', v)} />
        </Seccion>

        <Seccion titulo="Transporte">
          <TextoNumero id="pl-km" etiqueta="Kilómetros habituales" valor={b.km} error={problemas.km}
                       ayuda="Si la orden tiene los suyos, mandan los de la orden."
                       alCambiar={(v) => cambiar('km', v)} />
          <Casilla id="pl-fumigada" etiqueta="Mercadería fumigada" marcada={b.fumigada}
                   alCambiar={(v) => cambiar('fumigada', v)} />
        </Seccion>

        <details open={Boolean(hayIntervinientes)} className="rounded-md border p-4">
          <summary className="cursor-pointer text-sm font-semibold">Intervinientes (opcionales)</summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {INTERVINIENTES.map(({ clave, etiqueta }) => (
              <TextoCuit key={clave} id={`pl-int-${clave}`} etiqueta={etiqueta}
                         valor={b.intervinientes[clave] ?? ''} error={problemas[`interviniente:${clave}`]}
                         alCambiar={(v) => setB({ ...b, intervinientes: { ...b.intervinientes, [clave]: v } })} />
            ))}
            <TextoCuit id="pl-remitente-productor" etiqueta="Remitente comercial productor (retira el productor)"
                       valor={b.remitenteProductor} error={problemas.remitenteProductor}
                       alCambiar={(v) => cambiar('remitenteProductor', v)} />
          </div>
        </details>

        <Campo id="pl-observaciones" etiqueta="Observaciones" error={problemas.observaciones}>
          <textarea id="pl-observaciones" rows={2} value={b.observaciones}
                    onChange={(e) => cambiar('observaciones', e.target.value)}
                    className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm" />
        </Campo>
      </fieldset>

      {errorDeGuardar && (
        <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{errorDeGuardar}</p>
      )}
      {aviso && <p role="status" className="text-sm">{aviso}</p>}
      {puedeEditar && (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" onClick={guardar} disabled={ocupado || cantidadDeProblemas > 0}>
            {ocupado ? 'Guardando…' : 'Guardar plantilla'}
          </Button>
          {guardada.existe && (
            <Button type="button" variant="outline" disabled={ocupado} onClick={() => setConfirmandoBorrar(true)}>
              Borrar plantilla
            </Button>
          )}
          {cantidadDeProblemas > 0 && (
            <p role="status" className="text-destructive text-sm">
              {cantidadDeProblemas === 1 ? 'Hay 1 dato con error.' : `Hay ${cantidadDeProblemas} datos con error.`}
            </p>
          )}
        </div>
      )}
      <ConfirmDialog open={confirmandoBorrar} onOpenChange={setConfirmandoBorrar} title="Borrar la plantilla"
                     description="La próxima carta de este titular arranca sin datos. No se borra ninguna carta emitida."
                     confirmLabel="Borrar" onConfirm={borrar} />
    </section>
  )
}
