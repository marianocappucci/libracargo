// Guard: todo campo donde se elige un cliente ofrece darlo de alta ahí mismo (ADR-071 de libra-ui; ADR-050 de este producto).
//
// 🔴 **Lee los FUENTES, no el DOM**, igual que `selects-buscables.test.ts`: lo que hay que impedir es que **vuelva a nacer** un campo de cliente
// que no se pueda crear, y eso se ve en el JSX. El humano lo pidió el 2026-10-16 (en el mostrador de LibraDesk, un cliente que no estaba cargado
// obligaba a salir de la recepción). El motor vive en `libra-ui/auditoria-de-clientes`; acá se lo corre sobre el `src/` de este producto.
//
// `Elegir` (components/Elegir.tsx) es el envoltorio del producto sobre `SelectBuscable`: el lector no ve por adentro, así que se lo suma a
// `componentes`. Un campo de cliente tiene que ser `SelectCliente`; un *filtro* se exceptúa con «cliente-sin-alta: <motivo>».
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarCamposDeCliente, camposDeClienteEn, describirCamposSinAlta } from 'libra-ui/auditoria-de-clientes'

const SRC = join(process.cwd(), 'src')

describe('los campos de cliente ofrecen el alta', () => {
  const r = auditarCamposDeCliente(SRC, { componentes: ['Elegir'] })

  it('🔴 ningún campo de cliente queda sin alta (ni sin el motivo de por qué no la lleva)', () => {
    expect(describirCamposSinAlta(r.infracciones)).toEqual([])
  })

  it('🔴 el control — el guard midió campos de cliente, y los de alta son SelectCliente', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.campos).toBeGreaterThan(0)
    expect(r.conAlta).toBeGreaterThanOrEqual(4)      // Ordenes, NuevaFactura, FacturarPendientes y la ficha del titular
    expect(r.marcados).toBeGreaterThanOrEqual(2)     // el filtro de órdenes y el de cliente del reporte
  })

  it('🔴 el guard ve a través de `Elegir`: un cliente elegido con él, sin alta ni marca, es una infracción', () => {
    const fuente = `<Elegir id="x-cliente" etiqueta="Cliente" valor={v} opciones={opciones?.clientes ?? []} alCambiar={f} />`
    const hallados = camposDeClienteEn(fuente, 'X.tsx', undefined, ['Elegir'])
    expect(hallados).toHaveLength(1)
    expect(hallados[0].componente).toBe('Elegir')
  })
})
