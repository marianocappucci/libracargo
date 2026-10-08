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
 *  de mandar. 🔑 **Se carga el PDF tal como se descarga** (ADR-039): el servidor lo lee y el formulario muestra qué
 *  entendió antes de guardar; el 422 (un PDF que no se pudo leer con seguridad, un CSV mal armado) se muestra tal cual
 *  lo dice el servidor.
 */
import { DataTable } from 'libra-ui/data-table'
import { Eye, Upload } from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useRef, useState } from 'react'

import type { FilaDeTarifa, Tarifario, VistaPreviaDeTarifario } from '@/api/tarifario'
import { tarifario } from '@/api/tarifario'
import { formatearKilos } from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { formatearFecha, formatearImporte } from '@/components/esquema-orden'
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

/** `214146.67` → `214.146,67`: el valor de estadía como se escribe en el campo (el servidor entiende las dos formas). */
const estadiaParaElCampo = (valor: string | null) => formatearImporte(valor).replace(/^\$ /, '')

/** El formulario de carga (ADR-039): el PDF tal como lo descarga el transportista de la página del sector (o un CSV
 *  `km;tarifa`). Al elegir el archivo el servidor lo lee **sin guardar** y se muestra qué entendió, para compararlo contra
 *  el PDF; vigencia, nombre y valor de estadía quedan precargados con eso y se pueden corregir. Sólo se monta para el
 *  administrador.
 *
 *  🔑 Si el servidor no pudo leer el archivo con seguridad (422), no hay vista previa y no se puede confirmar: más vale
 *  no cargar que cargar una tabla leída a medias. */
function CargarEdicion({ ediciones, alCargar }: { ediciones: Tarifario[]; alCargar: (t: Tarifario) => void }) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [vista, setVista] = useState<VistaPreviaDeTarifario | null>(null)
  const [leyendo, setLeyendo] = useState(false)
  const [vigencia, setVigencia] = useState('')
  const [nombre, setNombre] = useState('')
  const [estadia, setEstadia] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const entrada = useRef<HTMLInputElement>(null)
  // Si se elige otro archivo mientras el anterior se lee, la respuesta vieja no pisa a la nueva.
  const lectura = useRef(0)

  const vigenciaLeida = vista?.vigencia ?? ''
  const nombreLeido = vista?.nombre ?? ''
  const estadiaLeida = estadiaParaElCampo(vista?.valor_estadia ?? null)

  const reemplaza = vigencia === '' ? false
    : vigencia === vigenciaLeida ? (vista?.reemplaza ?? false)
    : ediciones.some((t) => t.vigencia === vigencia)
  const completo = archivo !== null && vista !== null && vigencia !== ''

  function limpiarVista() {
    setVista(null); setVigencia(''); setNombre(''); setEstadia('')
  }

  async function elegir(nuevo: File | null) {
    const mia = ++lectura.current
    setArchivo(nuevo)
    setError(null)
    setAviso(null)
    limpiarVista()
    if (!nuevo) { setLeyendo(false); return }
    setLeyendo(true)
    try {
      const v = await tarifario.previsualizar(nuevo)
      if (mia !== lectura.current) return
      setVista(v)
      setVigencia(v.vigencia ?? '')
      setNombre(v.nombre ?? '')
      setEstadia(estadiaParaElCampo(v.valor_estadia))
    } catch (err) {
      if (mia !== lectura.current) return
      // El 422 dice por qué no se pudo leer con seguridad: se muestra como viene.
      setError(mensajeDeError(err))
    } finally {
      if (mia === lectura.current) setLeyendo(false)
    }
  }

  async function cargar(e: FormEvent) {
    e.preventDefault()
    if (!archivo || !vista) return
    setError(null)
    setAviso(null)
    setEnviando(true)
    try {
      // Sólo lo que el usuario cambió o lo que el archivo no traía; lo demás lo lee el servidor del mismo archivo.
      const t = await tarifario.cargar({
        archivo,
        vigencia: vigencia !== vigenciaLeida ? vigencia : undefined,
        nombre: nombre.trim() !== nombreLeido ? nombre : undefined,
        valorEstadia: estadia.trim() !== estadiaLeida ? estadia : undefined,
      })
      setAviso(`Se cargó «${t.nombre}», vigencia ${formatearFecha(t.vigencia)}: ${formatearKilos(t.filas)} filas (km ${rangoDeKm(t)}).`)
      setArchivo(null)
      limpiarVista()
      if (entrada.current) entrada.current.value = ''
      alCargar(t)
    } catch (err) {
      // El 422 explica qué falla («línea 4: …», «indicá la vigencia…»): se muestra como viene, sin reescribirlo.
      setError(mensajeDeError(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={cargar} aria-label="Cargar una edición" className="mt-8 grid max-w-xl gap-3 border-t pt-6">
      <h3 className="text-sm font-semibold">Cargar una edición</h3>
      <p className="text-muted-foreground text-xs">
        Subí el PDF tal como lo descargás de la página. El sistema lee la tabla de km y tarifas, la vigencia y el valor
        de estadía. También se acepta un CSV <code>km;tarifa</code>.
      </p>
      <div className="grid gap-1">
        <Label htmlFor="tarifario-archivo">PDF del tarifario (o CSV)</Label>
        <Input id="tarifario-archivo" ref={entrada} type="file" accept=".pdf,.csv,application/pdf,text/csv"
               onChange={(ev) => void elegir(ev.target.files?.[0] ?? null)} />
      </div>
      {leyendo && <p role="status" className="text-muted-foreground text-sm">Leyendo el archivo…</p>}
      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      {vista && (
        <section aria-label="Vista previa" className="grid gap-2 rounded border p-3 text-sm">
          <h4 className="text-xs font-semibold">Esto es lo que se leyó del archivo</h4>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted-foreground">Vigencia</dt>
            <dd className="font-medium">{vista.vigencia ? formatearFecha(vista.vigencia) : 'no dice: indicala'}</dd>
            <dt className="text-muted-foreground">Nombre</dt>
            <dd className="font-medium">{vista.nombre || 'no dice'}</dd>
            <dt className="text-muted-foreground">Valor de estadía</dt>
            <dd className="font-medium tabular-nums">{formatearImporte(vista.valor_estadia) || 'no dice'}</dd>
            <dt className="text-muted-foreground">Tabla</dt>
            <dd className="font-medium tabular-nums">
              {formatearKilos(vista.filas)} filas, km {vista.km_desde ?? '—'} a {vista.km_hasta ?? '—'}
            </dd>
          </dl>
          {vista.muestra.length > 0 && (
            <table aria-label="Muestra de la tabla leída" className="w-full max-w-xs text-sm tabular-nums">
              <thead className="bg-muted">
                <tr>
                  <th scope="col" className="px-3 py-1 text-right font-medium">Km</th>
                  <th scope="col" className="px-3 py-1 text-right font-medium">$/t</th>
                </tr>
              </thead>
              <tbody>
                {vista.muestra.map((f) => (
                  <tr key={f.km} className="border-t">
                    <td className="px-3 py-1 text-right">{f.km}</td>
                    <td className="px-3 py-1 text-right">{formatearImporte(f.tarifa)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
      {vista && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1">
              <Label htmlFor="tarifario-vigencia">Vigencia</Label>
              <Input id="tarifario-vigencia" type="date" value={vigencia} required={vigenciaLeida === ''}
                     onChange={(ev) => setVigencia(ev.target.value)} />
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
        </>
      )}
      {reemplaza && (
        <p role="note" className="text-xs font-medium text-amber-800 dark:text-amber-400">
          Ya hay una edición con esa vigencia: se va a reemplazar entera.
        </p>
      )}
      {aviso && <p role="status" className="rounded border p-3 text-sm">{aviso}</p>}
      <div>
        <Button type="submit" disabled={!completo || enviando}>
          <Upload className="size-4" /> {enviando ? 'Cargando…' : 'Cargar tarifario'}
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
