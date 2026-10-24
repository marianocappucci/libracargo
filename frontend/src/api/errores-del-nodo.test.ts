/** Los 409 del nodo se leen bien (libra-ui ADR-094, punto 5; el backend es ADR-056): `solo_en_el_nodo` en la web con un nodo vinculado,
 *  `solo_en_el_central` en el nodo y `sin_conexion`. Llegan como `{detail: {codigo, mensaje}}` y la pantalla tiene que mostrar el
 *  `mensaje`, no «[object Object]» ni «Conflict».
 *
 *  A diferencia del resto de los tests, acá NO se mockea `libra-ui/api-client`: se usa el real con un `fetch` falso, que es lo que prueba
 *  que el kit aplana el `detail` y que `mensajeDeError` (el del producto) lo muestra. */
import { api, ApiError } from 'libra-ui/api-client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mensajeDeError } from '@/components/AbmMaestro'

function responder(status: number, cuerpo: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status < 400, status, statusText: 'Conflict',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(cuerpo),
  }))
}

afterEach(() => vi.unstubAllGlobals())

const CASOS = [
  ['solo_en_el_nodo', 'Esta instancia opera desde la oficina con su nodo: escribí desde la versión de escritorio.'],
  ['solo_en_el_central', 'Esto lo maneja el central: hacelo desde la versión web.'],
  ['sin_conexion', 'Sin conexión: probá de nuevo cuando vuelva internet.'],
] as const

describe('los 409 del nodo', () => {
  for (const [codigo, mensaje] of CASOS) {
    it(`🔴 el 409 \`${codigo}\` se lee con su mensaje`, async () => {
      responder(409, { detail: { codigo, mensaje } })
      const error: ApiError = await api.post('/api/ordenes', {}).catch((e: ApiError) => e) as ApiError
      expect(error).toBeInstanceOf(ApiError)
      expect(error.status).toBe(409)
      expect(mensajeDeError(error)).toBe(mensaje)
      // El código sigue disponible para quien quiera distinguirlo.
      expect((error.detailData as { codigo: string }).codigo).toBe(codigo)
    })
  }

  it('el 202 `en_cola` no es un error: `api.post` lo devuelve como cualquier 2xx', async () => {
    const cuerpo = { codigo: 'en_cola', mensaje: 'La factura queda en cola.', pedido_id: 4, estado: 'esperando', motivo: '' }
    responder(202, cuerpo)
    await expect(api.post('/api/comprobantes/directa', {})).resolves.toEqual(cuerpo)
  })
})
