import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

const { default: CuentaCorriente } = await import('./CuentaCorriente')

const TERCEROS = [
  { id: 1, razon_social: 'Agro Norte', cuit: '30-00000001-0',
    es_cliente: true, es_fletero: false, es_proveedor: false },
  { id: 2, razon_social: 'Fletes SRL', cuit: '30-00000002-0',
    es_cliente: false, es_fletero: true, es_proveedor: false },
  // Proveedor PURO. Es el caso real: los 15 de la instancia del cliente no son
  // ademas cliente ni fletero, asi que si la lista no los contempla, NINGUNO se
  // puede elegir.
  { id: 3, razon_social: 'Gomeria Del Centro', cuit: '30-00000003-0',
    es_cliente: false, es_fletero: false, es_proveedor: true },
  // Dos roles a la vez, sin CUIT cargado.
  { id: 4, razon_social: 'Mixto SA', cuit: null,
    es_cliente: true, es_fletero: true, es_proveedor: false },
  { id: 5, razon_social: 'Agropecuaria Del Sur', cuit: '30-00000005-0',
    es_cliente: true, es_fletero: false, es_proveedor: false },
]

/** Escribe la ruta actual en el DOM, para poder asertar sobre la navegacion
 *  sin mockear `useNavigate` -- lo que probaria que se llamo a una funcion, no
 *  que se llego a algun lado. */
function Donde() {
  const { pathname, search } = useLocation()
  return <span data-testid="donde">{pathname + search}</span>
}

/** El boton «atras» del navegador. */
function Atras() {
  const navegar = useNavigate()
  return <button type="button" onClick={() => navegar(-1)}>atras</button>
}

const donde = () => screen.getByTestId('donde').textContent

function cuentaDe(rol: string, id: number, extra: Record<string, unknown> = {}) {
  return {
    tercero_id: id, rol, saldo: '100.00', saldo_recorriendo: '100.00', coinciden: true,
    movimientos: [], ...extra,
  }
}

/** Contesta los terceros, y la cuenta con lo que arme `cuenta(rol, id)`. */
function responder(cuenta: (rol: string, id: number) => unknown = (rol, id) => cuentaDe(rol, id)) {
  get.mockImplementation((ruta?: string) => {
    if (!ruta) return Promise.resolve([])
    if (ruta.startsWith('/api/terceros')) return Promise.resolve(TERCEROS)
    if (ruta.startsWith('/api/cuentas/')) {
      const [rol, id] = ruta.replace('/api/cuentas/', '').split('?')[0].split('/')
      return Promise.resolve(cuenta(rol, Number(id)))
    }
    return Promise.resolve([])
  })
}

/** Las cuentas que se pidieron, en orden. */
const cuentasPedidas = () =>
  get.mock.calls.map((c) => c[0] as string).filter((r) => r?.startsWith('/api/cuentas/'))

function montar(ruta = '/cuentas') {
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <Donde />
      <Atras />
      <CuentaCorriente />
    </MemoryRouter>,
  )
}

const pestana = (nombre: string) => screen.getByRole('tab', { name: nombre })
/** Radix activa la pestaña con el `mousedown`, no con el `click`. */
const irAPestana = (nombre: string) => fireEvent.mouseDown(pestana(nombre))

/** El campo donde se escribe el tercero: se nombra por el rol de la pestaña. */
const campo = (rotulo: string) => screen.getByRole('combobox', { name: rotulo }) as HTMLInputElement
/** Lo que ofrece la lista abierta: el nombre, y el CUIT pegado a continuación. */
const opciones = () => within(screen.getByRole('listbox')).queryAllByRole('option').map((o) => o.textContent)

/** Espera a que las listas de terceros lleguen: hasta entonces el campo no tiene
 *  nada que ofrecer. Devuelve el campo con la lista cerrada. */
async function conTerceros(rotulo: string) {
  const c = await screen.findByRole('combobox', { name: rotulo })
  await waitFor(() => {
    fireEvent.click(c)
    expect(screen.getByRole('listbox').querySelectorAll('[role="option"]').length).toBeGreaterThan(0)
  })
  fireEvent.keyDown(c, { key: 'Escape' })
  return c as HTMLInputElement
}

describe('CuentaCorriente', () => {
  beforeEach(() => { get.mockReset() })
  afterEach(() => { vi.restoreAllMocks() })

  it('🔴 avisa cuando los dos caminos NO coinciden', async () => {
    // Es la razon de que el endpoint devuelva los dos numeros. Si la pantalla
    // mostrara solo uno, un saldo divergente se veria igual de confiable que
    // uno sano, y esa es justo la situacion en la que NO hay que usarlo.
    responder((rol, id) => cuentaDe(rol, id, { saldo: '100.00', saldo_recorriendo: '90.00', coinciden: false }))
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toContain('NO coinciden')
    // Los dos numeros a la vista, no solo el de la base.
    expect(screen.getByText('$ 100,00')).toBeInTheDocument()
    expect(screen.getByText('$ 90,00')).toBeInTheDocument()
  })

  it('con los dos saldos iguales no aparece ninguna alarma', async () => {
    // El control del test de arriba: sin este, una pantalla que gritara SIEMPRE
    // pasaria igual y la alarma dejaria de significar algo.
    responder()
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('🔴 clickear una fila lleva al documento que la explica', async () => {
    // Es el pedido textual: "que me mande a la orden de carga o a la factura".
    // Antes de esto la pantalla tenia cero forma de llegar: el asiento mostraba
    // el importe y el concepto, y el documento quedaba a mano de nadie.
    responder((rol, id) => cuentaDe(rol, id, {
      movimientos: [{
        movimiento: {
          id: 1, fecha: '2026-08-20', tercero_id: 1, rol: 'cliente',
          concepto: 'Factura A 0001-00000009', descripcion: null,
          debe: '100.00', haber: '0.00',
          orden_id: 7, comprobante_id: 9, movimiento_caja_id: null,
        },
        saldo: '100.00',
      }],
    }))
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(screen.getByText('Factura A 0001-00000009')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Factura A 0001-00000009'))

    // Al comprobante y NO a la orden: el asiento apunta a los dos y gana el
    // documento que explica el importe de la linea.
    await waitFor(() => expect(donde()).toBe('/comprobantes?ver=9'))
  })
})

describe('las pestañas Clientes, Fleteros y Proveedores', () => {
  beforeEach(() => { get.mockReset(); responder() })
  afterEach(() => { vi.restoreAllMocks() })

  it('son tres, abre en Clientes y no queda el selector «Cuenta» de antes', async () => {
    montar()
    await screen.findByRole('tab', { name: 'Clientes' })
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Clientes', 'Fleteros', 'Proveedores'])
    expect(pestana('Clientes')).toHaveAttribute('aria-selected', 'true')
    expect(pestana('Fleteros')).toHaveAttribute('aria-selected', 'false')
    expect(pestana('Proveedores')).toHaveAttribute('aria-selected', 'false')
    expect(screen.queryByLabelText('Cuenta')).toBeNull()
    expect(screen.queryByLabelText('Tercero')).toBeNull()
    // El campo se nombra por el rol y dice qué se busca.
    expect(campo('Cliente')).toHaveAttribute('placeholder', 'Buscar cliente por nombre o CUIT…')
    // Y mientras no hay tercero no se pide ninguna cuenta.
    expect(cuentasPedidas()).toEqual([])
  })

  it('elegir una pestaña cambia el rótulo y el texto del campo, y la escribe en la URL', async () => {
    montar()
    irAPestana('Fleteros')
    await waitFor(() => expect(pestana('Fleteros')).toHaveAttribute('aria-selected', 'true'))
    expect(donde()).toBe('/cuentas?rol=fletero')
    expect(screen.getByText('Fletero', { selector: 'label' })).toBeInTheDocument()
    expect(campo('Fletero')).toHaveAttribute('placeholder', 'Buscar fletero por nombre o CUIT…')

    irAPestana('Proveedores')
    await waitFor(() => expect(pestana('Proveedores')).toHaveAttribute('aria-selected', 'true'))
    expect(donde()).toBe('/cuentas?rol=proveedor')
    expect(campo('Proveedor')).toHaveAttribute('placeholder', 'Buscar proveedor por nombre o CUIT…')
  })

  it('🔴 cada pestaña ofrece su propia lista, no la del rol de al lado', async () => {
    // Decia `rol === 'fletero' ? fleteros : clientes`, asi que "Proveedor"
    // mostraba la lista de CLIENTES. Con los 15 proveedores reales -- que son
    // proveedor-puro -- eso dejaba su cuenta corriente inalcanzable, y sus
    // 3.347 movimientos migrados sin forma de abrirse.
    montar()
    const nombres = async (pest: string, rotulo: string) => {
      irAPestana(pest)
      const c = await conTerceros(rotulo)
      fireEvent.click(c)
      const lista = opciones().map((o) => o?.replace(/30-0000000\d-0$/, ''))
      fireEvent.keyDown(c, { key: 'Escape' })
      return lista
    }
    expect(await nombres('Clientes', 'Cliente')).toEqual(['Agro Norte', 'Mixto SA', 'Agropecuaria Del Sur'])
    expect(await nombres('Fleteros', 'Fletero')).toEqual(['Fletes SRL', 'Mixto SA'])
    expect(await nombres('Proveedores', 'Proveedor')).toEqual(['Gomeria Del Centro'])
  })

  it('cambiar de pestaña descarta el tercero y la cuenta: es de un rol y no del otro', async () => {
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
    expect(campo('Cliente')).toHaveValue('Agro Norte')

    irAPestana('Fleteros')
    await waitFor(() => expect(donde()).toBe('/cuentas?rol=fletero'))
    expect(campo('Fletero')).toHaveValue('')
    expect(screen.queryByText('$ 100,00')).toBeNull()
    expect(screen.queryByText('Imprimir')).toBeNull()
    expect(screen.getByText('Buscá y elegí un fletero.')).toBeInTheDocument()
    // No se pidio la cuenta del fletero 1: el tercero no viajo de una pestaña a la otra.
    expect(cuentasPedidas()).toEqual(['/api/cuentas/cliente/1'])
  })

  it('🔑 cambiar de pestaña empuja el historial: atrás vuelve a la pestaña y a la cuenta de antes', async () => {
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))

    irAPestana('Proveedores')
    await waitFor(() => expect(donde()).toBe('/cuentas?rol=proveedor'))

    fireEvent.click(screen.getByText('atras'))
    await waitFor(() => expect(donde()).toBe('/cuentas?rol=cliente&tercero=1'))
    expect(pestana('Clientes')).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
    expect(campo('Cliente')).toHaveValue('Agro Norte')
  })

  it('tocar la pestaña que ya está activa no cambia nada', async () => {
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(campo('Cliente')).toHaveValue('Agro Norte'))
    irAPestana('Clientes')
    expect(donde()).toBe('/cuentas?rol=cliente&tercero=1')
  })

  it('la fecha «Saldo al» viaja en el pedido y sobrevive al cambio de pestaña', async () => {
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(cuentasPedidas()).toEqual(['/api/cuentas/cliente/1']))
    fireEvent.change(screen.getByLabelText('Saldo al'), { target: { value: '2026-09-30' } })
    await waitFor(() => expect(cuentasPedidas()).toContain('/api/cuentas/cliente/1?hasta=2026-09-30'))

    irAPestana('Fleteros')
    await waitFor(() => expect(pestana('Fleteros')).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByLabelText('Saldo al')).toHaveValue('2026-09-30')
  })
})

describe('los enlaces a una cuenta', () => {
  beforeEach(() => { get.mockReset(); responder() })
  afterEach(() => { vi.restoreAllMocks() })

  it('🔑 ?rol=fletero&tercero=2 abre la pestaña Fleteros con ese fletero y su cuenta', async () => {
    // Es lo que escriben el tablero y los reportes de saldos (`irA.cuenta`).
    montar('/cuentas?rol=fletero&tercero=2')
    await waitFor(() => expect(pestana('Fleteros')).toHaveAttribute('aria-selected', 'true'))
    await waitFor(() => expect(campo('Fletero')).toHaveValue('Fletes SRL'))
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
    expect(cuentasPedidas()).toEqual(['/api/cuentas/fletero/2'])
    expect(donde()).toBe('/cuentas?rol=fletero&tercero=2')
  })

  it('🔴 un proveedor puro se abre por su enlace', async () => {
    montar('/cuentas?rol=proveedor&tercero=3')
    await waitFor(() => expect(campo('Proveedor')).toHaveValue('Gomeria Del Centro'))
    expect(pestana('Proveedores')).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(cuentasPedidas()).toEqual(['/api/cuentas/proveedor/3']))
  })

  it('sin rol (el enlace de caja) se abre la primera cuenta que el tercero tenga, y se pide una sola', async () => {
    // Desde caja el movimiento guarda el tercero y no la cuenta (`irA.cuentaDe`).
    const abrirY = async (ruta: string, esperada: string, rotulo: string, nombre: string) => {
      const m = montar(ruta)
      await waitFor(() => expect(pestana(esperada)).toHaveAttribute('aria-selected', 'true'))
      await waitFor(() => expect(campo(rotulo)).toHaveValue(nombre))
      await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
      const pedidas = cuentasPedidas()
      m.unmount()
      get.mockClear()
      return pedidas
    }
    expect(await abrirY('/cuentas?tercero=3', 'Proveedores', 'Proveedor', 'Gomeria Del Centro'))
      .toEqual(['/api/cuentas/proveedor/3'])
    expect(await abrirY('/cuentas?tercero=2', 'Fleteros', 'Fletero', 'Fletes SRL'))
      .toEqual(['/api/cuentas/fletero/2'])
    // Cliente y fletero a la vez: gana cliente, el orden de siempre.
    expect(await abrirY('/cuentas?tercero=4', 'Clientes', 'Cliente', 'Mixto SA'))
      .toEqual(['/api/cuentas/cliente/4'])
  })

  it('un rol que no es ninguno de los tres se trata como si faltara', async () => {
    const m = montar('/cuentas?rol=cualquiera&tercero=3')
    await waitFor(() => expect(pestana('Proveedores')).toHaveAttribute('aria-selected', 'true'))
    m.unmount()

    montar('/cuentas?rol=cualquiera')
    expect(await screen.findByRole('tab', { name: 'Clientes' })).toHaveAttribute('aria-selected', 'true')
  })

  it('un tercero que no es un número no pide ninguna cuenta', async () => {
    montar('/cuentas?rol=cliente&tercero=abc')
    await conTerceros('Cliente')
    expect(cuentasPedidas()).toEqual([])
    expect(campo('Cliente')).toHaveValue('')
  })
})

describe('el campo donde se escribe el tercero', () => {
  beforeEach(() => { get.mockReset(); responder() })
  afterEach(() => { vi.restoreAllMocks() })

  it('🔑 es un campo de texto aunque la lista sea corta: se busca por letras siempre', async () => {
    // `Elegir` sólo ponia buscador desde 12 opciones; con 3 clientes habia un
    // `<select>` nativo y nada que escribir.
    montar()
    const c = await conTerceros('Cliente')
    expect(c.tagName).toBe('INPUT')
  })

  it('escribir filtra la lista, por nombre y sin importar mayúsculas ni acentos', async () => {
    montar()
    const c = await conTerceros('Cliente')
    fireEvent.change(c, { target: { value: 'AGRO' } })
    expect(opciones().map((o) => o?.replace(/30-0000000\d-0$/, ''))).toEqual(['Agro Norte', 'Agropecuaria Del Sur'])

    fireEvent.change(c, { target: { value: 'agropecuaria sur' } })
    expect(opciones()).toHaveLength(1)
  })

  it('también por CUIT, que se ve al lado del nombre', async () => {
    montar()
    const c = await conTerceros('Cliente')
    fireEvent.change(c, { target: { value: '00000005' } })
    expect(opciones()).toEqual(['Agropecuaria Del Sur30-00000005-0'])
    // Un tercero sin CUIT se ofrece igual, sólo con el nombre.
    fireEvent.change(c, { target: { value: 'mixto' } })
    expect(opciones()).toEqual(['Mixto SA'])
  })

  it('sólo busca entre los de la pestaña: un fletero no aparece en Clientes', async () => {
    montar()
    const c = await conTerceros('Cliente')
    fireEvent.change(c, { target: { value: 'fletes' } })
    expect(screen.getByText('No hay ninguno con ese nombre o CUIT.')).toBeInTheDocument()
  })

  it('elegir una opción carga la cuenta y deja el tercero en la URL', async () => {
    montar()
    const c = await conTerceros('Cliente')
    fireEvent.change(c, { target: { value: 'norte' } })
    fireEvent.click(screen.getByRole('option', { name: /Agro Norte/ }))

    await waitFor(() => expect(donde()).toBe('/cuentas?rol=cliente&tercero=1'))
    expect(c).toHaveValue('Agro Norte')
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))
    expect(cuentasPedidas()).toEqual(['/api/cuentas/cliente/1'])
  })

  it('escribir y Enter elige la primera coincidencia, sin tocar el mouse', async () => {
    montar('/cuentas?rol=proveedor')
    const c = await conTerceros('Proveedor')
    fireEvent.change(c, { target: { value: 'gomeria' } })
    fireEvent.keyDown(c, { key: 'Enter' })

    await waitFor(() => expect(donde()).toBe('/cuentas?rol=proveedor&tercero=3'))
    await waitFor(() => expect(cuentasPedidas()).toEqual(['/api/cuentas/proveedor/3']))
  })

  it('elegir reemplaza la entrada del historial: atrás no deshace la búsqueda', async () => {
    // Con una sola entrada, `-1` no tiene adónde ir. Si elegir empujara una
    // entrada, atrás volvería a `/cuentas` y la URL cambiaría.
    montar()
    const c = await conTerceros('Cliente')
    fireEvent.change(c, { target: { value: 'norte' } })
    fireEvent.click(screen.getByRole('option', { name: /Agro Norte/ }))
    await waitFor(() => expect(donde()).toBe('/cuentas?rol=cliente&tercero=1'))

    fireEvent.click(screen.getByText('atras'))
    expect(donde()).toBe('/cuentas?rol=cliente&tercero=1')
  })

  it('la × quita el tercero: sin cuenta y sin botón de imprimir', async () => {
    montar('/cuentas?rol=cliente&tercero=1')
    await waitFor(() => expect(screen.getAllByText('$ 100,00').length).toBe(2))

    fireEvent.click(screen.getByRole('button', { name: 'Quitar la selección' }))
    await waitFor(() => expect(donde()).toBe('/cuentas?rol=cliente'))
    expect(campo('Cliente')).toHaveValue('')
    expect(screen.queryByText('$ 100,00')).toBeNull()
    expect(screen.queryByText('Imprimir')).toBeNull()
  })
})

describe('imprimir la cuenta', () => {
  beforeEach(() => { get.mockReset(); responder() })
  afterEach(() => { vi.restoreAllMocks() })

  it('el botón aparece con una cuenta a la vista y la hoja lleva el tercero, el rol y los saldos', async () => {
    // Lo que importa es lo que hay en el DOM **en el momento de imprimir**: el navegador fotografia eso.
    let hoja = ''
    const imprimir = vi.spyOn(window, 'print').mockImplementation(() => {
      hoja = document.getElementById('hoja-impresa')?.textContent ?? ''
    })
    montar('/cuentas?rol=fletero&tercero=2')
    fireEvent.click(await screen.findByText('Imprimir'))

    await waitFor(() => expect(imprimir).toHaveBeenCalled())
    expect(hoja).toContain('Cuenta corriente')
    expect(hoja).toContain('Fletes SRL · cuenta fletero')
    expect(hoja).toContain('Saldo')
    expect(hoja).toContain('Coinciden')
    await waitFor(() => expect(document.getElementById('hoja-impresa')).toBeNull())
  })

  it('con «Saldo al» la hoja lo dice', async () => {
    let hoja = ''
    vi.spyOn(window, 'print').mockImplementation(() => {
      hoja = document.getElementById('hoja-impresa')?.textContent ?? ''
    })
    montar('/cuentas?rol=cliente&tercero=1')
    await screen.findByText('Imprimir')
    fireEvent.change(screen.getByLabelText('Saldo al'), { target: { value: '2026-09-30' } })
    await waitFor(() => expect(cuentasPedidas()).toContain('/api/cuentas/cliente/1?hasta=2026-09-30'))
    fireEvent.click(await screen.findByText('Imprimir'))

    await waitFor(() => expect(hoja).toContain('Agro Norte · cuenta cliente · al 2026-09-30'))
  })

  it('sin cuenta elegida no hay botón', async () => {
    montar()
    await screen.findByRole('tab', { name: 'Clientes' })
    expect(screen.queryByText('Imprimir')).toBeNull()
  })
})
