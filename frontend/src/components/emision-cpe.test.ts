/** La lógica de «Emitir carta de porte» que no es pantalla: el borrador, lo que se manda y los rangos. */
import { describe, expect, it } from 'vitest'

import type { DatosDePlantilla, Propuesta } from '@/api/cartas-porte'
import { enlaceDeWhatsApp, textoParaCompartir } from '@/api/cartas-porte'
import {
  borradorDe, borradorDePlantilla, datosDe, datosDePlantilla, netoDe, partidaAIso, partidaPorDefecto, problemasDe,
  problemasDePlantilla, relojDeArgentina,
} from './emision-cpe'

const PROPUESTA: Propuesta = {
  orden_id: 12, cuit_titular: '30222222223', sucursal: 1,
  origen: { tipo: 'campo', cod_provincia: 12, cod_localidad: 3456, renspa: null },
  cod_grano: 15, cosecha: 2526, peso_bruto: 44000, peso_tara: 14500,
  destino: { cuit: '30555555558', cod_provincia: 20, cod_localidad: 777, planta: 9, es_campo: false },
  cuit_destinatario: null,
  intervinientes: { cuitCorredorVentaPrimaria: '30111111118' }, cuit_remitente_comercial_productor: null,
  transporte: {
    cuit_transportista: '30999999995', dominios: ['ab123cd'], fecha_hora_partida: null, km: 320,
    cuit_chofer: '20333333336', cuit_pagador_flete: '30111111118', tarifa: '19724.73', mercaderia_fumigada: false,
  },
  observaciones: null, de_plantilla: false, faltantes: [],
}

describe('la partida', () => {
  it('se propone dentro de una hora, en hora de Argentina', () => {
    // 15:00 en Argentina son las 18:00 UTC: el reloj de pared tiene que ser el argentino, no el de la máquina.
    expect(partidaPorDefecto(new Date('2026-10-08T18:00:00Z'))).toBe('2026-10-08T16:00')
  })

  it('cruza la medianoche argentina sin usar el día de UTC', () => {
    // 23:30 en Argentina del 8 ya es el 9 en UTC; una hora después es el 9 de Argentina.
    expect(relojDeArgentina(new Date('2026-10-09T02:30:00Z'))).toBe('2026-10-08T23:30')
    expect(partidaPorDefecto(new Date('2026-10-09T02:30:00Z'))).toBe('2026-10-09T00:30')
  })

  it('viaja con la zona de Argentina', () => {
    expect(partidaAIso('2026-10-08T16:00')).toBe('2026-10-08T16:00:00-03:00')
  })
})

describe('del borrador a lo que se manda', () => {
  const ahora = new Date('2026-10-08T18:00:00Z')

  it('precarga la propuesta: CUIT con guiones, dominios en mayúsculas, destinatario = destino', () => {
    const b = borradorDe(PROPUESTA, ahora)
    expect(b.cuitTransportista).toBe('30-99999999-5')
    expect(b.dominios).toEqual(['AB123CD', '', ''])
    expect(b.cuitDestinatario).toBe('30-55555555-8')
    expect(b.intervinientes.cuitCorredorVentaPrimaria).toBe('30-11111111-8')
    expect(b.partida).toBe('2026-10-08T16:00')
  })

  it('manda números, CUIT sin guiones y sólo los intervinientes cargados', () => {
    const d = datosDe(borradorDe(PROPUESTA, ahora), '30222222223')
    expect(d.cod_grano).toBe(15)
    expect(d.peso_bruto).toBe(44000)
    expect(d.cuit_destinatario).toBe('30555555558')
    expect(d.intervinientes).toEqual({ cuitCorredorVentaPrimaria: '30111111118' })
    expect(d.transporte.fecha_hora_partida).toBe('2026-10-08T16:00:00-03:00')
    expect(d.transporte.dominios).toEqual(['AB123CD'])
    expect(d.transporte.tarifa).toBe('19724.73')
    expect(d.transporte.km).toBe(320)
    expect(d.observaciones).toBeNull()
  })

  it('una tarifa con coma viaja con punto', () => {
    const d = datosDe({ ...borradorDe(PROPUESTA, ahora), tarifa: '19724,73' }, '30222222223')
    expect(d.transporte.tarifa).toBe('19724.73')
  })

  it('un origen en planta manda el número de planta y no el RENSPA', () => {
    const d = datosDe({ ...borradorDe(PROPUESTA, ahora), origenTipo: 'planta', origenPlanta: '5', origenRenspa: 'x' },
      '30222222223')
    expect(d.origen).toEqual({ tipo: 'planta', cod_provincia: 12, cod_localidad: 3456, planta: 5 })
  })
})

describe('qué falta', () => {
  const ok = () => borradorDe(PROPUESTA, new Date('2026-10-08T18:00:00Z'))

  it('una propuesta completa no tiene problemas', () => {
    expect(problemasDe(ok())).toEqual({})
  })

  it('marca como obligatorio lo vacío', () => {
    const p = problemasDe({ ...ok(), cuitChofer: '', codGrano: '', km: '', dominios: ['', '', ''], partida: '' })
    expect(p.cuitChofer).toBe('Obligatorio')
    expect(p.codGrano).toBe('Obligatorio')
    expect(p.km).toBe('Obligatorio')
    expect(p.dominios).toBe('Obligatorio: al menos uno')
    expect(p.partida).toBe('Obligatorio')
  })

  it('aplica los mismos rangos que valida libracore antes de llamar a ARCA', () => {
    const p = problemasDe({
      ...ok(), cuitChofer: '20-3333', cosecha: '25', pesoBruto: '90000', pesoTara: '0', km: '100000',
      dominios: ['ABC', '', ''], tarifa: '123456',
    })
    expect(p.cuitChofer).toBe('Un CUIT tiene 11 dígitos')
    expect(p.cosecha).toBe('Cuatro cifras (2526 = 2025/2026)')
    expect(p.pesoBruto).toBe('El peso bruto va de 1 a 88.000 kg')
    expect(p.pesoTara).toBe('El peso tara va de 1 a 88.000 kg')
    expect(p.km).toBe('Los kilómetros van de 1 a 99.999')
    expect(p.dominios).toBe('Un dominio tiene 6 o 7 caracteres')
    expect(p.tarifa).toBeDefined()
  })

  it('la tara tiene que ser menor que el bruto, y el neto sólo se calcula con números', () => {
    expect(problemasDe({ ...ok(), pesoTara: '44000' }).pesoTara).toBe('La tara tiene que ser menor que el peso bruto')
    expect(netoDe({ pesoBruto: '44000', pesoTara: '14500' })).toBe(29500)
    expect(netoDe({ pesoBruto: '44000', pesoTara: '' })).toBeNull()
  })

  it('un interviniente vacío está bien; uno a medias, no', () => {
    expect(problemasDe({ ...ok(), remitenteProductor: '' })).toEqual({})
    expect(problemasDe({ ...ok(), remitenteProductor: '30-1' }).remitenteProductor).toBe('Un CUIT tiene 11 dígitos')
  })
})

describe('el texto para compartir', () => {
  const carta = { numero: '00001-00072413', nro_ctg: 10123456781, peso_neto: 29500, km: 320 }

  it('arma el mensaje con el tramo, los kilos, los km y el enlace', () => {
    expect(textoParaCompartir(carta, 'Suipacha', 'Rosario', 'https://x.test/a.pdf')).toBe(
      'Carta de porte 00001-00072413 · CTG 10123456781 · Suipacha → Rosario · 29.500 kg · 320 km. PDF: https://x.test/a.pdf')
  })

  it('omite lo que no se sabe en vez de dejar un hueco', () => {
    expect(textoParaCompartir({ ...carta, peso_neto: null, km: null }, '', 'Rosario', 'https://x.test/a.pdf')).toBe(
      'Carta de porte 00001-00072413 · CTG 10123456781 · Rosario. PDF: https://x.test/a.pdf')
  })

  it('el enlace de WhatsApp lleva el texto codificado', () => {
    expect(enlaceDeWhatsApp('a b&c · é')).toBe(`https://wa.me/?text=${encodeURIComponent('a b&c · é')}`)
  })
})

describe('la plantilla de un titular (ADR-044)', () => {
  /** Lo que `emitir` deja guardado: las claves de `CAMPOS_DE_PLANTILLA` del servidor. */
  const GUARDADA: DatosDePlantilla = {
    sucursal: 2,
    origen: { tipo: 'planta', cod_provincia: 12, cod_localidad: 3456, planta: 41 },
    cod_grano: 15, cosecha: 2526,
    destino: { cuit: '30555555558', cod_provincia: 20, cod_localidad: 777, planta: 9, es_campo: true },
    cuit_destinatario: '30555555558',
    intervinientes: { cuitCorredorVentaPrimaria: '30111111118' },
    cuit_remitente_comercial_productor: '20123456786',
    mercaderia_fumigada: true, km: 320, observaciones: 'Descarga de 6 a 14',
  }

  it('🔑 va y vuelve sin perder nada: del servidor al borrador y del borrador al servidor', () => {
    expect(datosDePlantilla(borradorDePlantilla(GUARDADA))).toEqual(GUARDADA)
  })

  it('🔑 las claves son exactamente las que el servidor lee de la plantilla (CAMPOS_DE_PLANTILLA)', () => {
    // Mismo listado que `emision_cpe.CAMPOS_DE_PLANTILLA` del backend; si allá cambia, acá cae el rojo.
    const delServidor = ['sucursal', 'origen', 'cod_grano', 'cosecha', 'destino', 'cuit_destinatario', 'intervinientes',
      'cuit_remitente_comercial_productor', 'mercaderia_fumigada', 'km', 'observaciones']
    expect(Object.keys(datosDePlantilla(borradorDePlantilla(GUARDADA))).sort()).toEqual([...delServidor].sort())
  })

  it('las claves de lo que se manda al emitir incluyen todas las de la plantilla (salvo las del viaje)', () => {
    const emitido = Object.keys(datosDe(borradorDe(PROPUESTA), '30222222223'))
    for (const clave of Object.keys(GUARDADA)) {
      expect([...emitido, 'mercaderia_fumigada', 'km'], clave).toContain(clave)
    }
  })

  it('una plantilla vacía queda vacía: lo que no se cargó no se manda', () => {
    expect(datosDePlantilla(borradorDePlantilla({}))).toEqual({})
  })

  it('la sucursal 1 es la de siempre y no se guarda; otra sí', () => {
    expect(datosDePlantilla(borradorDePlantilla({ sucursal: 1 }))).toEqual({})
    expect(datosDePlantilla(borradorDePlantilla({ sucursal: 3 }))).toEqual({ sucursal: 3 })
  })

  it('un origen en planta guarda su planta; en campo, su RENSPA', () => {
    expect(datosDePlantilla(borradorDePlantilla({ origen: { tipo: 'planta', cod_provincia: 1, cod_localidad: 2, planta: 7 } })))
      .toEqual({ origen: { tipo: 'planta', cod_provincia: 1, cod_localidad: 2, planta: 7 } })
    expect(datosDePlantilla(borradorDePlantilla({ origen: { tipo: 'campo', renspa: '01.001' } })))
      .toEqual({ origen: { tipo: 'campo', cod_provincia: null, cod_localidad: null, renspa: '01.001' } })
  })

  it('🔑 las reglas son las del asistente: mismos mensajes para los mismos errores', () => {
    const mala = borradorDePlantilla({
      cosecha: 252, km: 100000, cuit_destinatario: '123', observaciones: 'x'.repeat(2001),
      intervinientes: { cuitMercadoATermino: '20123' },
    })
    const delAsistente = problemasDe({
      ...borradorDe(PROPUESTA), cosecha: mala.cosecha, km: mala.km, cuitDestinatario: mala.cuitDestinatario,
      observaciones: mala.observaciones, intervinientes: { ...borradorDe(PROPUESTA).intervinientes, ...mala.intervinientes },
    })
    const delEditor = problemasDePlantilla(mala)
    for (const campo of ['cosecha', 'km', 'cuitDestinatario', 'observaciones', 'interviniente:cuitMercadoATermino']) {
      expect(delEditor[campo], campo).toBeDefined()
      expect(delEditor[campo], campo).toBe(delAsistente[campo])
    }
  })

  it('nada es obligatorio: una plantilla vacía no tiene problemas', () => {
    expect(problemasDePlantilla(borradorDePlantilla({}))).toEqual({})
  })
})
