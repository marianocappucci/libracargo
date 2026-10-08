/** Pre facturas: lo que se mandó (o se va a mandar) al cliente antes de facturar (ADR-032).
 *
 * La lista con su estado, y un filtro por estado y por cliente. Cada fila lleva a la pre factura
 * (`/pre-facturas/:id`), que es donde se la manda, se la acepta, se la edita, se la anula y se la factura.
 * Se genera desde **Facturar pendientes**: acá no hay alta, porque una pre factura sin órdenes no existe.
 */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ArrowLeft, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { NOMBRE_DE_TIPO } from '@/api/comprobantes'
import type { EstadoPreFactura, PreFactura } from '@/api/pre-facturas'
import { NOMBRE_DE_ESTADO, TONO_DE_ESTADO, preFacturas, tipoDe } from '@/api/pre-facturas'
import { mensajeDeError } from '@/components/AbmMaestro'
import { formatearFecha, formatearImporte } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { irA } from '@/navegacion'
import { ICONOS_LC } from '@/iconos'

const ESTADOS = Object.keys(NOMBRE_DE_ESTADO) as EstadoPreFactura[]

export default function PreFacturas() {
  const navegar = useNavigate()
  const [filas, setFilas] = useState<PreFactura[]>([])
  const [conteos, setConteos] = useState<Record<string, number>>({})
  const [estado, setEstado] = useState('')
  const [cliente, setCliente] = useState('')
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // El texto del cliente espera un respiro: escribir «Agro» no tiene que ser cuatro consultas.
  useEffect(() => {
    let vigente = true
    setCargando(true)
    const espera = setTimeout(() => {
      preFacturas.listar({ estado, cliente: cliente.trim() })
        .then((r) => { if (vigente) { setFilas(r.items); setConteos(r.counts); setError(null) } })
        .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
        .finally(() => { if (vigente) setCargando(false) })
    }, cliente ? 300 : 0)
    return () => { vigente = false; clearTimeout(espera) }
  }, [estado, cliente])

  const columnas = [
    { accessorKey: 'numero_interno', header: sortableHeader('Número') },
    { id: 'fecha', header: sortableHeader('Fecha'),
      accessorFn: (p: PreFactura) => p.fecha_sugerida,
      cell: ({ row }: { row: { original: PreFactura } }) => formatearFecha(row.original.fecha_sugerida) },
    { accessorKey: 'cliente_razon', header: 'Cliente' },
    { id: 'tipo', header: 'Comprobante',
      accessorFn: (p: PreFactura) => { const t = tipoDe(p); return t ? NOMBRE_DE_TIPO[t] : '' } },
    { id: 'total', header: sortableHeader('Total'),
      accessorFn: (p: PreFactura) => formatearImporte(p.total) },
    { id: 'estado', header: 'Estado',
      accessorFn: (p: PreFactura) => NOMBRE_DE_ESTADO[p.estado],
      cell: ({ row }: { row: { original: PreFactura } }) => (
        <BadgeEstado tono={TONO_DE_ESTADO[row.original.estado]}>
          {NOMBRE_DE_ESTADO[row.original.estado]}
        </BadgeEstado>
      ) },
  ]

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        {/* Ya no tiene entrada de menú: se llega desde Comprobantes > Clientes, y de acá se vuelve ahí. */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild aria-label="Volver a Comprobantes">
            <Link to="/comprobantes"><ArrowLeft className="size-4" /></Link>
          </Button>
          <TituloPantalla icono={ICONOS_LC.preFacturas}>Pre facturas</TituloPantalla>
        </div>
        <Button asChild>
          <Link to={irA.facturarPendientes()}>
            <Plus className="size-4" /> Generar pre factura
          </Link>
        </Button>
      </div>

      <p className="text-muted-foreground mb-4 text-sm">
        Un documento sin valor fiscal que se manda al cliente para que confirme los datos. La factura
        se emite después, por ARCA, desde la pre factura.
      </p>

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="pf-estado">Estado</Label>
          {/* select-cerrado: los estados de la pre factura (`ESTADOS`), una constante del código: no hay nada que buscar */}
          <select id="pf-estado" className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
                  value={estado} onChange={(e) => setEstado(e.target.value)}>
            <option value="">Todas</option>
            {ESTADOS.map((e) => (
              <option key={e} value={e}>{NOMBRE_DE_ESTADO[e]}{` (${conteos[e] ?? 0})`}</option>
            ))}
          </select>
        </div>
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="pf-cliente">Cliente</Label>
          <Input id="pf-cliente" placeholder="Razón social o CUIT" value={cliente}
                 onChange={(e) => setCliente(e.target.value)} />
        </div>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">{error}</p>
      )}

      <DataTable
        columns={columnas}
        data={filas}
        onRowClick={(p: PreFactura) => navegar(irA.preFactura(p.id))}
        emptyMessage={cargando ? 'Cargando…'
          : estado || cliente ? 'No hay pre facturas con ese filtro.' : 'Todavía no hay pre facturas.'}
      />
    </div>
  )
}
