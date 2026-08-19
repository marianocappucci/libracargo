import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import Layout from '@/components/Layout'
import { useAuth } from '@/context/AuthContext'
import Inicio from '@/pages/Inicio'
import Caja from '@/pages/Caja'
import Comprobantes from '@/pages/Comprobantes'
import CuentaCorriente from '@/pages/CuentaCorriente'
import Login from '@/pages/Login'
import Ordenes from '@/pages/Ordenes'
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

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
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
                <Route path="/comprobantes" element={<Comprobantes />} />
                <Route path="/usuarios" element={<Usuarios />} />
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
