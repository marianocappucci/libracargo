/** Configuración → «Tarifario de referencia» (ADR-038): las ediciones del tarifario sectorial con el que Suitrans cotiza.
 *
 *  Cada edición es una tabla de pesos por tonelada para cada kilómetro, con su vigencia (la del 10 de abril de 2026, por
 *  ejemplo) y, a veces, un «valor de estadía». La orden de carga la consulta para proponer la tarifa por tonelada
 *  (`SeccionFlete`); acá se ve qué ediciones hay y, quien administra, se carga una nueva.
 *
 *  🔑 **Ver es de todo el staff; cargar es sólo del administrador.** El servidor ya contesta 403 a quien no lo es, así
 *  que a los demás ni se les ofrece el formulario.
 *
 *  🔑 **Una vigencia que ya existe se reemplaza entera**, no se mezcla fila por fila: por eso el formulario avisa antes
 *  de mandar, y el 422 de un CSV mal armado (que nombra la línea) se muestra tal cual lo dice el servidor.
 */
import { DataTable } from 'libra-ui/data-table'
import { Eye, Upload } from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

import type { FilaDeTarifa, Tarifario } from '@/api/tarifario'
import { tarifario } from '@/api/tarifario'
import { formatearKilos } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { formatearFecha, formatearImporte, hoyEnArgentina } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/context/AuthContext'

type Celda = { row: { original: Tarifario } }

/** `1–1.050`, o `—` si la edición no tiene filas. */
const rangoDeKm = (t: Tarifario) =>
  t.km_desde == null || t.km_hasta == null ? '—' : `${formatearKilos(t.km_desde)}–${formatearKilos(t.km_hasta)}`

/** La tabla de una edición, con un buscador por km: «80» trae el 80, el 800... — los km que empiezan con eso. */
function TablaDeEdicion({ edicion }: { edicion: Tarifario }) {
  const [filas, setFilas] = useState<FilaDeTarifa[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busqueda, setBusqueda] = useState('')

  useEffect(() => {
    let vigente = true
    setFilas(null)
    setError(null)
    tarifario.filas(edicion.id)
      .then((f) => { if (vigente) setFilas(f) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [edicion.id])

  const q = busqueda.trim()
  const visibles = (filas ?? []).filter((f) => String(f.km).startsWith(q))

  return (
    <section aria-label={`Tabla del ${formatearFecha(edicion.vigencia)}`} className="mt-6 grid max-w-md gap-3">
      <h3 className="text-sm font-semibold">
        {edicion.nombre} · vigencia {formatearFecha(edicion.vigencia)}
      </h3>
      <div className="grid gap-1">
        <Label htmlFor="tarifario-buscar-km">Buscar por km</Label>
        <Input id="tarifario-buscar-km" inputMode="numeric" value={busqueda} placeholder="Por ejemplo, 80"
               onChange={(e) => setBusqueda(e.target.value)} />
      </div>
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      {filas === null && !error && <p className="text-muted-foreground text-sm">Cargando…</p>}
      {filas !== null && (
        <div className="max-h-96 overflow-y-auto rounded border">
          <table className="w-full text-sm tabular-nums">
            <thead className="bg-muted sticky top-0">
              <tr>
                <th scope="col" className="px-3 py-2 text-right font-medium">Km</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Tarifa por tonelada</th>
              </tr>
            </thead>
            <tbody>
              {visibles.map((f) => (
                <tr key={f.km} className="border-t">
                  <td className="px-3 py-1 text-right">{f.km}</td>
                  <td className="px-3 py-1 text-right">{formatearImporte(f.tarifa)}</td>
                </tr>
              ))}
              {visibles.length === 0 && (
                <tr>
                  <td colSpan={2} className="text-muted-foreground px-3 py-4 text-center">
                    {q ? `Ningún km empieza con ${q}.` : 'Esta edición no tiene filas.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** El formulario de carga: un CSV `km;tarifa`, su vigencia y su nombre. Sólo se monta para el administrador. */
function CargarEdicion({ ediciones, alCargar }: { ediciones: Tarifario[]; alCargar: (t: Tarifario) => void }) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [vigencia, setVigencia] = useState(hoyEnArgentina())
  const [nombre, setNombre] = useState('')
  const [estadia, setEstadia] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const entrada = useRef<HTMLInputElement>(null)

  const reemplaza = vigencia !== '' && ediciones.some((t) => t.vigencia === vigencia)
  const completo = archivo !== null && vigencia !== '' && nombre.trim() !== ''

  async function cargar(e: FormEvent) {
    e.preventDefault()
    if (!archivo) return
    setError(null)
    setAviso(null)
    setEnviando(true)
    try {
      const t = await tarifario.cargar({ archivo, vigencia, nombre: nombre.trim(), valorEstadia: estadia })
      setAviso(`Se cargó «${t.nombre}», vigencia ${formatearFecha(t.vigencia)}: ${formatearKilos(t.filas)} filas (km ${rangoDeKm(t)}).`)
      setArchivo(null)
      setNombre('')
      setEstadia('')
      if (entrada.current) entrada.current.value = ''
      alCargar(t)
    } catch (err) {
      // El 422 nombra la línea del CSV que falla («línea 4: …»): se muestra como viene, sin reescribirlo.
      setError(mensajeDeError(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={cargar} aria-label="Cargar una edición" className="mt-8 grid max-w-xl gap-3 border-t pt-6">
      <h3 className="text-sm font-semibold">Cargar una edición</h3>
      <p className="text-muted-foreground text-xs">
        CSV con dos columnas: km y tarifa por tonelada (por ejemplo <code>80;23.205,57</code>). Si ya hay una edición con
        esa vigencia, se reemplaza.
      </p>
      <div className="grid gap-1">
        <Label htmlFor="tarifario-archivo">Archivo CSV</Label>
        <Input id="tarifario-archivo" ref={entrada} type="file" accept=".csv,.txt,text/csv,text/plain"
               onChange={(ev) => setArchivo(ev.target.files?.[0] ?? null)} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1">
          <Label htmlFor="tarifario-vigencia">Vigencia</Label>
          <Input id="tarifario-vigencia" type="date" value={vigencia} onChange={(ev) => setVigencia(ev.target.value)} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="tarifario-estadia">Valor de estadía (opcional)</Label>
          <Input id="tarifario-estadia" inputMode="decimal" value={estadia} placeholder="214.146,67"
                 className="tabular-nums" onChange={(ev) => setEstadia(ev.target.value)} />
        </div>
      </div>
      <div className="grid gap-1">
        <Label htmlFor="tarifario-nombre">Nombre</Label>
        <Input id="tarifario-nombre" value={nombre} placeholder="Por ejemplo, Tarifario de referencia abril 2026"
               onChange={(ev) => setNombre(ev.target.value)} />
      </div>
      {reemplaza && (
        <p role="note" className="text-xs font-medium text-amber-800 dark:text-amber-400">
          Ya hay una edición con la vigencia {formatearFecha(vigencia)}: se va a reemplazar entera.
        </p>
      )}
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      {aviso && <p role="status" className="rounded border p-3 text-sm">{aviso}</p>}
      <div>
        <Button type="submit" disabled={!completo || enviando}>
          <Upload className="size-4" /> {enviando ? 'Cargando…' : 'Cargar'}
        </Button>
      </div>
    </form>
  )
}

export function TarifarioDeReferencia() {
  const { user } = useAuth() as { user: { role?: string } | null }
  const esAdmin = user?.role === 'admin'
  const [ediciones, setEdiciones] = useState<Tarifario[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [abierta, setAbierta] = useState<Tarifario | null>(null)
  const [recarga, setRecarga] = useState(0)

  useEffect(() => {
    let vigente = true
    setCargando(true)
    tarifario.listar()
      .then((l) => { if (vigente) setEdiciones(l) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [recarga])

  const columnas = [
    { id: 'vigencia', header: 'Vigencia', accessorFn: (t: Tarifario) => formatearFecha(t.vigencia) },
    { accessorKey: 'nombre', header: 'Nombre' },
    { id: 'km', header: 'Km', meta: { className: 'tabular-nums' }, accessorFn: rangoDeKm },
    { id: 'filas', header: 'Filas', meta: { className: 'tabular-nums' }, accessorFn: (t: Tarifario) => formatearKilos(t.filas) },
    { id: 'estadia', header: 'Valor de estadía', meta: { className: 'tabular-nums' },
      accessorFn: (t: Tarifario) => formatearImporte(t.valor_estadia) || '—' },
    { id: 'acciones', header: '',
      cell: ({ row }: Celda) => (
        <div className="flex justify-end">
          <Button variant="ghost" size="icon" aria-label={`Ver la tabla del ${formatearFecha(row.original.vigencia)}`}
                  onClick={() => setAbierta(row.original)}>
            <Eye className="size-4" />
          </Button>
        </div>
      ) },
  ]

  return (
    <div className="grid gap-2">
      <p className="text-muted-foreground max-w-2xl text-sm">
        La tarifa de referencia en pesos por tonelada para cada kilómetro. La orden de carga usa la edición vigente a su
        fecha para proponer la tarifa por tonelada; el porcentaje pactado se elige en cada viaje.
      </p>
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      <DataTable columns={columnas} data={ediciones}
                 emptyMessage={cargando ? 'Cargando…' : 'Todavía no hay ningún tarifario cargado.'} />
      {abierta && <TablaDeEdicion edicion={abierta} />}
      {esAdmin ? (
        <CargarEdicion ediciones={ediciones} alCargar={(t) => { setAbierta(t); setRecarga((n) => n + 1) }} />
      ) : (
        <p className="text-muted-foreground mt-4 text-xs">Las ediciones las carga un administrador.</p>
      )}
    </div>
  )
}

export default TarifarioDeReferencia
