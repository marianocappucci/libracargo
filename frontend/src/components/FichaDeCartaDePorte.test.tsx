/** La ficha de una carta de porte con los códigos de ARCA traducidos (ADR-051): grano, localidad y provincia con su
 *  nombre cuando el servidor lo tiene, y con su código —como antes— cuando todavía no. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CartaPorte } from '@/api/cartas-porte'
import { etiquetaDeGrano } from '@/api/cartas-porte'

import { FichaDeCartaDePorte } from './FichaDeCartaDePorte'

const parte = (cuit: string | null, nombre: string | null = null) => ({ cuit, nombre })

function carta(extra: Partial<CartaPorte> = {}): CartaPorte {
  return {
    id: 1, nro_ctg: 10123456781, numero: '00001-00072411', estado: 'AC', estado_descripcion: 'Activa',
    fecha_inicio_estado: null, fecha_emision: '2026-10-05T14:30:00', fecha_vencimiento: '2026-10-08T14:30:00',
    fecha_partida: '2026-10-05T16:00:00-03:00', cuit_representada: '30222222223', ambiente: 'produccion',
    transportista: parte('30222222223'), pagador_flete: parte('30111111118'), chofer: parte('20333333336'),
    origen: parte('30444444441'), destino: parte('30555555558'), destinatario: parte('30555555558'),
    dominios: ['AB123CD'], cod_grano: 23, cosecha: 2526, peso_bruto: 44000, peso_tara: 14500, peso_neto: 29500,
    peso_bruto_descarga: null, peso_tara_descarga: null, peso_neto_descarga: null,
    cod_provincia_origen: 12, cod_localidad_origen: 5321, cod_provincia_destino: 12, cod_localidad_destino: 4211,
    planta_destino: 9, km: 320, tarifa: '45678.50', tiene_pdf: false, tiene_descarga: false,
    consultada_en: '2026-10-06T09:00:00-03:00', orden_carga_id: null, guardada_id: null,
    ...extra,
  }
}

const CON_NOMBRES = {
  grano: 'SOJA', provincia_origen: 'SANTA FE', localidad_origen: 'FUNES',
  provincia_destino: 'SANTA FE', localidad_destino: 'ROSARIO',
}

describe('Ficha de una carta de porte: los códigos de ARCA con su nombre', () => {
  it('con los nombres bajados muestra grano, localidad y provincia, no los códigos', () => {
    render(<FichaDeCartaDePorte carta={carta(CON_NOMBRES)} />)

    expect(screen.getByText('SOJA · cosecha 25/26')).toBeInTheDocument()
    expect(screen.getByText('30-44444444-1 · FUNES, SANTA FE')).toBeInTheDocument()
    expect(screen.getByText('30-55555555-8 · ROSARIO, SANTA FE · Planta 9')).toBeInTheDocument()
    expect(screen.queryByText(/Provincia 12/)).toBeNull()
    expect(screen.queryByText(/Localidad 5321/)).toBeNull()
    expect(screen.queryByText(/Grano 23/)).toBeNull()
  })

  it('sin nombres (todavía no se bajó la tabla) sigue mostrando los códigos', () => {
    render(<FichaDeCartaDePorte carta={carta()} />)

    expect(screen.getByText('Grano 23 · cosecha 25/26')).toBeInTheDocument()
    expect(screen.getByText('30-44444444-1 · Provincia 12 · Localidad 5321')).toBeInTheDocument()
    expect(screen.getByText('30-55555555-8 · Provincia 12 · Localidad 4211 · Planta 9')).toBeInTheDocument()
  })

  it('con el nombre de la provincia y no el de la localidad, cada uno con lo suyo', () => {
    render(<FichaDeCartaDePorte carta={carta({ provincia_origen: 'SANTA FE', localidad_origen: null })} />)

    expect(screen.getByText('30-44444444-1 · SANTA FE · Localidad 5321')).toBeInTheDocument()
  })

  it('una carta sin grano ni cosecha no inventa nada', () => {
    render(<FichaDeCartaDePorte carta={carta({ cod_grano: null, cosecha: null })} />)

    expect(screen.getByText('Grano').nextElementSibling).toHaveTextContent('—')
  })

  it('una cosecha con otro formato se muestra tal cual', () => {
    render(<FichaDeCartaDePorte carta={carta({ cosecha: 25 })} />)

    expect(screen.getByText('Grano 23 · cosecha 25')).toBeInTheDocument()
  })

  it('dice cuándo se le consultó por última vez a ARCA', () => {
    render(<FichaDeCartaDePorte carta={carta()} />)

    expect(screen.getByText('Última consulta a ARCA')).toBeInTheDocument()
  })

  it('en la vista previa (sin consulta guardada) no muestra esa línea', () => {
    render(<FichaDeCartaDePorte carta={carta({ id: null, consultada_en: null })} />)

    expect(screen.queryByText('Última consulta a ARCA')).toBeNull()
  })
})

describe('etiquetaDeGrano', () => {
  it('prefiere el nombre, cae al código y, sin nada, a un guion', () => {
    expect(etiquetaDeGrano({ grano: 'SOJA', cod_grano: 23 })).toBe('SOJA')
    expect(etiquetaDeGrano({ grano: null, cod_grano: 23 })).toBe('Grano 23')
    expect(etiquetaDeGrano({ cod_grano: 23 })).toBe('Grano 23')
    expect(etiquetaDeGrano({ grano: null, cod_grano: null })).toBe('—')
  })
})
