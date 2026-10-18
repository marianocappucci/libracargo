/** El payload del alta de un cliente (`POST /api/terceros`): una sola función lo arma para todas las pantallas. */
import { IVA_CONDITIONS } from 'libra-ui/facturas'
import { describe, expect, it } from 'vitest'

import { arregloDe, conClienteNuevo, conTerceroNuevo, terceroConRol, terceroDeCliente } from './clientes'

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

  it('«No Alcanzado» no tiene equivalente: no viaja y el servidor usa su valor por defecto', () => {
    for (const c of ['No Alcanzado']) {
      expect(terceroDeCliente({ ...base, condicionIva: c })).not.toHaveProperty('condicion_iva')
    }
  })

  it('🔴 cada condición del kit está contemplada: si el kit suma una, este test obliga a decidir qué hace acá', () => {
    const conEquivalente = ['Responsable Inscripto', 'Monotributista', 'IVA Exento', 'Consumidor Final']
    // «IVA No Responsable» salió del kit en v0.158.2 (ADR-072).
    const sinEquivalente = ['No Alcanzado']
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

describe('arregloDe (CUIT repetido, ADR-052)', () => {
  const repetido = (roles: ('cliente' | 'fletero' | 'proveedor')[], activo = true) =>
    ({ mensaje: '', existente: { id: 2, razon_social: 'Transportes del Sur', roles, activo } })

  it('a quien no es cliente se le suma el rol; a un cliente de baja se lo reactiva; a uno activo se lo elige', () => {
    expect(arregloDe(repetido(['fletero']))).toBe('sumar-rol')
    expect(arregloDe(repetido(['proveedor'], false))).toBe('sumar-rol')
    expect(arregloDe(repetido(['cliente', 'fletero'], false))).toBe('reactivar')
    expect(arregloDe(repetido(['cliente']))).toBe('elegir')
  })
})

describe('el alta en otro rol (el «Tercero» de Caja, ADR-053)', () => {
  const repetido = (roles: ('cliente' | 'fletero' | 'proveedor')[], activo = true) =>
    ({ mensaje: '', existente: { id: 2, razon_social: 'Transportes del Sur', roles, activo } })

  it('el cuerpo lleva el rol pedido y nada más de roles; los datos son los mismos que los de un cliente', () => {
    expect(terceroConRol({ ...base, documento: '30-71234567-8' }, 'fletero')).toEqual({
      razon_social: 'Cereales del Sur', es_fletero: true, cuit: '30-71234567-8',
    })
    expect(terceroConRol(base, 'proveedor')).toEqual({ razon_social: 'Cereales del Sur', es_proveedor: true })
    expect(terceroConRol(base, 'cliente')).toEqual(terceroDeCliente(base))
  })

  it('el arreglo del CUIT repetido mira el rol pedido, no el de cliente', () => {
    expect(arregloDe(repetido(['cliente']), 'fletero')).toBe('sumar-rol')
    expect(arregloDe(repetido(['fletero']), 'fletero')).toBe('elegir')
    expect(arregloDe(repetido(['proveedor'], false), 'proveedor')).toBe('reactivar')
  })

  it('el nuevo entra a la lista de su rol y a la de terceros, una sola vez, y no a la de clientes', () => {
    const c = { id: 77, etiqueta: 'Gomería Ficticia' }
    const vacio = { clientes: [], fleteros: [], proveedores: [], terceros: [] }
    expect(conTerceroNuevo(conTerceroNuevo(vacio, c, 'proveedor'), c, 'proveedor'))
      .toEqual({ clientes: [], fleteros: [], proveedores: [c], terceros: [c] })
  })
})
