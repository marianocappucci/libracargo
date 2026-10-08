/** Un campo para buscar escribiendo, con los resultados pedidos al servidor, agrupados.
 *
 * 🔑 **Por qué no es el `SelectBuscable` de `libra-ui`.** Ese filtra en memoria una lista que ya tiene: no avisa qué se
 * escribió ni deja pedir las opciones al servidor. Acá la lista completa son 4.027 localidades del catálogo más las del
 * maestro, y no se baja entera para elegir una: se escribe, se espera un instante y se pide lo que coincide. Además cada
 * resultado puede traer su propia consecuencia (traer una localidad del catálogo al maestro, abrir un diálogo para cargar un
 * paraje), cosa que una lista de `{value, label}` no expresa.
 *
 * Es un *combobox* con lista: el campo recibe el foco y las flechas recorren los resultados, Enter elige, Escape cierra.
 * Cerrada, Enter no es suyo: sigue su camino (enviar el formulario que lo contiene).
 */
import { Loader2, Search, X } from 'lucide-react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { useEffect, useId, useRef, useState } from 'react'

import { mensajeDeError } from '@/components/AbmMaestro'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

export type ItemBuscado = {
  clave: string
  /** Lo que se lee: el nombre y, si hace falta, la provincia («Suipacha — Buenos Aires»). */
  etiqueta: string
  /** Una marca discreta a la derecha («Paraje»). */
  marca?: string
  /** Se ve, pero no se puede elegir (una localidad dada de baja). */
  deshabilitado?: boolean
  /** Lo que pasa al elegirlo. Si falla, el mensaje del servidor se muestra bajo el campo tal cual. */
  alElegir: () => void | Promise<void>
}

export type GrupoBuscado = { titulo?: string; items: ItemBuscado[] }

type Props = {
  id: string
  /** El nombre accesible del campo. */
  etiqueta: string
  /** Lo que el campo muestra mientras no se está buscando (lo elegido). */
  valorVisible: string
  buscar: (q: string) => Promise<GrupoBuscado[]>
  /** Una opción fija al final de la lista, para lo escrito («Cargar «X» como paraje…»). */
  alFinal?: (q: string) => ItemBuscado
  /** Si está, hay una × para vaciar lo elegido. */
  alQuitar?: () => void
  placeholder?: string
  /** Si está, el campo arranca con esto escrito y la lista abierta (buscar de entrada lo más probable). */
  consultaInicial?: string
  /** La lista se dibuja a continuación del campo, empujando lo de abajo, en vez de flotar encima: en un diálogo con
   *  scroll una lista flotante queda recortada. */
  enLinea?: boolean
  /** Letras mínimas para buscar. */
  minimo?: number
  /** Espera tras la última tecla antes de pedir. */
  esperaMs?: number
  mensajeVacio?: string
  deshabilitado?: boolean
  invalido?: boolean
  className?: string
  /** Texto bajo el campo (el error de validación del formulario). */
  children?: ReactNode
}

export function BuscadorAsincrono({
  id, etiqueta, valorVisible, buscar, alFinal, alQuitar,
  placeholder = 'Buscar…', consultaInicial, enLinea = false, minimo = 2, esperaMs = 250,
  mensajeVacio = 'No hay coincidencias.', deshabilitado, invalido, className, children,
}: Props) {
  // `null` = no se está buscando: el campo muestra lo elegido. Cerrar la lista por cualquier camino lo deja así.
  const [consulta, setConsulta] = useState<string | null>(consultaInicial ?? null)
  const [abierto, setAbierto] = useState(Boolean(consultaInicial))
  const [grupos, setGrupos] = useState<GrupoBuscado[]>([])
  const [buscando, setBuscando] = useState(false)
  const [errorDeBusqueda, setErrorDeBusqueda] = useState<string | null>(null)
  const [errorAlElegir, setErrorAlElegir] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [resaltada, setResaltada] = useState(0)
  const campo = useRef<HTMLInputElement>(null)
  const lista = useRef<HTMLDivElement>(null)
  const recienEnfocado = useRef(false)
  const idInterno = useId()
  const idLista = `${idInterno}-lista`
  const idOpcion = (i: number) => `${idInterno}-opcion-${i}`

  // `buscar` es una función nueva en cada render del padre: va por ref para no repetir el pedido por eso.
  const buscarRef = useRef(buscar)
  buscarRef.current = buscar

  const q = (consulta ?? '').trim()
  const suficiente = q.length >= minimo

  // El pedido, con espera tras la última tecla. `vigente` descarta la respuesta de una consulta que ya cambió: sin
  // eso, una respuesta lenta de «sui» pisaría la de «suipacha».
  useEffect(() => {
    if (consulta === null || !suficiente) {
      setGrupos([])
      setBuscando(false)
      setErrorDeBusqueda(null)
      return
    }
    let vigente = true
    setBuscando(true)
    const t = setTimeout(() => {
      buscarRef.current(q)
        .then((g) => { if (vigente) { setGrupos(g); setErrorDeBusqueda(null) } })
        .catch((e) => { if (vigente) { setGrupos([]); setErrorDeBusqueda(mensajeDeError(e)) } })
        .finally(() => { if (vigente) setBuscando(false) })
    }, esperaMs)
    return () => { vigente = false; clearTimeout(t) }
  }, [consulta, q, suficiente, esperaMs])

  const pie = alFinal && suficiente ? alFinal(q) : null
  const items = [...grupos.flatMap((g) => g.items), ...(pie ? [pie] : [])]
  const indiceDe = new Map(items.map((it, i) => [it.clave, i]))

  useEffect(() => {
    if (!abierto) return
    lista.current?.querySelector('[data-resaltada="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [resaltada, abierto])

  // Elegir deja el campo con lo elegido seleccionado: la próxima letra empieza una búsqueda nueva.
  useEffect(() => {
    if (document.activeElement === campo.current) campo.current?.select()
  }, [valorVisible])

  function cerrar() {
    setAbierto(false)
    setConsulta(null)
  }

  async function elegir(item: ItemBuscado | undefined) {
    if (!item || item.deshabilitado || ocupado) return
    setErrorAlElegir(null)
    setOcupado(true)
    try {
      await item.alElegir()
      cerrar()
    } catch (e) {
      setErrorAlElegir(mensajeDeError(e))
    } finally {
      setOcupado(false)
    }
  }

  function alEscribir(valor: string) {
    setConsulta(valor)
    setResaltada(0)
    setErrorAlElegir(null)
    setAbierto(true)
  }

  function alTeclear(e: ReactKeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (abierto) setResaltada((i) => Math.min(i + 1, Math.max(items.length - 1, 0)))
      else { setConsulta(''); setAbierto(true) }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (abierto) setResaltada((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      if (!abierto) return
      e.preventDefault()
      void elegir(items[resaltada])
    } else if (e.key === 'Escape') {
      if (!abierto) return
      e.preventDefault()
      e.stopPropagation()  // que no cierre también el diálogo que contiene al campo
      cerrar()
    } else if (e.key === 'Tab') {
      cerrar()
    }
  }

  const activa = abierto ? items[resaltada] : undefined
  const sinResultados = suficiente && !buscando && !errorDeBusqueda && grupos.every((g) => g.items.length === 0)

  function opcion(item: ItemBuscado) {
    const i = indiceDe.get(item.clave) ?? 0
    return (
      <div
        key={item.clave} id={idOpcion(i)} role="option"
        aria-selected={i === resaltada} aria-disabled={item.deshabilitado || undefined}
        data-resaltada={i === resaltada}
        onClick={() => void elegir(item)}
        onMouseEnter={() => setResaltada(i)}
        className={cn(
          'flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm',
          i === resaltada && 'bg-accent text-accent-foreground',
          item.deshabilitado && 'cursor-not-allowed opacity-60',
        )}
      >
        <span className="truncate">{item.etiqueta}</span>
        {item.marca && (
          <span className="text-muted-foreground ml-auto shrink-0 text-xs">{item.marca}</span>
        )}
      </div>
    )
  }

  return (
    <div className="grid gap-1">
      <div
        className={cn('relative', className)}
        // Cierra cuando el foco sale del control entero (campo, × y lista): cubre el click afuera y el Tab.
        onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) cerrar() }}
      >
        <div className="relative">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
          <Input
            id={id} ref={campo} type="text" role="combobox" autoComplete="off"
            value={consulta ?? valorVisible}
            onChange={(e) => alEscribir(e.target.value)}
            onKeyDown={alTeclear}
            onFocus={(e) => { recienEnfocado.current = true; e.currentTarget.select() }}
            onMouseUp={(e) => { if (recienEnfocado.current) e.preventDefault(); recienEnfocado.current = false }}
            onClick={() => { if (!abierto) { setConsulta(consulta ?? ''); setAbierto(true) } }}
            placeholder={placeholder}
            disabled={deshabilitado}
            // `readOnly` y no `disabled` mientras trae la localidad: deshabilitar le saca el foco al campo y no vuelve.
            readOnly={ocupado}
            aria-expanded={abierto}
            aria-haspopup="listbox"
            aria-controls={abierto ? idLista : undefined}
            aria-activedescendant={activa ? idOpcion(resaltada) : undefined}
            aria-autocomplete="list"
            aria-label={etiqueta}
            aria-invalid={invalido || undefined}
            aria-busy={buscando || ocupado || undefined}
            className={cn('w-full pl-9', (alQuitar && valorVisible !== '' || ocupado) && 'pr-9')}
          />
          {ocupado && (
            <Loader2 className="text-muted-foreground absolute top-1/2 right-2.5 size-4 -translate-y-1/2 animate-spin" />
          )}
          {!ocupado && alQuitar && valorVisible !== '' && !deshabilitado && (
            <Button
              type="button" variant="ghost" size="icon" aria-label="Quitar la selección"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { alQuitar(); cerrar(); campo.current?.focus() }}
              className="text-muted-foreground absolute top-1/2 right-1 size-7 -translate-y-1/2"
            >
              <X className="size-4" />
            </Button>
          )}
        </div>

        {abierto && (
          <div
            // Sin esto, tocar la lista le saca el foco al campo y el `onBlur` de arriba la cierra antes del click.
            onMouseDown={(e) => e.preventDefault()}
            className={cn(
              'bg-popover text-popover-foreground mt-1 w-full min-w-56 rounded-md border p-1',
              !enLinea && 'absolute z-50 shadow-md',
            )}
          >
            <div ref={lista} id={idLista} role="listbox" aria-label={`Opciones de ${etiqueta}`} className="max-h-72 overflow-y-auto">
              {!suficiente && (
                <p className="text-muted-foreground px-2 py-3 text-center text-sm">
                  Escribí al menos {minimo} letras para buscar.
                </p>
              )}
              {suficiente && buscando && (
                <p role="status" className="text-muted-foreground px-2 py-2 text-sm">Buscando…</p>
              )}
              {errorDeBusqueda && (
                <p role="alert" className="text-destructive px-2 py-2 text-sm">{errorDeBusqueda}</p>
              )}
              {sinResultados && (
                <p className="text-muted-foreground px-2 py-2 text-sm">{mensajeVacio}</p>
              )}
              {grupos.map((g, n) => {
                if (g.items.length === 0) return null
                const idTitulo = `${idInterno}-grupo-${n}`
                return (
                  <div key={g.titulo ?? `grupo-${n}`} role="group" aria-labelledby={g.titulo ? idTitulo : undefined}>
                    {g.titulo && (
                      <div
                        id={idTitulo} role="presentation"
                        className="text-muted-foreground mt-1 border-t px-2 pt-2 pb-1 text-xs font-medium first:mt-0 first:border-t-0"
                      >
                        {g.titulo}
                      </div>
                    )}
                    {g.items.map(opcion)}
                  </div>
                )
              })}
              {pie && (
                <div role="group" className="mt-1 border-t pt-1">
                  {opcion(pie)}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
      {errorAlElegir && (
        <p role="alert" className="text-destructive text-xs">{errorAlElegir}</p>
      )}
      {children}
    </div>
  )
}
