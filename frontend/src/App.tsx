import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import Layout from '@/components/Layout'
import { useAuth } from '@/context/AuthContext'
import Inicio from '@/pages/Inicio'
import Caja from '@/pages/Caja'
import ComprobantesSeccion from '@/pages/ComprobantesSeccion'
import EditarPreFactura from '@/pages/EditarPreFactura'
import FacturarPendientes from '@/pages/FacturarPendientes'
import Configuracion from '@/pages/Configuracion'
import CuentaCorriente from '@/pages/CuentaCorriente'
import Login from '@/pages/Login'
import { ForgotPassword, ResetPassword } from '@/pages/PasswordReset'
import Logs from '@/pages/Logs'
import Ordenes from '@/pages/Ordenes'
import PreFactura from '@/pages/PreFactura'
import PreFacturas from '@/pages/PreFacturas'
import Reporte from '@/pages/Reporte'
import ReportesIndice from '@/pages/ReportesIndice'
import Usuarios from '@/pages/Usuarios'
import {
  Choferes, Localidades, RazonesSociales, Terceros, TiposCarga, Vehiculos,
} from '@/pages/maestros'

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
                <Route path="/reportes/:slug" element={<Reporte />} />
                <Route path="/usuarios" element={<Usuarios />} />
                <Route path="/logs" element={<Logs />} />
                <Route path="/configuracion" element={<Configuracion />} />
                <Route path="/terceros" element={<Terceros />} />
                <Route path="/choferes" element={<Choferes />} />
                <Route path="/vehiculos" element={<Vehiculos />} />
                <Route path="/localidades" element={<Localidades />} />
                <Route path="/tipos-carga" element={<TiposCarga />} />
                <Route path="/razones-sociales" element={<RazonesSociales />} />
              </Routes>
            </Layout>
          </Privado>
        }
      />
    </Routes>
  )
}
