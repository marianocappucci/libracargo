/** Entidades (ADR-040): Clientes, Fleteros, Choferes y Proveedores en una entrada del menú.
 *
 *  Lo que se prueba es lo que la pantalla decide: las cuatro pestañas y que vayan en la URL, que cada una liste su rol, que
 *  el alta marque el rol de donde se está, que un CUIT repetido ofrezca sumar el rol en vez de cargar otra vez, la ficha
 *  del fletero con sus choferes y vehículos, y que Configuración ya no tenga Terceros ni Choferes (y los enlaces viejos
 *  lleguen acá).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { elegirEnBuscable } from '@/test/buscable'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  // Misma firma que la real: `ApiError(status, detail, detailData)`. Con un `detail` objeto, la real deja en `detail` su
  // `mensaje` y el objeto entero en `detailData`.
  class ApiError extends Error {
    status: number
    detail: string
    detailData?: unknown
    constructor(status: number, detail: string, detailData?: unknown) {
      super(detail); this.status = status; this.detail = detail; this.detailData = detailData
    }
  }
  return { ApiError, api: { get, post, put, del: vi.fn(), postForm: vi.fn() } }
})
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'admin', name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: Entidades } = await import('./Entidades')
const { Configuracion } = await import('./Configuracion')
const { default: Vehiculos } = await import('./Vehiculos')
const { ApiError } = await import('libra-ui/api-client')

type Rol = 'cliente' | 'fletero' | 'proveedor'
const entidad = (id: number, razon_social: string, roles: Rol[], extra: Record<string, unknown> = {}) => ({
  id, razon_social, cuit: null, condicion_iva: 'responsable_inscripto', localidad: null, contacto: null, activo: true,
  es_cliente: roles.includes('cliente'), es_fletero: roles.includes('fletero'), es_proveedor: roles.includes('proveedor'),
  ...extra,
})
const ENTIDADES = [
  entidad(1, 'Agro Norte SA', ['cliente']),
  entidad(2, 'Transportes del Sur', ['fletero', 'proveedor'], { cuit: '30711111114' }),
  entidad(3, 'Ferretería Central', ['proveedor']),
]
const CHOFERES = [
  { id: 11, nombre: 'Juan Pérez', dni: '20111222', cuit: '20123456786', telefono: null, fletero_id: 2, observaciones: null, activo: true },
  { id: 12, nombre: 'Ana Gómez', dni: null, cuit: null, telefono: '3415550000', fletero_id: null, observaciones: null, activo: true },
]
const VEHICULOS = [
  { id: 21, patente_chasis: 'AB123CD', patente_acoplado: 'EF456GH', fletero_id: 2, observaciones: null, activo: true },
]

function responder() {
  get.mockImplementation((ruta: string) => {
    const porRol = ruta.match(/^\/api\/terceros\/rol\/(\w+)\?solo_activos=false$/)
    if (porRol) return Promise.resolve(ENTIDADES.filter((e) => e[`es_${porRol[1]}` as 'es_cliente']))
    if (ruta.startsWith('/api/configuracion')) return Promise.resolve({ razon_social: 'Transportes del Plata' })
    if (ruta === '/api/choferes') return Promise.resolve(CHOFERES)
    if (ruta === '/api/choferes?fletero_id=2') return Promise.resolve(CHOFERES.filter((c) => c.fletero_id === 2))
    if (ruta === '/api/vehiculos?fletero_id=2') return Promise.resolve(VEHICULOS)
    return Promise.resolve([])
  })
}

function Ubicacion() {
  const { pathname, search } = useLocation()
  return <p data-testid="ubicacion">{pathname + search}</p>
}

function abrir(url = '/entidades') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/entidades" element={<><Entidades /><Ubicacion /></>} />
        <Route path="/configuracion" element={<Configuracion />} />
        <Route path="/vehiculos" element={<><Vehiculos /><Ubicacion /></>} />
      </Routes>
    </MemoryRouter>,
  )
}
const ubicacion = () => screen.getByTestId('ubicacion').textContent

const duplicado = (existente: { id: number; razon_social: string; roles: Rol[] }) =>
  new ApiError(409, `El CUIT 30-71111111-4 ya es de «${existente.razon_social}». Sumale el rol en vez de cargarla de nuevo.`, {
    mensaje: `El CUIT 30-71111111-4 ya es de «${existente.razon_social}». Sumale el rol en vez de cargarla de nuevo.`,
    existente: { activo: true, ...existente },
  })

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset()
  responder()
  // jsdom no trae `matchMedia`, que algunas piezas del kit piden.
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
})

describe('Entidades · pestañas y URL', () => {
  it('tiene Clientes, Fleteros, Choferes y Proveedores, y sin parámetro abre Clientes', async () => {
    abrir()
    const pestanas = await screen.findAllByRole('tab')
    expect(pestanas.map((t) => t.textContent)).toEqual(['Clientes', 'Fleteros', 'Choferes', 'Proveedores'])
    expect(screen.getByRole('tab', { name: 'Clientes' })).toHaveAttribute('data-state', 'active')
    expect(await screen.findByText('Agro Norte SA')).toBeInTheDocument()
  })

  it('🔑 la pestaña va en la URL: elegir Fleteros escribe ?pestana=fleteros, y entrar con ella la abre', async () => {
    abrir()
    await screen.findByText('Agro Norte SA')
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Fleteros' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Fleteros' }))
    await waitFor(() => expect(ubicacion()).toBe('/entidades?pestana=fleteros'))
    expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
  })

  it('entrar con ?pestana=proveedores abre Proveedores; una pestaña desconocida cae en Clientes', async () => {
    const { unmount } = abrir('/entidades?pestana=proveedores')
    expect(await screen.findByText('Ferretería Central')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Proveedores' })).toHaveAttribute('data-state', 'active')
    unmount()
    abrir('/entidades?pestana=cualquier-cosa')
    expect(await screen.findByText('Agro Norte SA')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Clientes' })).toHaveAttribute('data-state', 'active')
  })

  it('cada pestaña lista SU rol: una entidad con dos roles está en las dos', async () => {
    abrir('/entidades?pestana=fleteros')
    expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
    expect(screen.queryByText('Agro Norte SA')).toBeNull()
    expect(screen.queryByText('Ferretería Central')).toBeNull()
    expect(get).toHaveBeenCalledWith('/api/terceros/rol/fletero?solo_activos=false')
  })

  it('la columna Roles muestra los OTROS roles como pastillas, y no el de la pestaña', async () => {
    abrir('/entidades?pestana=fleteros')
    const fila = (await screen.findByText('Transportes del Sur')).closest('tr') as HTMLElement
    expect(within(fila).getByText('Proveedor')).toBeInTheDocument()
    expect(within(fila).queryByText('Fletero')).toBeNull()
    // Y el CUIT se lee con guiones.
    expect(within(fila).getByText('30-71111111-4')).toBeInTheDocument()
  })
})

describe('Entidades · botones en la línea del título', () => {
  /** La fila del título: el contenedor más chico que tiene a la vez el título y el botón. */
  const filaDelTitulo = () => screen.getByRole('heading', { name: 'Entidades' }).parentElement as HTMLElement

  it.each(['clientes', 'fleteros', 'choferes', 'proveedores'])(
    '🔑 en %s el «Nuevo» está en la misma línea que el título «Entidades», no debajo de las pestañas',
    async (pestana) => {
      abrir(`/entidades?pestana=${pestana}`)
      const nuevo = await screen.findByRole('button', { name: 'Nuevo' })
      expect(within(filaDelTitulo()).getByRole('button', { name: 'Nuevo' })).toBe(nuevo)
      // Y las pestañas no lo contienen.
      expect(screen.getByRole('tablist')).not.toContainElement(nuevo)
    })

  it('hay un solo «Nuevo» a la vez, y al cambiar de pestaña el de la anterior se va', async () => {
    abrir()
    await screen.findByRole('button', { name: 'Nuevo' })
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Fleteros' }))
    await screen.findByText('Transportes del Sur')
    expect(screen.getAllByRole('button', { name: 'Nuevo' })).toHaveLength(1)
  })
})

describe('Entidades · alta', () => {
  it('🔑 el alta desde Fleteros marca el rol fletero de entrada, y los otros se tildan en la ficha', async () => {
    post.mockResolvedValue(entidad(9, 'Nueva SRL', ['fletero', 'proveedor']))
    abrir('/entidades?pestana=fleteros')
    await screen.findByText('Transportes del Sur')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByRole('heading', { name: 'Nuevo fletero' })).toBeInTheDocument()
    const roles = within(dialogo).getByRole('group', { name: /Roles/ })
    expect(within(roles).getByLabelText('Fletero')).toBeChecked()
    expect(within(roles).getByLabelText('Cliente')).not.toBeChecked()
    expect(within(roles).getByLabelText('Proveedor')).not.toBeChecked()

    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'Nueva SRL' } })
    fireEvent.click(within(roles).getByLabelText('Proveedor'))
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toBe('/api/terceros')
    expect(post.mock.calls[0][1]).toMatchObject({ razon_social: 'Nueva SRL', es_fletero: true, es_proveedor: true })
    expect(post.mock.calls[0][1].es_cliente).toBeFalsy()
  })

  it('el alta desde Proveedores marca proveedor, no cliente', async () => {
    post.mockResolvedValue(entidad(9, 'X', ['proveedor']))
    abrir('/entidades?pestana=proveedores')
    await screen.findByText('Ferretería Central')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'X' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1]).toMatchObject({ es_proveedor: true })
    expect(post.mock.calls[0][1].es_cliente).toBeFalsy()
  })
})

describe('Entidades · CUIT repetido (409)', () => {
  async function altaRepetida(existente: { id: number; razon_social: string; roles: Rol[] }) {
    post.mockRejectedValue(duplicado(existente))
    abrir('/entidades?pestana=fleteros')
    await screen.findByText('Transportes del Sur')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'Agro Norte' } })
    fireEvent.change(within(dialogo).getByLabelText('CUIT'), { target: { value: '30711111114' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    return dialogo
  }

  it('🔑 muestra el mensaje del servidor dentro del diálogo, no [object Object]', async () => {
    const dialogo = await altaRepetida({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] })
    const alerta = await within(dialogo).findByRole('alert')
    expect(alerta).toHaveTextContent('El CUIT 30-71111111-4 ya es de «Agro Norte SA»')
    expect(alerta).not.toHaveTextContent('[object')
    expect(within(dialogo).getByRole('button', { name: 'Sumarle el rol de fletero' })).toBeInTheDocument()
    expect(within(dialogo).getByRole('button', { name: 'Ver Agro Norte SA' })).toBeInTheDocument()
  })

  it('🔑 «Sumarle el rol de fletero» llama al endpoint, cierra el diálogo, recarga y destaca la fila', async () => {
    post.mockReset()
    post.mockRejectedValueOnce(duplicado({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] }))
    post.mockResolvedValueOnce(entidad(1, 'Agro Norte SA', ['cliente', 'fletero']))
    abrir('/entidades?pestana=fleteros')
    await screen.findByText('Transportes del Sur')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Razón social'), { target: { value: 'Agro Norte' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    const boton = await within(dialogo).findByRole('button', { name: 'Sumarle el rol de fletero' })

    // Al recargar, la entidad ya es fletero y aparece en la pestaña.
    const antes = get.mock.calls.length
    ENTIDADES[0].es_fletero = true
    fireEvent.click(boton)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/terceros/1/roles/fletero'))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(get.mock.calls.length).toBeGreaterThan(antes)
    const fila = (await screen.findByText('Agro Norte SA')).closest('tr') as HTMLElement
    expect(fila.className).toContain('bg-primary/10')
    ENTIDADES[0].es_fletero = false
  })

  it('«Ver …» cierra el diálogo y abre la ficha de la entidad existente, en la pestaña de su rol', async () => {
    const dialogo = await altaRepetida({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] })
    fireEvent.click(await within(dialogo).findByRole('button', { name: 'Ver Agro Norte SA' }))
    await waitFor(() => expect(ubicacion()).toBe('/entidades?pestana=clientes&ver=1'))
    const ficha = await screen.findByRole('dialog')
    expect(within(ficha).getByRole('heading', { name: 'Editar cliente' })).toBeInTheDocument()
    expect(within(ficha).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    // Cerrarla limpia el ?ver= de la URL.
    fireEvent.click(within(ficha).getByText('Cancelar'))
    await waitFor(() => expect(ubicacion()).toBe('/entidades?pestana=clientes'))
  })

  it('si la existente ya tiene el rol sólo se ofrece verla', async () => {
    const dialogo = await altaRepetida({ id: 2, razon_social: 'Transportes del Sur', roles: ['fletero', 'proveedor'] })
    await within(dialogo).findByRole('button', { name: 'Ver Transportes del Sur' })
    expect(within(dialogo).queryByRole('button', { name: /Sumarle el rol/ })).toBeNull()
  })

  it('al EDITAR un CUIT que choca con otra se muestra el mensaje pero no se ofrece sumar el rol', async () => {
    put.mockRejectedValue(duplicado({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] }))
    abrir('/entidades?pestana=fleteros')
    fireEvent.click(await screen.findByText('Transportes del Sur'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('ya es de «Agro Norte SA»')
    expect(within(dialogo).queryByRole('button', { name: /Sumarle el rol/ })).toBeNull()
    expect(within(dialogo).getByRole('button', { name: 'Ver Agro Norte SA' })).toBeInTheDocument()
  })

  it('un error que no es de CUIT se muestra como siempre', async () => {
    post.mockRejectedValue(new ApiError(422, 'el tercero tiene que ser al menos una cosa'))
    abrir('/entidades?pestana=fleteros')
    await screen.findByText('Transportes del Sur')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('al menos una cosa')
    expect(within(dialogo).queryByRole('button', { name: /Sumarle/ })).toBeNull()
  })
})

describe('Entidades · Choferes', () => {
  it('la pestaña lista nombre, CUIT con guiones, DNI, teléfono y fletero', async () => {
    abrir('/entidades?pestana=choferes')
    const fila = (await screen.findByText('Juan Pérez')).closest('tr') as HTMLElement
    expect(within(fila).getByText('20-12345678-6')).toBeInTheDocument()
    expect(within(fila).getByText('20111222')).toBeInTheDocument()
    await waitFor(() => expect(within(fila).getByText('Transportes del Sur')).toBeInTheDocument())
    for (const encabezado of ['Nombre', 'CUIT', 'DNI', 'Teléfono', 'Fletero']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(encabezado) })).toBeInTheDocument()
    }
  })

  it('el fletero del chofer se elige por nombre, no por número', async () => {
    abrir('/entidades?pestana=choferes')
    fireEvent.click(await screen.findByText('Ana Gómez'))
    const dialogo = await screen.findByRole('dialog')
    const campo = await within(dialogo).findByLabelText('Fletero')
    put.mockResolvedValue({})
    // El fletero se busca escribiendo (ADR-039 del kit): el campo es un combobox y las opciones existen con la lista abierta.
    await elegirEnBuscable(campo, 'Transportes del Sur')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][0]).toBe('/api/choferes/12')
    expect(put.mock.calls[0][1].fletero_id).toBe(2)
  })
})

describe('Entidades · ficha del fletero', () => {
  it('🔑 al abrir un fletero se ven sus choferes y sus vehículos, con enlace', async () => {
    abrir('/entidades?pestana=fleteros')
    fireEvent.click(await screen.findByText('Transportes del Sur'))
    const dialogo = await screen.findByRole('dialog')
    const ficha = await within(dialogo).findByRole('region', { name: 'Ficha del fletero' })
    const chofer = await within(ficha).findByRole('link', { name: 'Juan Pérez' })
    expect(chofer).toHaveAttribute('href', '/entidades?pestana=choferes&ver=11')
    expect(within(ficha).getByText(/20-12345678-6/)).toBeInTheDocument()
    const vehiculo = await within(ficha).findByRole('link', { name: 'AB123CD' })
    expect(vehiculo).toHaveAttribute('href', '/vehiculos?ver=21')
    expect(within(ficha).getByText(/Acoplado EF456GH/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/choferes?fletero_id=2')
    expect(get).toHaveBeenCalledWith('/api/vehiculos?fletero_id=2')
  })

  it('un fletero sin choferes ni vehículos lo dice', async () => {
    ENTIDADES.push(entidad(5, 'Fletero Nuevo', ['fletero']))
    get.mockImplementation((ruta: string) => {
      if (ruta.startsWith('/api/terceros/rol/fletero')) return Promise.resolve(ENTIDADES.filter((e) => e.es_fletero))
      return Promise.resolve([])
    })
    abrir('/entidades?pestana=fleteros&ver=5')
    const ficha = await screen.findByRole('region', { name: 'Ficha del fletero' })
    expect(await within(ficha).findByText('Todavía no tiene choferes.')).toBeInTheDocument()
    expect(within(ficha).getByText('Todavía no tiene vehículos.')).toBeInTheDocument()
    ENTIDADES.pop()
  })

  it('?ver= abre la ficha de esa fila al cargar; un cliente no lleva la sección de choferes', async () => {
    abrir('/entidades?pestana=clientes&ver=1')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    expect(within(dialogo).queryByRole('region', { name: 'Ficha del fletero' })).toBeNull()
  })
})

describe('Configuración sin Terceros, Choferes ni Vehículos', () => {
  it('🔑 ya no tiene las pestañas Terceros, Choferes ni Vehículos; quedan las demás', async () => {
    render(<MemoryRouter initialEntries={['/configuracion']}><Configuracion /></MemoryRouter>)
    const pestanas = (await screen.findAllByRole('tab')).map((t) => t.textContent)
    expect(pestanas).not.toContain('Terceros')
    expect(pestanas).not.toContain('Choferes')
    expect(pestanas).not.toContain('Vehículos')
    for (const queda of ['Localidades', 'Tipos de carga', 'Tarifario de referencia']) {
      expect(pestanas).toContain(queda)
    }
  })

  it.each([
    ['/configuracion?seccion=terceros', '/entidades?pestana=clientes'],
    ['/configuracion?seccion=choferes', '/entidades?pestana=choferes'],
    ['/configuracion?seccion=choferes&ver=11', '/entidades?pestana=choferes&ver=11'],
    ['/configuracion?seccion=vehiculos', '/vehiculos'],
    ['/configuracion?seccion=vehiculos&ver=21', '/vehiculos?ver=21'],
  ])('🔴 el enlace viejo %s redirige a %s', async (viejo, nuevo) => {
    abrir(viejo)
    await waitFor(() => expect(ubicacion()).toBe(nuevo))
  })

  it('los demás enlaces de Configuración no se tocan', async () => {
    render(<MemoryRouter initialEntries={['/configuracion?seccion=localidades']}><Configuracion /></MemoryRouter>)
    const pestana = await screen.findByRole('tab', { name: 'Localidades' })
    expect(pestana).toHaveAttribute('data-state', 'active')
  })

  it('Vehículos abre la ficha del ?ver= y muestra el fletero por nombre', async () => {
    get.mockImplementation((ruta: string) => {
      if (ruta === '/api/vehiculos') return Promise.resolve(VEHICULOS)
      if (ruta.startsWith('/api/terceros/rol/fletero')) return Promise.resolve([ENTIDADES[1]])
      return Promise.resolve([])
    })
    abrir('/vehiculos?ver=21')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Patente del chasis')).toHaveValue('AB123CD')
    // Es una pantalla del menú: tiene su título (con el diálogo abierto el resto queda oculto al lector, de ahí `hidden`).
    expect(screen.getByRole('heading', { name: 'Vehículos', hidden: true })).toBeInTheDocument()
  })
})

describe('Entidades · la línea de Carta de porte en la ficha del cliente (ADR-044)', () => {
  const titularDe = (extra: Record<string, unknown>) => ({
    id: 4, cuit: '30111111118', razon_social: 'Agro Norte SA', emite: 'nosotros', activo: true, notas: null,
    delegacion: 'delegado', tercero: { id: 1, razon_social: 'Agro Norte SA' }, tiene_plantilla: false, motivo: null,
    ...extra,
  })
  /** El servidor contesta `null` si el cliente no es titular. */
  function conTitular(valor: unknown) {
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta: string) => ruta === '/api/cartas-porte/titulares/de-tercero/1'
      ? Promise.resolve(valor) : base(ruta))
  }

  it.each([
    [{ delegacion: 'delegado' }, 'Carta de porte: delegó a nosotros ✓'],
    [{ delegacion: 'pendiente' }, 'Carta de porte: pendiente'],
    [{ emite: 'titular', delegacion: 'delegado' }, 'Carta de porte: emite él · consulta habilitada ✓'],
    [{ emite: 'titular', delegacion: 'pendiente' }, 'Carta de porte: emite él · falta que delegue'],
  ])('🔑 un cliente titular dice cómo está (%o) y lleva a su titular', async (extra, texto) => {
    conTitular(titularDe(extra))
    abrir('/entidades?pestana=clientes&ver=1')
    const dialogo = await screen.findByRole('dialog')
    expect(await within(dialogo).findByText(new RegExp(texto))).toBeInTheDocument()
    expect(within(dialogo).getByRole('link', { name: 'Ver titular' }))
      .toHaveAttribute('href', '/cartas-porte?pestana=titulares&ver=4')
    expect(get).toHaveBeenCalledWith('/api/cartas-porte/titulares/de-tercero/1')
  })

  it('un cliente que no es titular no muestra nada', async () => {
    conTitular(null)
    abrir('/entidades?pestana=clientes&ver=1')
    const dialogo = await screen.findByRole('dialog')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/cartas-porte/titulares/de-tercero/1'))
    expect(within(dialogo).queryByText(/Carta de porte:/)).toBeNull()
  })

  it('si la consulta falla, la ficha sigue sin la línea', async () => {
    const base = get.getMockImplementation()!
    get.mockImplementation((ruta: string) => ruta.startsWith('/api/cartas-porte/')
      ? Promise.reject(new Error('sin red')) : base(ruta))
    abrir('/entidades?pestana=clientes&ver=1')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    expect(within(dialogo).queryByText(/Carta de porte:/)).toBeNull()
  })

  it('un fletero o un proveedor no la piden: la línea es de los clientes', async () => {
    abrir('/entidades?pestana=proveedores&ver=3')
    await screen.findByRole('dialog')
    expect(get.mock.calls.some(([r]) => String(r).includes('/titulares/de-tercero/'))).toBe(false)
  })
})
