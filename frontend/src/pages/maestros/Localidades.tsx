/** Configuración → Localidades (ADR-041, ADR-042): el maestro de orígenes y destinos, con el catálogo de Argentina y del
 *  resto del Mercosur detrás.
 *
 *  Cada fila es **del catálogo** (vinculada por su código censal), **un paraje** (un lugar real que no está en ningún
 *  catálogo, cargado a mano con su provincia) o **sin vincular** (las que se fueron cargando a mano antes y todavía no
 *  se emparejaron). La pantalla es la `AbmMaestro` de siempre con tres cosas propias: la columna «Origen», un filtro rápido
 *  de lo que falta vincular y las acciones que cambian de dónde viene una localidad: vincular, marcar como paraje y
 *  —sólo un administrador— unificar dos que son el mismo lugar.
 *
 *  Las altas ya no se tipean: «Agregar del catálogo» trae una localidad oficial y «Cargar paraje» es la excepción.
 */
import { sortableHeader } from 'libra-ui/data-table'
import { BadgeEstado, type TonoEstado } from 'libra-ui/badge-estado'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { Flag, Link2, MapPinPlus, Merge } from 'lucide-react'
import { useState } from 'react'

import { buscarEnElCatalogo, nombreDePais, TODOS_LOS_PAISES } from '@/api/geo'
import {
  conProvincia, ETIQUETA_ORIGEN, localidadesApi, origenDe, type Localidad, type OrigenDeLocalidad,
} from '@/api/localidades'
import { AbmMaestro, mensajeDeError, type ContextoDeLista } from '@/components/AbmMaestro'
import { BuscadorAsincrono, type GrupoBuscado } from '@/components/BuscadorAsincrono'
import { DialogoParaje } from '@/components/DialogoParaje'
import { SelectPais } from '@/components/SelectPais'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/context/AuthContext'

import { CAMPOS_LOCALIDAD } from './definiciones'

type Ctx = ContextoDeLista<Localidad>

/** Del catálogo = neutro (es lo esperado); paraje = azul (una excepción deliberada); sin vincular = ámbar (falta una decisión). */
const TONO_DE_ORIGEN: Record<OrigenDeLocalidad, TonoEstado> = {
  catalogo: 'neutro', paraje: 'curso', sin_vincular: 'atencion',
}

/** Lo que falta resolver: activa, y ni del catálogo ni marcada como paraje. Una baja sin vincular no pide nada a nadie. */
const faltaVincular = (l: Localidad) => l.activo && origenDe(l) === 'sin_vincular'

type Dialogo =
  | { tipo: 'agregar'; ctx: Ctx }
  | { tipo: 'paraje'; ctx: Ctx }
  | { tipo: 'vincular'; ctx: Ctx; fila: Localidad }
  | { tipo: 'marcar'; ctx: Ctx; fila: Localidad }
  | { tipo: 'unificar'; ctx: Ctx; fila: Localidad }

export function Localidades() {
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const [soloSinVincular, setSoloSinVincular] = useState(false)
  const [dialogo, setDialogo] = useState<Dialogo | null>(null)
  const cerrar = () => setDialogo(null)

  /** «Marcar como paraje»: si la fila ya tiene provincia no hay nada que preguntar; si no, se pide en el diálogo. */
  async function marcarComoParaje(fila: Localidad, ctx: Ctx, provincia: string, pais: string) {
    await localidadesApi.editar(fila.id, {
      nombre: fila.nombre, provincia, pais, es_paraje: true, activo: fila.activo,
    })
    ctx.recargar()
    ctx.destacar(fila.id)
  }

  async function alPedirMarcar(fila: Localidad, ctx: Ctx) {
    ctx.fallar(null)
    if (!fila.provincia) { setDialogo({ tipo: 'marcar', ctx, fila }); return }
    try {
      await marcarComoParaje(fila, ctx, fila.provincia, fila.pais)
    } catch (e) {
      ctx.fallar(mensajeDeError(e))
    }
  }

  return (
    <>
      <AbmMaestro<Localidad>
        recurso="localidades"
        titulo="Localidades"
        campos={CAMPOS_LOCALIDAD}
        singular="localidad"
        sinNuevo
        columnas={[
          { accessorKey: 'nombre', header: sortableHeader('Nombre') },
          { accessorKey: 'provincia', header: sortableHeader('Provincia') },
          {
            id: 'pais',
            header: sortableHeader('País'),
            accessorFn: (l: Localidad) => nombreDePais(l.pais),
          },
          {
            id: 'origen',
            header: sortableHeader('Origen'),
            accessorFn: (l: Localidad) => ETIQUETA_ORIGEN[origenDe(l)],
            cell: ({ row }: { row: { original: Localidad } }) => {
              const o = origenDe(row.original)
              return <BadgeEstado tono={TONO_DE_ORIGEN[o]}>{ETIQUETA_ORIGEN[o]}</BadgeEstado>
            },
          },
        ]}
        buscarEn={(l) => [l.nombre, l.provincia, nombreDePais(l.pais), ETIQUETA_ORIGEN[origenDe(l)]]}
        visibles={soloSinVincular ? faltaVincular : undefined}
        barra={(ctx) => (
          <>
            <Button
              type="button" variant={soloSinVincular ? 'default' : 'outline'} aria-pressed={soloSinVincular}
              onClick={() => setSoloSinVincular((v) => !v)}
            >
              Sin vincular ({ctx.filas.filter(faltaVincular).length})
            </Button>
            <Button type="button" variant="outline" onClick={() => setDialogo({ tipo: 'paraje', ctx })}>
              <Flag className="size-4" /> Cargar paraje
            </Button>
            <Button type="button" onClick={() => setDialogo({ tipo: 'agregar', ctx })}>
              <MapPinPlus className="size-4" /> Agregar del catálogo
            </Button>
          </>
        )}
        accionesDeFila={(fila, ctx) => (
          <>
            {!fila.catalogo_id && (
              <Button variant="ghost" size="icon" aria-label="Vincular al catálogo" title="Vincular al catálogo"
                      onClick={() => setDialogo({ tipo: 'vincular', ctx, fila })}>
                <Link2 className="size-4" />
              </Button>
            )}
            {origenDe(fila) === 'sin_vincular' && (
              <Button variant="ghost" size="icon" aria-label="Marcar como paraje" title="Marcar como paraje"
                      onClick={() => void alPedirMarcar(fila, ctx)}>
                <Flag className="size-4" />
              </Button>
            )}
            {esAdmin && fila.activo && (
              <Button variant="ghost" size="icon" aria-label="Unificar con…" title="Unificar con…"
                      onClick={() => setDialogo({ tipo: 'unificar', ctx, fila })}>
                <Merge className="size-4" />
              </Button>
            )}
          </>
        )}
      />

      {dialogo?.tipo === 'agregar' && <DialogoAgregar ctx={dialogo.ctx} alCerrar={cerrar} />}
      {dialogo?.tipo === 'vincular' && <DialogoVincular ctx={dialogo.ctx} fila={dialogo.fila} alCerrar={cerrar} />}
      {dialogo?.tipo === 'unificar' && <DialogoUnificar ctx={dialogo.ctx} fila={dialogo.fila} alCerrar={cerrar} />}
      {dialogo?.tipo === 'paraje' && (
        <DialogoParaje
          alCerrar={cerrar}
          confirmar={async ({ nombre, provincia, pais }) => {
            const l = await localidadesApi.cargarParaje(nombre, provincia, pais)
            dialogo.ctx.recargar()
            dialogo.ctx.destacar(l.id)
            cerrar()
          }}
        />
      )}
      {dialogo?.tipo === 'marcar' && (
        <DialogoParaje
          alCerrar={cerrar} nombreFijo
          titulo={`Marcar «${dialogo.fila.nombre}» como paraje`} textoConfirmar="Marcar como paraje"
          nombreInicial={dialogo.fila.nombre} provinciaInicial={dialogo.fila.provincia} paisInicial={dialogo.fila.pais}
          confirmar={async ({ provincia, pais }) => {
            await marcarComoParaje(dialogo.fila, dialogo.ctx, provincia, pais)
            cerrar()
          }}
        />
      )}
    </>
  )
}

/** Los resultados del catálogo como opciones del buscador. Las que ya tiene el maestro llevan una marca: elegirlas no
 *  duplica nada (el servidor devuelve la que ya está), pero conviene saberlo antes. */
function gruposDelCatalogo(
  q: string, pais: string, ctx: Ctx, alElegir: (c: { id: string; nombre: string; provincia: string }) => Promise<void>,
): Promise<GrupoBuscado[]> {
  return buscarEnElCatalogo(q, 20, pais).then((resultados) => {
    const yaCargadas = new Set(ctx.filas.map((f) => f.catalogo_id).filter(Boolean))
    if (resultados.length === 0) return []
    return [{
      items: resultados.map((c) => ({
        clave: c.id,
        etiqueta: conProvincia(c.nombre, c.provincia, c.pais),
        marca: yaCargadas.has(c.id) ? 'Ya cargada' : undefined,
        alElegir: () => alElegir(c),
      })),
    }]
  })
}

/** «Agregar del catálogo»: se busca por nombre y se trae la elegida al maestro. */
function DialogoAgregar({ ctx, alCerrar }: { ctx: Ctx; alCerrar: () => void }) {
  const [pais, setPais] = useState(TODOS_LOS_PAISES)
  return (
    <Dialog open onOpenChange={(v) => { if (!v) alCerrar() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Agregar del catálogo</DialogTitle>
          <DialogDescription>
            Las localidades de Argentina (INDEC) y del resto del Mercosur (GeoNames). Se trae una por vez, con su provincia.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <SelectPais id="agregar-pais" valor={pais} alCambiar={setPais} conTodos />
          <div className="grid gap-1">
            <Label htmlFor="agregar-buscar">Buscar localidad</Label>
            <BuscadorAsincrono
              id="agregar-buscar" etiqueta="Buscar localidad" enLinea claveDeBusqueda={pais}
              valorVisible="" placeholder="Escribí el nombre…"
              mensajeVacio="Ninguna localidad del catálogo se llama así."
              buscar={(q) => gruposDelCatalogo(q, pais, ctx, async (c) => {
                const l = await localidadesApi.desdeCatalogo(c.id)
                ctx.recargar()
                ctx.destacar(l.id)
                // Si ya estaba pero de baja, el servidor la devuelve tal cual: se avisa en vez de dejar creer que quedó lista.
                ctx.fallar(l.activo ? null
                  : `«${l.nombre}» ya estaba cargada pero está dada de baja: reactivala desde la lista.`)
                alCerrar()
              })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={alCerrar}>Cerrar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** «Vincular al catálogo»: busca, ya con el nombre de la fila escrito, y vincula la elegida. El 409 del servidor
 *  («… ya está vinculada a «X»: si son la misma, unificalas») se muestra tal cual. */
function DialogoVincular({ ctx, fila, alCerrar }: { ctx: Ctx; fila: Localidad; alCerrar: () => void }) {
  // Se busca en el país de la fila: es lo más probable, y se cambia con el desplegable si la fila estaba mal cargada.
  const [pais, setPais] = useState(fila.pais || TODOS_LOS_PAISES)
  return (
    <Dialog open onOpenChange={(v) => { if (!v) alCerrar() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Vincular «{fila.nombre}» al catálogo</DialogTitle>
          <DialogDescription>
            Elegí la localidad oficial que es. Las órdenes que ya la usan no cambian; el nombre tampoco.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <SelectPais id="vincular-pais" valor={pais} alCambiar={setPais} conTodos />
          <div className="grid gap-1">
            <Label htmlFor="vincular-buscar">Buscar en el catálogo</Label>
            <BuscadorAsincrono
              id="vincular-buscar" etiqueta="Buscar en el catálogo" enLinea claveDeBusqueda={pais}
              valorVisible="" consultaInicial={fila.nombre} placeholder="Escribí el nombre…"
              mensajeVacio="Ninguna localidad del catálogo se llama así."
              buscar={(q) => gruposDelCatalogo(q, pais, ctx, async (c) => {
                await localidadesApi.vincular(fila.id, c.id)
                ctx.recargar()
                ctx.destacar(fila.id)
                alCerrar()
              })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={alCerrar}>Cancelar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** «Unificar con…» (sólo administrador): dos filas que son el mismo lugar («Pto. San Martín» y «Pto San Martín»). Las
 *  órdenes de la primera pasan a la que se elige y la primera se da de baja: por eso se dice con todas las letras antes. */
function DialogoUnificar({ ctx, fila, alCerrar }: { ctx: Ctx; fila: Localidad; alCerrar: () => void }) {
  const [enId, setEnId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)
  const candidatas = ctx.filas.filter((l) => l.activo && l.id !== fila.id)
  const destino = candidatas.find((l) => String(l.id) === enId)

  async function unificar() {
    if (!destino) return
    setError(null)
    setGuardando(true)
    try {
      const queda = await localidadesApi.unificar(fila.id, destino.id)
      ctx.recargar()
      ctx.destacar(queda.id)
      alCerrar()
    } catch (e) {
      setError(mensajeDeError(e))
      setGuardando(false)
    }
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v) alCerrar() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Unificar «{fila.nombre}» con…</DialogTitle>
          <DialogDescription>
            Para dos localidades que son el mismo lugar. Elegí la que queda.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1">
            <Label htmlFor="unificar-en">La localidad que queda</Label>
            <SelectBuscable
              id="unificar-en" ariaLabel="La localidad que queda" buscarEscribiendo
              value={enId} onChange={setEnId}
              opciones={candidatas.map((l) => ({ value: String(l.id), label: conProvincia(l.nombre, l.provincia, l.pais) }))}
              placeholder="Buscar localidad…" emptyMessage="No hay otra con ese nombre."
              className="w-full min-w-0"
            />
          </div>
          {destino && (
            <p role="note" className="rounded border p-3 text-sm">
              Las órdenes de «{fila.nombre}» pasan a «{destino.nombre}» y «{fila.nombre}» se da de baja.
            </p>
          )}
          {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={alCerrar}>Cancelar</Button>
          <Button type="button" disabled={!destino || guardando} onClick={() => void unificar()}>
            Unificar
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
