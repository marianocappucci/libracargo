/** Transporte (ADR-045; antes «Entidades», ADR-040): Fleteros, Choferes y Vehículos en una entrada del menú.
 *
 *  Lo que se prueba es lo que la pantalla decide: las tres pestañas y que vayan en la URL, que cada una liste lo suyo, que el alta
 *  marque el rol de fletero, que un CUIT repetido ofrezca sumar el rol en vez de cargar otra vez (y «Ver …» lleve a la pantalla del
 *  rol de la entidad existente), y la ficha del fletero con sus choferes y vehículos. Clientes y Proveedores ya no son pestañas de
 *  acá: tienen sus tests (`Clientes.test.tsx`, `Proveedores.test.tsx`), y los enlaces viejos, el suyo
 *  (`test/menu-y-enlaces-de-transporte.test.tsx`).
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ENTIDADES, VEHICULOS, cuitDuplicado, entidad, responder, simularMatchMedia } from '@/test/entidades-de-prueba'
import type { Rol } from '@/test/entidades-de-prueba'
import { elegirEnBuscable } from '@/test/buscable'
import { CLAVE_DE_PESTANA_DE_TRANSPORTE } from '@/pestana-recordada'

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

const { default: Transporte } = await import('./Transporte')
const { default: Clientes } = await import('./Clientes')
const { ApiError } = await import('libra-ui/api-client')

function Ubicacion() {
  const { pathname, search } = useLocation()
  return <p data-testid="ubicacion">{pathname + search}</p>
}

function abrir(url = '/transporte') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/transporte" element={<><Transporte /><Ubicacion /></>} />
        {/* A donde lleva el «Ver …» de un CUIT repetido que es de un cliente. */}
        <Route path="/clientes" element={<><Clientes /><Ubicacion /></>} />
      </Routes>
    </MemoryRouter>,
  )
}
const ubicacion = () => screen.getByTestId('ubicacion').textContent

const duplicado = (existente: { id: number; razon_social: string; roles: Rol[] }) => cuitDuplicado(ApiError, existente)

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset()
  responder(get)
  simularMatchMedia()
  // La pestaña recordada vive en el `localStorage` del navegador, que jsdom comparte entre los tests de un archivo.
  window.localStorage.clear()
})

afterEach(() => { vi.restoreAllMocks() })

describe('Transporte · pestañas y URL', () => {
  it('🔴 tiene SÓLO Fleteros, Choferes y Vehículos —en ese orden—, y sin parámetro abre Fleteros', async () => {
    abrir()
    const pestanas = await screen.findAllByRole('tab')
    expect(pestanas.map((t) => t.textContent)).toEqual(['Fleteros', 'Choferes', 'Vehículos'])
    expect(screen.getByRole('tab', { name: 'Fleteros' })).toHaveAttribute('data-state', 'active')
    expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
    // Clientes y Proveedores se fueron al menú principal: ni pestaña, ni filas de esos roles.
    expect(screen.queryByRole('tab', { name: 'Clientes' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Proveedores' })).toBeNull()
    expect(screen.queryByText('Agro Norte SA')).toBeNull()
  })

  it('el título de la pantalla es «Transporte», no «Entidades»', async () => {
    abrir()
    expect(await screen.findByRole('heading', { name: 'Transporte' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Entidades' })).toBeNull()
  })

  it('🔑 la pestaña va en la URL: elegir Choferes escribe ?pestana=choferes, y entrar con ella la abre', async () => {
    const { unmount } = abrir()
    await screen.findByText('Transportes del Sur')
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Choferes' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Choferes' }))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=choferes'))
    expect(await screen.findByText('Juan Pérez')).toBeInTheDocument()
    unmount()

    abrir('/transporte?pestana=choferes')
    expect(await screen.findByText('Ana Gómez')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Choferes' })).toHaveAttribute('data-state', 'active')
  })

  it('🔑 Vehículos también va en la URL: ?pestana=vehiculos la abre, y elegirla la escribe', async () => {
    const { unmount } = abrir('/transporte?pestana=vehiculos')
    expect(await screen.findByText('AB123CD')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vehículos' })).toHaveAttribute('data-state', 'active')
    expect(get).toHaveBeenCalledWith('/api/vehiculos')
    unmount()

    abrir()
    await screen.findByText('Transportes del Sur')
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Vehículos' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Vehículos' }))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=vehiculos'))
    expect(await screen.findByText('AB123CD')).toBeInTheDocument()
  })

  it('una pestaña desconocida —también las que ya no existen, como clientes o proveedores— cae en Fleteros', async () => {
    for (const pestana of ['cualquier-cosa', 'clientes', 'proveedores']) {
      const { unmount } = abrir(`/transporte?pestana=${pestana}`)
      expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Fleteros' })).toHaveAttribute('data-state', 'active')
      unmount()
    }
  })

  it('Fleteros lista SU rol: una entidad con dos roles está en las dos pantallas', async () => {
    abrir('/transporte?pestana=fleteros')
    expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
    expect(screen.queryByText('Agro Norte SA')).toBeNull()
    expect(screen.queryByText('Ferretería Central')).toBeNull()
    expect(get).toHaveBeenCalledWith('/api/terceros/rol/fletero?solo_activos=false')
  })

  it('la columna Roles muestra los OTROS roles como pastillas, y no el de la pestaña', async () => {
    abrir('/transporte?pestana=fleteros')
    const fila = (await screen.findByText('Transportes del Sur')).closest('tr') as HTMLElement
    expect(within(fila).getByText('Proveedor')).toBeInTheDocument()
    expect(within(fila).queryByText('Fletero')).toBeNull()
    // Y el CUIT se lee con guiones.
    expect(within(fila).getByText('30-71111111-4')).toBeInTheDocument()
  })
})

describe('Transporte · recuerda la última pestaña', () => {
  const recordada = () => window.localStorage.getItem(CLAVE_DE_PESTANA_DE_TRANSPORTE)

  it('🔑 sin ?pestana= (el menú) abre la última que se usó, y completa la URL con ella', async () => {
    window.localStorage.setItem(CLAVE_DE_PESTANA_DE_TRANSPORTE, 'vehiculos')
    abrir('/transporte')
    expect(await screen.findByText('AB123CD')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Vehículos' })).toHaveAttribute('data-state', 'active')
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=vehiculos'))
  })

  it('🔴 con ?pestana= manda la URL, aunque haya otra recordada; y pasa a ser la recordada', async () => {
    window.localStorage.setItem(CLAVE_DE_PESTANA_DE_TRANSPORTE, 'vehiculos')
    abrir('/transporte?pestana=choferes')
    expect(await screen.findByText('Juan Pérez')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Choferes' })).toHaveAttribute('data-state', 'active')
    expect(ubicacion()).toBe('/transporte?pestana=choferes')
    await waitFor(() => expect(recordada()).toBe('choferes'))
  })

  it('🔑 elegir una pestaña la recuerda: la próxima vez que se entra sin ella, abre esa', async () => {
    const { unmount } = abrir()
    await screen.findByText('Transportes del Sur')
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Choferes' }))
    await screen.findByText('Juan Pérez')
    await waitFor(() => expect(recordada()).toBe('choferes'))
    unmount()

    abrir('/transporte')
    expect(await screen.findByText('Ana Gómez')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Choferes' })).toHaveAttribute('data-state', 'active')
  })

  it('sin nada guardado abre Fleteros', async () => {
    abrir('/transporte')
    expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Fleteros' })).toHaveAttribute('data-state', 'active')
  })

  it.each(['clientes', 'proveedores', 'cualquier-cosa', ''])(
    '🔴 un valor guardado que no es una pestaña (%j) cae en Fleteros', async (basura) => {
      window.localStorage.setItem(CLAVE_DE_PESTANA_DE_TRANSPORTE, basura)
      abrir('/transporte')
      expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Fleteros' })).toHaveAttribute('data-state', 'active')
      await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=fleteros'))
    })

  it('🔴 si el almacenamiento tira error al leer y al escribir, abre Fleteros y la pantalla anda igual', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage bloqueado') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage bloqueado') })
    abrir('/transporte')
    expect(await screen.findByText('Transportes del Sur')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Fleteros' })).toHaveAttribute('data-state', 'active')
    // Y cambiar de pestaña sigue andando, con la URL como fuente de verdad.
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Choferes' }))
    expect(await screen.findByText('Juan Pérez')).toBeInTheDocument()
    expect(ubicacion()).toBe('/transporte?pestana=choferes')
  })

  it('un ?ver= sin pestaña no es de la recordada: cae en Fleteros y conserva el ver', async () => {
    window.localStorage.setItem(CLAVE_DE_PESTANA_DE_TRANSPORTE, 'vehiculos')
    abrir('/transporte?ver=2')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Transportes del Sur')
    await waitFor(() => expect(ubicacion()).toBe('/transporte?ver=2&pestana=fleteros'))
  })
})

describe('Transporte · botones en la línea del título', () => {
  /** La fila del título: el contenedor más chico que tiene a la vez el título y el botón. */
  const filaDelTitulo = () => screen.getByRole('heading', { name: 'Transporte' }).parentElement as HTMLElement

  it.each(['fleteros', 'choferes', 'vehiculos'])(
    '🔑 en %s el «Nuevo» está en la misma línea que el título «Transporte», no debajo de las pestañas',
    async (pestana) => {
      abrir(`/transporte?pestana=${pestana}`)
      const nuevo = await screen.findByRole('button', { name: 'Nuevo' })
      expect(within(filaDelTitulo()).getByRole('button', { name: 'Nuevo' })).toBe(nuevo)
      // Y las pestañas no lo contienen.
      expect(screen.getByRole('tablist')).not.toContainElement(nuevo)
    })

  it('hay un solo «Nuevo» a la vez, y al cambiar de pestaña el de la anterior se va', async () => {
    abrir()
    await screen.findByRole('button', { name: 'Nuevo' })
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Choferes' }))
    await screen.findByText('Juan Pérez')
    expect(screen.getAllByRole('button', { name: 'Nuevo' })).toHaveLength(1)
  })
})

describe('Transporte · alta', () => {
  it('🔑 el alta desde Fleteros marca el rol fletero de entrada, y los otros se tildan en la ficha', async () => {
    post.mockResolvedValue(entidad(9, 'Nueva SRL', ['fletero', 'proveedor']))
    abrir('/transporte?pestana=fleteros')
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
})

describe('Transporte · CUIT repetido (409)', () => {
  async function altaRepetida(existente: { id: number; razon_social: string; roles: Rol[] }) {
    post.mockRejectedValue(duplicado(existente))
    abrir('/transporte?pestana=fleteros')
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
    abrir('/transporte?pestana=fleteros')
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

  it('🔑 «Ver …» de un cliente cierra el diálogo y abre su ficha en Clientes (/clientes?ver=), no en una pestaña de Transporte', async () => {
    const dialogo = await altaRepetida({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] })
    fireEvent.click(await within(dialogo).findByRole('button', { name: 'Ver Agro Norte SA' }))
    await waitFor(() => expect(ubicacion()).toBe('/clientes?ver=1'))
    const ficha = await screen.findByRole('dialog')
    expect(within(ficha).getByRole('heading', { name: 'Editar cliente' })).toBeInTheDocument()
    expect(within(ficha).getByLabelText('Razón social')).toHaveValue('Agro Norte SA')
    // Cerrarla limpia el ?ver= de la URL.
    fireEvent.click(within(ficha).getByText('Cancelar'))
    await waitFor(() => expect(ubicacion()).toBe('/clientes'))
  })

  it('«Ver …» de otro fletero abre su ficha en la pestaña Fleteros de Transporte', async () => {
    const dialogo = await altaRepetida({ id: 2, razon_social: 'Transportes del Sur', roles: ['fletero', 'proveedor'] })
    fireEvent.click(await within(dialogo).findByRole('button', { name: 'Ver Transportes del Sur' }))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=fleteros&ver=2'))
    expect(await screen.findByRole('region', { name: 'Ficha del fletero' })).toBeInTheDocument()
  })

  it('si la existente ya tiene el rol sólo se ofrece verla', async () => {
    const dialogo = await altaRepetida({ id: 2, razon_social: 'Transportes del Sur', roles: ['fletero', 'proveedor'] })
    await within(dialogo).findByRole('button', { name: 'Ver Transportes del Sur' })
    expect(within(dialogo).queryByRole('button', { name: /Sumarle el rol/ })).toBeNull()
  })

  it('al EDITAR un CUIT que choca con otra se muestra el mensaje pero no se ofrece sumar el rol', async () => {
    put.mockRejectedValue(duplicado({ id: 1, razon_social: 'Agro Norte SA', roles: ['cliente'] }))
    abrir('/transporte?pestana=fleteros')
    fireEvent.click(await screen.findByText('Transportes del Sur'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('ya es de «Agro Norte SA»')
    expect(within(dialogo).queryByRole('button', { name: /Sumarle el rol/ })).toBeNull()
    expect(within(dialogo).getByRole('button', { name: 'Ver Agro Norte SA' })).toBeInTheDocument()
  })

  it('un error que no es de CUIT se muestra como siempre', async () => {
    post.mockRejectedValue(new ApiError(422, 'el tercero tiene que ser al menos una cosa'))
    abrir('/transporte?pestana=fleteros')
    await screen.findByText('Transportes del Sur')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(within(dialogo).getByText('Guardar'))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('al menos una cosa')
    expect(within(dialogo).queryByRole('button', { name: /Sumarle/ })).toBeNull()
  })
})

describe('Transporte · Vehículos', () => {
  it('🔑 la pestaña lista chasis, acoplado y el fletero por nombre, como la pantalla que era', async () => {
    abrir('/transporte?pestana=vehiculos')
    const fila = (await screen.findByText('AB123CD')).closest('tr') as HTMLElement
    expect(within(fila).getByText('EF456GH')).toBeInTheDocument()
    await waitFor(() => expect(within(fila).getByText('Transportes del Sur')).toBeInTheDocument())
    for (const encabezado of ['Chasis', 'Acoplado', 'Fletero']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(encabezado) })).toBeInTheDocument()
    }
  })

  it('🔑 ?ver= abre la ficha del vehículo en su pestaña, con el fletero por nombre, y cerrarla limpia el parámetro', async () => {
    abrir('/transporte?pestana=vehiculos&ver=21')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Patente del chasis')).toHaveValue('AB123CD')
    expect(within(dialogo).getByRole('heading', { name: 'Editar Vehículos' })).toBeInTheDocument()
    fireEvent.click(within(dialogo).getByText('Cancelar'))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=vehiculos'))
  })

  it('el alta de un vehículo guarda por la misma API de siempre', async () => {
    post.mockResolvedValue({ ...VEHICULOS[0], id: 22 })
    abrir('/transporte?pestana=vehiculos')
    await screen.findByText('AB123CD')
    fireEvent.click(screen.getByText('Nuevo'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('Patente del chasis'), { target: { value: 'ZZ999ZZ' } })
    fireEvent.click(within(dialogo).getByText('Guardar'))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toBe('/api/vehiculos')
    expect(post.mock.calls[0][1]).toMatchObject({ patente_chasis: 'ZZ999ZZ' })
  })
})

describe('Transporte · Choferes', () => {
  it('la pestaña lista nombre, CUIT con guiones, DNI, teléfono y fletero', async () => {
    abrir('/transporte?pestana=choferes')
    const fila = (await screen.findByText('Juan Pérez')).closest('tr') as HTMLElement
    expect(within(fila).getByText('20-12345678-6')).toBeInTheDocument()
    expect(within(fila).getByText('20111222')).toBeInTheDocument()
    await waitFor(() => expect(within(fila).getByText('Transportes del Sur')).toBeInTheDocument())
    for (const encabezado of ['Nombre', 'CUIT', 'DNI', 'Teléfono', 'Fletero']) {
      expect(screen.getByRole('columnheader', { name: new RegExp(encabezado) })).toBeInTheDocument()
    }
  })

  it('el fletero del chofer se elige por nombre, no por número', async () => {
    abrir('/transporte?pestana=choferes')
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

  it('🔑 ?ver= abre la ficha del chofer en su pestaña, y cerrarla limpia el parámetro', async () => {
    abrir('/transporte?pestana=choferes&ver=11')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Nombre')).toHaveValue('Juan Pérez')
    fireEvent.click(within(dialogo).getByText('Cancelar'))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=choferes'))
  })
})

describe('Transporte · ficha del fletero', () => {
  it('🔑 al abrir un fletero se ven sus choferes y sus vehículos, con enlace', async () => {
    abrir('/transporte?pestana=fleteros')
    fireEvent.click(await screen.findByText('Transportes del Sur'))
    const dialogo = await screen.findByRole('dialog')
    const ficha = await within(dialogo).findByRole('region', { name: 'Ficha del fletero' })
    const chofer = await within(ficha).findByRole('link', { name: 'Juan Pérez' })
    expect(chofer).toHaveAttribute('href', '/transporte?pestana=choferes&ver=11')
    expect(within(ficha).getByText(/20-12345678-6/)).toBeInTheDocument()
    const vehiculo = await within(ficha).findByRole('link', { name: 'AB123CD' })
    expect(vehiculo).toHaveAttribute('href', '/transporte?pestana=vehiculos&ver=21')
    expect(within(ficha).getByText(/Acoplado EF456GH/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/api/choferes?fletero_id=2')
    expect(get).toHaveBeenCalledWith('/api/vehiculos?fletero_id=2')
  })

  it('🔑 el enlace del chofer lleva a su ficha en la pestaña Choferes', async () => {
    abrir('/transporte?pestana=fleteros')
    fireEvent.click(await screen.findByText('Transportes del Sur'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(await within(dialogo).findByRole('link', { name: 'Juan Pérez' }))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=choferes&ver=11'))
    const ficha = await screen.findByRole('dialog')
    expect(within(ficha).getByLabelText('Nombre')).toHaveValue('Juan Pérez')
    // Con la ficha abierta el resto queda oculto al lector, de ahí `hidden`.
    expect(screen.getByRole('tab', { name: 'Choferes', hidden: true })).toHaveAttribute('data-state', 'active')
  })

  it('🔑 el enlace del vehículo lleva a su ficha en la pestaña Vehículos', async () => {
    abrir('/transporte?pestana=fleteros')
    fireEvent.click(await screen.findByText('Transportes del Sur'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.click(await within(dialogo).findByRole('link', { name: 'AB123CD' }))
    await waitFor(() => expect(ubicacion()).toBe('/transporte?pestana=vehiculos&ver=21'))
    const ficha = await screen.findByRole('dialog')
    expect(within(ficha).getByLabelText('Patente del chasis')).toHaveValue('AB123CD')
    expect(screen.getByRole('tab', { name: 'Vehículos', hidden: true })).toHaveAttribute('data-state', 'active')
  })

  it('un fletero sin choferes ni vehículos lo dice', async () => {
    ENTIDADES.push(entidad(5, 'Fletero Nuevo', ['fletero']))
    get.mockImplementation((ruta: string) => {
      if (ruta.startsWith('/api/terceros/rol/fletero')) return Promise.resolve(ENTIDADES.filter((e) => e.es_fletero))
      return Promise.resolve([])
    })
    abrir('/transporte?pestana=fleteros&ver=5')
    const ficha = await screen.findByRole('region', { name: 'Ficha del fletero' })
    expect(await within(ficha).findByText('Todavía no tiene choferes.')).toBeInTheDocument()
    expect(within(ficha).getByText('Todavía no tiene vehículos.')).toBeInTheDocument()
    ENTIDADES.pop()
  })

  it('?ver= abre la ficha de esa fila al cargar', async () => {
    abrir('/transporte?pestana=fleteros&ver=2')
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('Razón social')).toHaveValue('Transportes del Sur')
    expect(within(dialogo).getByRole('heading', { name: 'Editar fletero' })).toBeInTheDocument()
  })

  it('el fletero no pide la línea de Carta de porte: es de los clientes', async () => {
    abrir('/transporte?pestana=fleteros&ver=2')
    await screen.findByRole('dialog')
    expect(get.mock.calls.some(([r]) => String(r).includes('/titulares/de-tercero/'))).toBe(false)
  })
})

