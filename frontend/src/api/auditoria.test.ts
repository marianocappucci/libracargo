import { describe, expect, it, vi } from 'vitest'

vi.mock('libra-ui/api-client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { describirCambio } = await import('./auditoria')

type Registro = Parameters<typeof describirCambio>[0]

function registro(extra: Partial<Registro>): Registro {
  return {
    id: 1, ts: '2026-08-19T10:00:00-03:00', usuario_id: 1, usuario_nombre: 'admin',
    entidad: 'orden_carga', entidad_id: 7, accion: 'modificacion',
    datos_antes: null, datos_despues: null, ...extra,
  } as Registro
}

describe('describirCambio', () => {
  it('una modificación se lee como "de esto a esto"', () => {
    expect(describirCambio(registro({
      datos_antes: { tarifa: '1000.00' }, datos_despues: { tarifa: '1200.00' },
    }))).toBe('tarifa: 1000.00 → 1200.00')
  })

  it('un alta muestra sólo lo que quedó', () => {
    expect(describirCambio(registro({
      accion: 'alta', datos_despues: { nombre: 'Suipacha' },
    }))).toBe('nombre: Suipacha')
  })

  it('mira las claves de los DOS lados', () => {
    // En una baja hay campos que existen antes y no después. Leyendo un solo
    // lado se pierden, y el log diria menos de lo que sabe.
    expect(describirCambio(registro({
      accion: 'baja',
      datos_antes: { activo: true, motivo: 'x' },
      datos_despues: { activo: false },
    }))).toBe('activo: true → false · motivo: x →')
  })

  it('un registro migrado, sin detalle, no inventa nada', () => {
    // Los 15.884 de `sucesos` traen quien y cuando pero no que cambio: la
    // columna queda vacia, y eso es un dato.
    expect(describirCambio(registro({ datos_antes: null, datos_despues: null }))).toBe('')
  })
})
