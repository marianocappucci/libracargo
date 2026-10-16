/** El payload del alta de un cliente (`POST /api/terceros`): una sola función lo arma para todas las pantallas. */
import { IVA_CONDITIONS } from 'libra-ui/facturas'
import { describe, expect, it } from 'vitest'

import { conClienteNuevo, terceroDeCliente } from './clientes'

const base = { nombre: 'Cereales del Sur', documento: '', condicionIva: '', telefono: '', email: '' }

describe('terceroDeCliente', () => {
  it('siempre es un cliente con su razón social; lo que no se pidió no viaja', () => {
    expect(terceroDeCliente(base)).toEqual({ razon_social: 'Cereales del Sur', es_cliente: true })
  })

  it('lleva el CUIT, el teléfono y el email cuando se cargaron', () => {
    expect(terceroDeCliente({ ...base, documento: '30-71234567-8', telefono: '2226 444555', email: 'a@b.com' })).toEqual({
      razon_social: 'Cereales del Sur', es_cliente: true, cuit: '30-71234567-8', telefono: '2226 444555', email: 'a@b.com',
    })
  })

  it('pasa los textos del kit al enum del servidor', () => {
    const iva = (c: string) => terceroDeCliente({ ...base, condicionIva: c }).condicion_iva
    expect(iva('Responsable Inscripto')).toBe('responsable_inscripto')
    expect(iva('Monotributista')).toBe('monotributo')
    expect(iva('IVA Exento')).toBe('exento')
    expect(iva('Consumidor Final')).toBe('consumidor_final')
  })

  it('«No Alcanzado» e «IVA No Responsable» no tienen equivalente: no viajan y el servidor usa su valor por defecto', () => {
    for (const c of ['No Alcanzado', 'IVA No Responsable']) {
      expect(terceroDeCliente({ ...base, condicionIva: c })).not.toHaveProperty('condicion_iva')
    }
  })

  it('🔴 cada condición del kit está contemplada: si el kit suma una, este test obliga a decidir qué hace acá', () => {
    const conEquivalente = ['Responsable Inscripto', 'Monotributista', 'IVA Exento', 'Consumidor Final']
    const sinEquivalente = ['No Alcanzado', 'IVA No Responsable']
    expect([...IVA_CONDITIONS].sort()).toEqual([...conEquivalente, ...sinEquivalente].sort())
  })
})

describe('conClienteNuevo', () => {
  const c = { id: 77, etiqueta: 'Cereales del Sur' }
  it('suma el cliente a la lista de clientes y a la de terceros, una sola vez', () => {
    const o = conClienteNuevo(conClienteNuevo({ clientes: [], terceros: [], otra: 1 }, c), c)
    expect(o).toEqual({ clientes: [c], terceros: [c], otra: 1 })
  })
})
