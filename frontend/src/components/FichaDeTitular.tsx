/** La ficha de un titular de Carta de Porte: sus datos, su delegación en ARCA y su plantilla (ADR-044).
 *
 *  Sirve para el alta (sin `titular`, con los datos de partida si vienen de «Delegado sin cargar») y para ver y editar uno
 *  cargado. Sólo un administrador escribe; un operador mira.
 *
 *  🔑 **El estado de la delegación se muestra y no se edita**: lo informa ARCA (ver `servicios/titulares_cpe.py`). Lo que
 *  se carga es lo que ARCA no sabe: a quién corresponde, quién emite (nosotros por su delegación, o él) y sus notas.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BadgeEstado } from 'libra-ui/badge-estado'

import type { QuienEmite, Titular } from '@/api/cartas-porte'
import {
  cartasPorte, enmascararCuit, etiquetaDeDelegacion, formatearCuit, tonoDeDelegacion,
} from '@/api/cartas-porte'
import { listarPorRol } from '@/api/maestros'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { InstruccionesDeDelegacion } from '@/components/InstruccionesDeDelegacion'
import { PlantillaDeTitular } from '@/components/PlantillaDeTitular'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { irA } from '@/navegacion'

/** Con qué arranca el alta de un titular que ARCA trae y no está cargado. */
export type PartidaDelAlta = { cuit: string; razon_social: string; tercero_id: number | null }

/** Qué dice cada estado de delegación, para que quien mira sepa qué hacer. */
function explicacion(t: Titular, motivo: string | null): string {
  if (t.emite === 'titular') {
    if (t.delegacion === 'delegado') {
      return 'Emite él con su propio acceso. ARCA informa que nos delegó el servicio: podemos consultar sus cartas por CTG.'
    }
    if (t.delegacion === 'pendiente') {
      return 'Emite él con su propio acceso, pero para consultar sus cartas por CTG tiene que delegarnos el servicio. '
        + 'ARCA todavía no lo informa: lo suma con el próximo ticket, que puede tardar hasta 12 horas desde que lo hace.'
    }
    return `Emite él con su propio acceso. No se pudo verificar en ARCA si nos delegó la consulta${motivo ? `: ${motivo}` : '.'}`
  }
  if (t.delegacion === 'delegado') return 'ARCA informa que este CUIT le delegó la emisión a nuestro certificado.'
  if (t.delegacion === 'pendiente') {
    return 'Está cargado, pero ARCA todavía no informa su delegación. ARCA la suma con el próximo ticket, que puede '
      + 'tardar hasta 12 horas desde que el titular la hace.'
  }
  return `No se pudo verificar en ARCA${motivo ? `: ${motivo}` : '.'}`
}

function Formulario({ titular, partida, esAdmin, cuitParaCatalogos, motivo, alCerrar, alCambiar }: {
  titular: Titular | null
  partida: PartidaDelAlta | null
  esAdmin: boolean
  cuitParaCatalogos: string | null
  motivo: string | null
  alCerrar: () => void
  alCambiar: () => void
}) {
  const [cuit, setCuit] = useState(enmascararCuit(titular?.cuit ?? partida?.cuit ?? ''))
  const [razonSocial, setRazonSocial] = useState(titular?.razon_social ?? partida?.razon_social ?? '')
  const [emite, setEmite] = useState<QuienEmite>(titular?.emite ?? 'nosotros')
  const [activo, setActivo] = useState(titular?.activo ?? true)
  const [notas, setNotas] = useState(titular?.notas ?? '')
  const [terceroId, setTerceroId] = useState(String(titular?.tercero?.id ?? partida?.tercero_id ?? ''))
  const [clientes, setClientes] = useState<{ id: number; etiqueta: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [confirmandoBorrar, setConfirmandoBorrar] = useState(false)

  // Para vincular a mano con una entidad. Es un extra: si el pedido falla, la ficha sigue (se vincula por CUIT).
  useEffect(() => {
    let vigente = true
    listarPorRol('cliente')
      .then((filas) => {
        if (!vigente || !Array.isArray(filas)) return
        setClientes(filas.flatMap((f) => (typeof f.razon_social === 'string'
          ? [{ id: f.id, etiqueta: f.razon_social }] : [])))
      })
      .catch(() => {})
    return () => { vigente = false }
  }, [])

  const cuitDigitos = cuit.replace(/\D/g, '')
  const puedeEscribir = esAdmin && !enviando
  // Al cargar, la razón social puede quedar vacía si el CUIT es de una entidad cargada (el servidor la toma de ella).
  const valido = titular ? razonSocial.trim() !== '' : cuitDigitos.length === 11

  async function guardar() {
    if (!puedeEscribir || !valido) return
    setError(null); setEnviando(true)
    try {
      const comunes = {
        emite, activo, notas: notas.trim() || null, tercero_id: terceroId ? Number(terceroId) : null,
      }
      if (titular) await cartasPorte.editarTitular(titular.id, { ...comunes, razon_social: razonSocial.trim() })
      else await cartasPorte.crearTitular({ ...comunes, cuit: cuitDigitos, razon_social: razonSocial.trim() || null })
      alCambiar()
      alCerrar()
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setEnviando(false)
    }
  }

  async function borrar() {
    if (!titular) return
    setConfirmandoBorrar(false); setError(null); setEnviando(true)
    try {
      await cartasPorte.borrarTitular(titular.id)
      alCambiar()
      alCerrar()
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
      <DialogHeader>
        <DialogTitle>{titular ? titular.razon_social : 'Nuevo titular'}</DialogTitle>
        <DialogDescription>
          {titular
            ? `CUIT ${formatearCuit(titular.cuit)}`
            : 'Un cliente a cuyo nombre emitimos cartas de porte, o que las emite él.'}
        </DialogDescription>
      </DialogHeader>

      {titular && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <BadgeEstado tono={tonoDeDelegacion(titular.delegacion)}>
            {etiquetaDeDelegacion(titular.delegacion, titular.emite)}
          </BadgeEstado>
          <span className="text-muted-foreground">{explicacion(titular, motivo)}</span>
        </div>
      )}

      <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void guardar() }}>
        <div className="grid gap-1">
          <Label htmlFor="titular-cuit">CUIT</Label>
          <Input id="titular-cuit" value={cuit} inputMode="numeric" placeholder="00-00000000-0"
                 disabled={titular !== null || partida !== null || !puedeEscribir}
                 onChange={(e) => setCuit(enmascararCuit(e.target.value))} />
          {titular && <p className="text-muted-foreground text-xs">El CUIT no se cambia: dalo de baja y cargá el otro.</p>}
        </div>
        <div className="grid gap-1">
          <Label htmlFor="titular-razon">Razón social</Label>
          <Input id="titular-razon" value={razonSocial} maxLength={120} disabled={!puedeEscribir}
                 onChange={(e) => setRazonSocial(e.target.value)} />
        </div>

        <fieldset className="grid gap-1 sm:col-span-2" disabled={!puedeEscribir}>
          <legend className="mb-1 text-sm font-medium">Quién emite la carta de porte</legend>
          <div className="flex items-start gap-2">
            <input id="titular-emite-nosotros" type="radio" name="titular-emite" checked={emite === 'nosotros'}
                   onChange={() => setEmite('nosotros')} className="mt-1" />
            <Label htmlFor="titular-emite-nosotros" className="grid gap-0.5 font-normal">
              <span className="font-medium">Nosotros</span>
              <span className="text-muted-foreground text-xs">
                El titular nos delegó <code>wscpe</code> en ARCA y emitimos desde la orden.
              </span>
            </Label>
          </div>
          <div className="flex items-start gap-2">
            <input id="titular-emite-titular" type="radio" name="titular-emite" checked={emite === 'titular'}
                   onChange={() => setEmite('titular')} className="mt-1" />
            <Label htmlFor="titular-emite-titular" className="grid gap-0.5 font-normal">
              <span className="font-medium">El titular</span>
              <span className="text-muted-foreground text-xs">
                Emite él; nosotros no emitimos, sólo consultamos sus cartas por CTG (para eso también tiene que delegarnos).
              </span>
            </Label>
          </div>
        </fieldset>

        <div className="sm:col-span-2">
          <Elegir id="titular-entidad" etiqueta="Cliente de Entidades" vacio="El que tenga este CUIT"
                  valor={terceroId} opciones={clientes} alCambiar={setTerceroId}
                  deshabilitado={!puedeEscribir} />
          {titular?.tercero && (
            <p className="text-muted-foreground mt-1 text-xs">
              Vinculado a{' '}
              <Link className="underline underline-offset-2" to={irA.entidades('clientes', titular.tercero.id)}>
                {titular.tercero.razon_social}
              </Link>.
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 sm:col-span-2">
          <input id="titular-activo" type="checkbox" checked={activo} disabled={!puedeEscribir}
                 onChange={(e) => setActivo(e.target.checked)} />
          <Label htmlFor="titular-activo">Activo</Label>
        </div>

        <div className="grid gap-1 sm:col-span-2">
          <Label htmlFor="titular-notas">Notas</Label>
          <textarea id="titular-notas" rows={2} value={notas} maxLength={2000} disabled={!puedeEscribir}
                    onChange={(e) => setNotas(e.target.value)}
                    className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm" />
        </div>

        {error && (
          <p role="alert" className="rounded border border-destructive/40 p-3 text-sm sm:col-span-2">{error}</p>
        )}
        <DialogFooter className="sm:col-span-2">
          {esAdmin && titular && (
            <Button type="button" variant="outline" className="text-destructive sm:mr-auto" disabled={enviando}
                    onClick={() => setConfirmandoBorrar(true)}>
              Sacar de la lista
            </Button>
          )}
          <Button type="button" variant="ghost" onClick={alCerrar}>{esAdmin ? 'Cancelar' : 'Cerrar'}</Button>
          {esAdmin && (
            <Button type="submit" disabled={enviando || !valido}>
              {enviando ? 'Guardando…' : titular ? 'Guardar' : 'Agregar titular'}
            </Button>
          )}
        </DialogFooter>
      </form>

      {titular && titular.delegacion === 'pendiente' && (
        <InstruccionesDeDelegacion titular={titular.razon_social} soloConsulta={titular.emite === 'titular'} />
      )}

      {titular && titular.emite === 'nosotros' && (
        <PlantillaDeTitular titular={titular} cuitParaCatalogos={cuitParaCatalogos} puedeEditar={esAdmin}
                            alCambiar={alCambiar} />
      )}
      {titular && titular.emite === 'titular' && (
        <p className="text-muted-foreground text-sm">
          No emitimos a su nombre, así que no lleva datos habituales para emitir.
        </p>
      )}

      <ConfirmDialog open={confirmandoBorrar} onOpenChange={setConfirmandoBorrar}
                     title="Sacar al titular de la lista"
                     description="Deja de aparecer acá. No se borra ninguna carta de porte ni toca la delegación en ARCA; su plantilla se conserva por si se vuelve a cargar."
                     confirmLabel="Sacar" onConfirm={borrar} />
    </DialogContent>
  )
}

export function FichaDeTitular({ abierto, alCambiarAbierto, ...resto }: {
  abierto: boolean
  alCambiarAbierto: (abierto: boolean) => void
  titular: Titular | null
  partida: PartidaDelAlta | null
  esAdmin: boolean
  cuitParaCatalogos: string | null
  motivo: string | null
  alCambiar: () => void
}) {
  return (
    <Dialog open={abierto} onOpenChange={alCambiarAbierto}>
      {/* Un diálogo cerrado no monta su contenido: cada apertura arranca con el formulario limpio. */}
      {abierto && <Formulario {...resto} alCerrar={() => alCambiarAbierto(false)} />}
    </Dialog>
  )
}
