/** Titulares: los clientes a cuyo nombre se emiten cartas de porte, y los que las emiten ellos (ADR-044).
 *
 *  Pedido del dueño (2026-10-08): *«vamos a tener otros clientes que nos van a delegar en ARCA para que podamos hacer
 *  nosotros las cartas de porte, como habrá otros que las hagan ellos mismos. Tendríamos que tener en pantalla una sección
 *  para guardar esos datos y poder ir cargándolos»*.
 *
 *  🔑 **La delegación se lee de ARCA, no se tilda.** Cada titular dice «Delegado ✓» si está entre las relaciones del ticket
 *  de `wscpe`, «Pendiente» si está cargado y ARCA todavía no lo trae (lo suma con el próximo ticket, hasta 12 horas),
 *  «Sin verificar» si no hay certificado o ARCA no contestó —con el motivo a la vista, sin romper la pantalla—. Vale
 *  también para el que «Emite él»: la delegación de `wscpe` habilita consultar sus cartas por CTG además de emitirlas, y
 *  quién emite sólo decide si se le ofrece emitir. Un CUIT que ARCA trae y no está cargado aparece aparte, como «Delegado sin cargar», con
 *  «Agregar».
 *
 *  Ver es de cualquier operador; cargar, editar y borrar —y la plantilla— son de un administrador.
 */
import { BadgeEstado } from 'libra-ui/badge-estado'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import type { ListadoDeTitulares, Titular, TitularSinCargar } from '@/api/cartas-porte'
import {
  ETIQUETA_DE_QUIEN_EMITE, cartasPorte, etiquetaDeDelegacion, formatearCuit, tonoDeDelegacion,
} from '@/api/cartas-porte'
import { mensajeDeError } from '@/components/AbmMaestro'
import { AccionesDelTitulo } from '@/components/AccionesDelTitulo'
import { FichaDeTitular } from '@/components/FichaDeTitular'
import type { PartidaDelAlta } from '@/components/FichaDeTitular'
import { InstruccionesDeDelegacion } from '@/components/InstruccionesDeDelegacion'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/context/AuthContext'
import { irA } from '@/navegacion'

import { useFichaEnLaUrl } from './maestros/hooks'

type Celda = { row: { original: Titular } }

/** Cuál ficha está abierta: la de un titular cargado, el alta en blanco, o el alta de uno que ARCA trae. */
type Abierta = { tipo: 'titular'; id: number } | { tipo: 'alta'; partida: PartidaDelAlta | null }

export function Titulares() {
  const { user } = useAuth()
  const esAdmin = user?.role === 'admin'
  const { abrirId, alCerrarFicha } = useFichaEnLaUrl()
  const [listado, setListado] = useState<ListadoDeTitulares | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recarga, setRecarga] = useState(0)
  const [abierta, setAbierta] = useState<Abierta | null>(null)

  useEffect(() => {
    let vigente = true
    cartasPorte.titulares()
      .then((r) => { if (vigente) { setListado(r); setError(null) } })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [recarga])

  const recargar = useCallback(() => setRecarga((n) => n + 1), [])

  // `?ver=<id>` abre la ficha de ese titular, como llega el enlace de la ficha del cliente.
  useEffect(() => {
    if (abrirId !== null && listado?.titulares.some((t) => t.id === abrirId)) {
      setAbierta({ tipo: 'titular', id: abrirId })
    }
  }, [abrirId, listado])

  function cambiarAbierta(abre: boolean) {
    if (abre) return
    if (abierta?.tipo === 'titular' && abrirId !== null) alCerrarFicha()
    setAbierta(null)
  }

  const titular = abierta?.tipo === 'titular' ? listado?.titulares.find((t) => t.id === abierta.id) ?? null : null
  const partida = abierta?.tipo === 'alta' ? abierta.partida : null
  const hayFicha = abierta?.tipo === 'alta' || titular !== null

  function agregar(s: TitularSinCargar) {
    setAbierta({
      tipo: 'alta',
      partida: { cuit: s.cuit, razon_social: s.tercero?.razon_social ?? '', tercero_id: s.tercero?.id ?? null },
    })
  }

  const columnas = [
    { id: 'razon', header: sortableHeader('Razón social'),
      accessorFn: (t: Titular) => t.razon_social,
      cell: ({ row }: Celda) => {
        const t = row.original
        return (
          <div>
            <div className={t.activo ? undefined : 'text-muted-foreground line-through'}>{t.razon_social}</div>
            {t.tercero && (
              <Link to={irA.entidades('clientes', t.tercero.id)} className="text-muted-foreground text-xs underline"
                    onClick={(e) => e.stopPropagation()}>
                Cliente: {t.tercero.razon_social}
              </Link>
            )}
          </div>
        )
      } },
    { id: 'cuit', header: sortableHeader('CUIT'), accessorFn: (t: Titular) => formatearCuit(t.cuit) },
    { id: 'emite', header: 'Quién emite', accessorFn: (t: Titular) => ETIQUETA_DE_QUIEN_EMITE[t.emite] },
    { id: 'delegacion', header: 'Delegación en ARCA',
      accessorFn: (t: Titular) => etiquetaDeDelegacion(t.delegacion, t.emite),
      cell: ({ row }: Celda) => (
        <BadgeEstado tono={tonoDeDelegacion(row.original.delegacion)}>
          {etiquetaDeDelegacion(row.original.delegacion, row.original.emite)}
        </BadgeEstado>
      ) },
    { id: 'plantilla', header: 'Datos habituales',
      accessorFn: (t: Titular) => (t.emite === 'titular' ? '—' : t.tiene_plantilla ? 'Cargados' : 'Sin cargar') },
    { id: 'estado', header: 'Estado', accessorFn: (t: Titular) => (t.activo ? 'Activo' : 'Baja') },
  ]

  return (
    <div className="grid gap-4">
      {esAdmin && (
        <AccionesDelTitulo>
          <Button onClick={() => setAbierta({ tipo: 'alta', partida: null })}>
            <Plus className="size-4" /> Nuevo titular
          </Button>
        </AccionesDelTitulo>
      )}

      <p className="text-muted-foreground text-sm">
        Los clientes a cuyo nombre emitimos cartas de porte porque nos delegaron <code>wscpe</code> en ARCA, y los que las
        emiten ellos. Si un titular figura como «Pendiente», ARCA todavía no informa su delegación: la suma con el
        próximo ticket, que puede tardar hasta 12 horas.
      </p>

      {error && <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>}
      {listado && !listado.verificado && (
        <p role="status" className="rounded-md border border-amber-600/50 bg-amber-500/10 p-3 text-sm">
          <strong>Sin verificar en ARCA.</strong> {listado.motivo}
        </p>
      )}

      <DataTable
        columns={columnas}
        data={listado?.titulares ?? []}
        onRowClick={(t: Titular) => setAbierta({ tipo: 'titular', id: t.id })}
        emptyMessage={listado === null && !error ? 'Cargando…'
          : 'Todavía no hay titulares cargados. Cargalos con «Nuevo titular», o agregá los que ARCA ya trae.'}
      />

      {listado && listado.sin_cargar.length > 0 && (
        <section aria-label="Delegados sin cargar" className="grid gap-2 rounded-md border p-4">
          <div>
            <h2 className="text-sm font-semibold">Delegados sin cargar</h2>
            <p className="text-muted-foreground text-xs">
              ARCA informa que estos CUIT le delegaron la emisión a nuestro certificado, pero no están en la lista.
            </p>
          </div>
          <ul className="grid gap-2">
            {listado.sin_cargar.map((s) => (
              <li key={s.cuit} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>
                  <span className="font-medium">{s.tercero?.razon_social ?? 'Sin nombre cargado'}</span>
                  <span className="text-muted-foreground tabular-nums"> · {formatearCuit(s.cuit)}</span>
                </span>
                <span className="flex items-center gap-2">
                  <BadgeEstado tono="curso">Delegado sin cargar</BadgeEstado>
                  {esAdmin && (
                    <Button size="sm" variant="outline" onClick={() => agregar(s)}
                            aria-label={`Agregar ${formatearCuit(s.cuit)}`}>
                      Agregar
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <InstruccionesDeDelegacion />

      <FichaDeTitular
        abierto={hayFicha}
        alCambiarAbierto={cambiarAbierta}
        titular={titular}
        partida={partida}
        esAdmin={esAdmin}
        motivo={listado?.motivo ?? null}
        alCambiar={recargar}
      />
    </div>
  )
}
