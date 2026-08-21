import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { cargarOpciones } = await import('./ordenes')

const TERCEROS = [
  { id: 1, razon_social: 'Agro Norte', es_cliente: true, es_fletero: false, es_proveedor: false },
  { id: 2, razon_social: 'Fletes SRL', es_cliente: false, es_fletero: true, es_proveedor: false },
  // Proveedor PURO: es el caso que importa. Los 15 de la instancia del cliente
  // son asi, o sea que ninguno aparecia en ninguna lista.
  { id: 3, razon_social: 'Gomeria Del Centro', es_cliente: false, es_fletero: false,
    es_proveedor: true },
  // Dos roles a la vez: el que se repetia donde se concatenaban las listas.
  { id: 4, razon_social: 'Mixto SA', es_cliente: true, es_fletero: true, es_proveedor: false },
]

function responder(porRecurso: Record<string, unknown[]>) {
  get.mockImplementation((ruta: string) => {
    const recurso = ruta.replace('/api/', '').split('?')[0]
    const desplazamiento = Number(new URLSearchParams(ruta.split('?')[1]).get('desplazamiento') ?? 0)
    const filas = porRecurso[recurso] ?? []
    return Promise.resolve(filas.slice(desplazamiento, desplazamiento + 1000))
  })
}

const VACIOS = {
  terceros: TERCEROS, localidades: [], choferes: [], vehiculos: [],
  'tipos-carga': [], 'razones-sociales': [],
}

describe('cargarOpciones', () => {
  // 🔑 Cuerpo de bloque y no expresion: `mockReset()` DEVUELVE el mock, y
  // vitest trata lo que devuelve un `beforeEach` como hook de limpieza -- o
  // sea que lo llamaba **sin argumentos** al terminar cada test. El sintoma es
  // un "Cannot read properties of undefined" adentro del propio mock, y por eso
  // los otros tests del repo tienen un guard defensivo por la ruta vacia.
  beforeEach(() => { get.mockReset() })

  it('🔴 arma la lista de proveedores, que no existía', async () => {
    // Sin ella, la pantalla de cuenta corriente ofrecia el rol "Proveedor" y
    // mostraba la lista de CLIENTES.
    responder(VACIOS)
    const o = await cargarOpciones()
    expect(o.proveedores.map((p) => p.etiqueta)).toEqual(['Gomeria Del Centro'])
  })

  it('la lista de todos los terceros no repite al que tiene dos roles', async () => {
    responder(VACIOS)
    const o = await cargarOpciones()
    expect(o.terceros.map((t) => t.id)).toEqual([1, 2, 3, 4])
    // Control: concatenar clientes + fleteros, que es lo que se hacia antes,
    // SI lo repite. Es la prueba de que la lista nueva arregla algo.
    const concatenado = [...o.clientes, ...o.fleteros].map((t) => t.id)
    expect(concatenado.filter((id) => id === 4).length).toBe(2)
  })

  it('🔴 trae TODAS las filas aunque pasen del tope de la API', async () => {
    // Sobre la instancia del cliente hay 276 terceros activos y el listado
    // devolvia 200: 76 no aparecian en ningun select del sistema, sin ninguna
    // senal. Se pagina de a 1.000, que es el maximo que acepta la API.
    const muchos = Array.from({ length: 1250 }, (_, i) => ({
      id: i + 1, razon_social: `Tercero ${i + 1}`,
      es_cliente: true, es_fletero: false, es_proveedor: false,
    }))
    responder({ ...VACIOS, terceros: muchos })
    const o = await cargarOpciones()
    expect(o.terceros.length).toBe(1250)
    expect(o.terceros[1249].etiqueta).toBe('Tercero 1250')
  })

  it('con una cantidad exacta al tope no se cuelga ni pierde filas', async () => {
    // El caso de borde del paginado: 1.000 justas. La primera pagina viene
    // llena, asi que hay que pedir una vuelta mas -- y esa devuelve vacio.
    const mil = Array.from({ length: 1000 }, (_, i) => ({
      id: i + 1, razon_social: `T${i + 1}`, es_cliente: true,
      es_fletero: false, es_proveedor: false,
    }))
    responder({ ...VACIOS, terceros: mil })
    const o = await cargarOpciones()
    expect(o.terceros.length).toBe(1000)
    const pedidosDeTerceros = get.mock.calls
      .filter((c) => String(c[0]).startsWith('/api/terceros')).length
    expect(pedidosDeTerceros).toBe(2)
  })
})
