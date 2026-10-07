/** «Traer de ARCA»: pide una o varias cartas de porte por su CTG y las guarda.
 *
 *  🔑 **«Consultar como» es obligatorio y no tiene valor por defecto**, ni siquiera cuando hay un solo CUIT. ARCA
 *  contesta según por quién se pregunta, y una CPE consultada con el CUIT equivocado no es un error visible: es una
 *  carta que no aparece, o una que se guarda a nombre de otro. Por eso la persona tiene que elegirlo cada vez.
 *
 *  🔑 **La vista previa no guarda nada.** «Ver antes de guardar» sólo existe con un único CTG; con varios se guarda
 *  directo y el resultado dice, CTG por CTG, qué quedó y qué no.
 */
import { useEffect, useMemo, useState } from 'react'

import type { CartaPorte, Representados, ResultadoDeTraer } from '@/api/cartas-porte'
import { cartasPorte, leerCtgs, MAX_CTGS, nombreOCuit } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { FichaDeCartaDePorte } from '@/components/FichaDeCartaDePorte'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'

function Formulario({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: () => void }) {
  const [representados, setRepresentados] = useState<Representados | null>(null)
  const [errorDeAcceso, setErrorDeAcceso] = useState<string | null>(null)
  const [intento, setIntento] = useState(0)
  const [cuit, setCuit] = useState('')
  const [texto, setTexto] = useState('')
  const [vista, setVista] = useState<CartaPorte | null>(null)
  const [resultados, setResultados] = useState<ResultadoDeTraer[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState<'consultando' | 'guardando' | null>(null)

  // Al abrir (y al reintentar): quién deja consultar el certificado. El 409 («cargalo en Configuración / ARCA») y
  // el 502 («ARCA no da acceso») traen su explicación en el `detail`, y sin esta lista no hay nada más que hacer.
  useEffect(() => {
    let vigente = true
    setRepresentados(null)
    setErrorDeAcceso(null)
    cartasPorte.representados()
      .then((r) => { if (vigente) setRepresentados(r) })
      .catch((e) => { if (vigente) setErrorDeAcceso(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [intento])

  const ctgs = useMemo(() => leerCtgs(texto), [texto])
  const hayTexto = texto.trim() !== ''
  const listos = ctgs.validos.length > 0 && ctgs.invalidos.length === 0 && !ctgs.excede
  const puedeGuardar = Boolean(cuit) && listos && ocupado === null && resultados === null
  const puedeVer = Boolean(cuit) && listos && ctgs.validos.length === 1 && ocupado === null

  /** Lo que se vio o se guardó es de una consulta concreta: si cambia el CUIT o los CTG, ya no vale. */
  function cambiarCuit(valor: string) {
    setCuit(valor); setVista(null); setResultados(null); setError(null)
  }
  function cambiarTexto(valor: string) {
    setTexto(valor); setVista(null); setResultados(null); setError(null)
  }

  async function verAntes() {
    setError(null); setVista(null); setOcupado('consultando')
    try {
      setVista(await cartasPorte.consultar(ctgs.validos[0], cuit))
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setOcupado(null)
    }
  }

  async function guardar() {
    setError(null); setOcupado('guardando')
    try {
      setResultados(await cartasPorte.traer(ctgs.validos, cuit))
      // Aunque alguna haya fallado, las otras quedaron guardadas: el listado se refresca igual.
      alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setOcupado(null)
    }
  }

  if (errorDeAcceso) {
    return (
      <>
        <p role="alert" className="border-destructive/40 rounded border p-3 text-sm">{errorDeAcceso}</p>
        <DialogFooter>
          <Button variant="ghost" onClick={alCerrar}>Cerrar</Button>
          <Button variant="outline" onClick={() => setIntento(intento + 1)}>Reintentar</Button>
        </DialogFooter>
      </>
    )
  }

  const homologacion = representados?.ambiente === 'homologacion'
  const guardadas = resultados?.filter((r) => r.id !== null).length ?? 0

  return (
    <>
      <div className="grid gap-3">
        {representados === null ? (
          <p className="text-muted-foreground text-sm">Consultando a ARCA por quién se puede preguntar…</p>
        ) : (
          <div className="grid gap-1">
            <Elegir
              id="cpe-cuit" etiqueta="Consultar como" vacio="Elegir…" valor={cuit}
              opciones={representados.cuits.map((c) => ({ id: c.cuit, etiqueta: nombreOCuit(c) }))}
              alCambiar={cambiarCuit}
            />
            {representados.cuits.length === 0 && (
              <p role="alert" className="text-destructive text-xs">
                El certificado no tiene ninguna delegación: ARCA no informa por quién consultar.
              </p>
            )}
            {homologacion ? (
              <p className="text-xs font-medium text-amber-800 dark:text-amber-400">
                Homologación: no tiene CPE reales
              </p>
            ) : (
              <p className="text-muted-foreground text-xs">Ambiente: producción</p>
            )}
          </div>
        )}

        <div className="grid gap-1">
          <Label htmlFor="cpe-ctg">CTG</Label>
          <textarea
            id="cpe-ctg" rows={4} value={texto} onChange={(e) => cambiarTexto(e.target.value)}
            placeholder="Uno o varios, separados por espacio, coma o renglón"
            disabled={representados === null}
            className="border-input bg-background w-full rounded-md border px-3 py-2 font-mono text-sm"
          />
          {/* Qué entendió el campo: lo que se va a pedir, lo que se descartó y por qué. */}
          {hayTexto && (
            <p className="text-muted-foreground text-xs" aria-live="polite">
              {ctgs.validos.length === 1 ? '1 CTG' : `${ctgs.validos.length} CTG`}
              {ctgs.repetidos > 0 && ` (se quitó ${ctgs.repetidos === 1 ? '1 repetido' : `${ctgs.repetidos} repetidos`})`}
            </p>
          )}
          {ctgs.invalidos.length > 0 && (
            <p role="alert" className="text-destructive text-xs">
              Un CTG tiene 11 dígitos. No sirve: {ctgs.invalidos.join(', ')}
            </p>
          )}
          {ctgs.excede && (
            <p role="alert" className="text-destructive text-xs">
              Son demasiados: se pueden traer hasta {MAX_CTGS} CTG por vez.
            </p>
          )}
        </div>

        {error && <p role="alert" className="border-destructive/40 rounded border p-3 text-sm">{error}</p>}

        {vista && (
          <section aria-label="Vista previa" className="grid gap-3 rounded border p-4">
            {vista.guardada_id != null && (
              <p role="status" className="text-sm font-medium">Ya está guardada: se va a actualizar</p>
            )}
            <FichaDeCartaDePorte carta={vista} />
          </section>
        )}

        {resultados && (
          <section aria-label="Resultado" className="grid gap-2 rounded border p-4 text-sm">
            <p role="status" className="font-medium">
              {guardadas === 1 ? 'Se guardó 1 carta de porte' : `Se guardaron ${guardadas} cartas de porte`}
              {resultados.length - guardadas > 0 && `; ${resultados.length - guardadas} con error`}.
            </p>
            <ul className="grid gap-1">
              {resultados.map((r) => (
                <li key={r.ctg}>
                  <span className="font-mono">{r.ctg}</span>
                  {r.error
                    ? <span className="text-destructive"> — {r.error}</span>
                    : <span className="text-muted-foreground"> — guardada</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={alCerrar}>{resultados ? 'Cerrar' : 'Cancelar'}</Button>
        {ctgs.validos.length === 1 && ctgs.invalidos.length === 0 && (
          <Button variant="outline" onClick={verAntes} disabled={!puedeVer}>
            {ocupado === 'consultando' ? 'Consultando…' : 'Ver antes de guardar'}
          </Button>
        )}
        <Button onClick={guardar} disabled={!puedeGuardar}>
          {ocupado === 'guardando' ? 'Guardando…' : 'Guardar'}
        </Button>
      </DialogFooter>
    </>
  )
}

export function TraerCartasDePorte({ abierto, alCambiar, alGuardar }: {
  abierto: boolean
  alCambiar: (abierto: boolean) => void
  /** Se llama cuando quedó guardada al menos una carta, para que el listado se refresque. */
  alGuardar: () => void
}) {
  return (
    <Dialog open={abierto} onOpenChange={alCambiar}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Traer de ARCA</DialogTitle>
        </DialogHeader>
        {/* El contenido de un diálogo cerrado no se monta: cada apertura arranca limpia, con el CUIT sin elegir. */}
        <Formulario alCerrar={() => alCambiar(false)} alGuardar={alGuardar} />
      </DialogContent>
    </Dialog>
  )
}
