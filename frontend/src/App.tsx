import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import Layout from '@/components/Layout'
import { useAuth } from '@/context/AuthContext'
import Inicio from '@/pages/Inicio'
import Caja from '@/pages/Caja'
import CartasDePorte from '@/pages/CartasDePorte'
import Clientes from '@/pages/Clientes'
import ComprobantesSeccion from '@/pages/ComprobantesSeccion'
import EditarPreFactura from '@/pages/EditarPreFactura'
import EmitirCartaDePorte from '@/pages/EmitirCartaDePorte'
import FacturarPendientes from '@/pages/FacturarPendientes'
import Configuracion from '@/pages/Configuracion'
import CuentaCorriente from '@/pages/CuentaCorriente'
import Login from '@/pages/Login'
import { ForgotPassword, ResetPassword } from '@/pages/PasswordReset'
import Logs from '@/pages/Logs'
import PlantillaDeTitular from '@/pages/PlantillaDeTitular'
import Ordenes from '@/pages/Ordenes'
import PreFactura from '@/pages/PreFactura'
import PreFacturas from '@/pages/PreFacturas'
import PreLiquidacionTransportistas from '@/pages/PreLiquidacionTransportistas'
import Proveedores from '@/pages/Proveedores'
import Reporte from '@/pages/Reporte'
import ReportesIndice from '@/pages/ReportesIndice'
import Transporte from '@/pages/Transporte'
import Usuarios from '@/pages/Usuarios'
import { Localidades, TiposCarga } from '@/pages/maestros'
import { destinoDeEntidadesViejo, destinoDeVehiculosViejo, irA } from '@/navegacion'

function Privado({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  // Mientras `GET /auth/me` está en vuelo, `user` es null — indistinguible de
  // "no autenticado". Sin esperar a `loading`, un refresh estando adentro
  // patea al login por un instante y se pierde la ruta que se estaba mirando.
  if (loading) return null
  return user ? <>{children}</> : <Navigate to="/login" replace />
}

/** `/gastos` era la pantalla de comprobantes de proveedores; hoy es la pestaña Proveedores de Comprobantes.
 *  Se redirige conservando el query, así `/gastos?ver=5` abre el 5 en su pestaña. `replace`: el enlace viejo
 *  no queda en el historial, y atrás no vuelve a rebotar. */
function GastosAProveedores() {
  const { search } = useLocation()
  // `seccion` primero, como la escribe `irA.gasto`: un solo enlace canónico.
  const params = new URLSearchParams({ seccion: 'proveedores' })
  new URLSearchParams(search).forEach((valor, clave) => {
    if (clave !== 'seccion') params.append(clave, valor)
  })
  return <Navigate to={`/comprobantes?${params}`} replace />
}

/** `/entidades` era la pantalla de clientes, fleteros, choferes y proveedores (ADR-040); hoy cada una vive en la suya (ADR-045).
 *  Se redirige según la pestaña que pedía el enlace, conservando la ficha (`ver`): `/entidades?pestana=fleteros&ver=7` abre el 7
 *  en Transporte → Fleteros. `replace`: el enlace viejo no queda en el historial, y atrás no vuelve a rebotar. */
function EntidadesAlDestinoNuevo() {
  const { search } = useLocation()
  return <Navigate to={destinoDeEntidadesViejo(search)} replace />
}

/** `/vehiculos` era una entrada del menú; hoy es la pestaña Vehículos de Transporte (ADR-045). Se redirige conservando el query
 *  entero, así `/vehiculos?ver=21` abre el 21 en su pestaña. `replace`, como las demás. */
function VehiculosAlTransporte() {
  const { search } = useLocation()
  return <Navigate to={destinoDeVehiculosViejo(search)} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Públicas, al lado del login y NO adentro de `Privado`: quien las usa
          es exactamente quien no puede entrar. Puestas del lado privado, el
          enlace del correo redirigiría a `/login` y pediría la contraseña que
          la persona justamente no tiene. */}
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route
        path="/*"
        element={
          <Privado>
            <Layout>
              <Routes>
                <Route path="/" element={<Inicio />} />
                <Route path="/ordenes" element={<Ordenes />} />
                <Route path="/cartas-porte" element={<CartasDePorte />} />
                {/* Formularios largos, en página propia y no en un diálogo (2026-10-09). Cuelgan de /cartas-porte: el menú
                    marca esa entrada. */}
                <Route path="/cartas-porte/emitir/:ordenId" element={<EmitirCartaDePorte />} />
                <Route path="/cartas-porte/titulares/:id/plantilla" element={<PlantillaDeTitular />} />
                <Route path="/cuentas" element={<CuentaCorriente />} />
                <Route path="/caja" element={<Caja />} />
                {/* Una entrada de menú, dos pestañas (`?seccion=`): Clientes —la ruta pelada— y Proveedores. */}
                <Route path="/comprobantes" element={<ComprobantesSeccion />} />
                <Route path="/comprobantes/facturar" element={<FacturarPendientes />} />
                {/* Las pre facturas ya no tienen entrada de menú: se llega desde Comprobantes > Clientes, y
                    «Comprobantes» queda marcada en el menú (`activoEn` con `RUTAS_DE_COMPROBANTES`). */}
                <Route path="/pre-facturas" element={<PreFacturas />} />
                <Route path="/pre-facturas/:id" element={<PreFactura />} />
                {/* Editar es la pantalla de facturar pendientes sobre una pre factura que ya existe. */}
                <Route path="/pre-facturas/:id/editar" element={<EditarPreFactura />} />
                <Route path="/gastos" element={<GastosAProveedores />} />
                <Route path="/reportes" element={<ReportesIndice />} />
                {/* Viene en bloques por transportista: no entra en la grilla genérica. Va antes que
                    `:slug`, aunque el router ya prefiere la ruta estática. */}
                <Route path="/reportes/pre-liquidacion-transportistas"
                       element={<PreLiquidacionTransportistas />} />
                <Route path="/reportes/:slug" element={<Reporte />} />
                <Route path="/usuarios" element={<Usuarios />} />
                <Route path="/logs" element={<Logs />} />
                <Route path="/configuracion" element={<Configuracion />} />
                {/* Clientes y Proveedores son entradas propias del menú, y Fleteros, Choferes y Vehículos las pestañas de
                    Transporte (ADR-045). Antes eran las cuatro pestañas de «Entidades» (ADR-040): esa ruta y las más viejas
                    (`/terceros`, `/choferes`, `/vehiculos`) se redirigen, que es lo que el log de actividad y los marcadores todavía usan. */}
                <Route path="/clientes" element={<Clientes />} />
                <Route path="/proveedores" element={<Proveedores />} />
                <Route path="/transporte" element={<Transporte />} />
                <Route path="/entidades" element={<EntidadesAlDestinoNuevo />} />
                <Route path="/terceros" element={<Navigate to={irA.clientes()} replace />} />
                <Route path="/choferes" element={<Navigate to={irA.transporte('choferes')} replace />} />
                <Route path="/vehiculos" element={<VehiculosAlTransporte />} />
                <Route path="/localidades" element={<Localidades />} />
                <Route path="/tipos-carga" element={<TiposCarga />} />
              </Routes>
            </Layout>
          </Privado>
        }
      />
    </Routes>
  )
}
