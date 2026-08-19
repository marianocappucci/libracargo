-- Tablas espejo del sistema legado de Suitrans, para el staging de F6.
--
-- 🔑 **Todo es TEXT, y no hay una sola restricción.** El dump entra tal cual y
-- recién después se transforma. Tipar durante la carga mezcla dos clases de
-- error —el que trae el dato y el que mete la conversión— y deja sin forma de
-- saber cuál de los dos falló. Un `date NOT NULL` de MySQL admite
-- `0000-00-00`; un `float(10,2)` admite lo que el navegador haya mandado.
--
-- Los nombres de tabla y de columna son **idénticos** a los del legado, hasta
-- en los prefijos redundantes (`cliente_cliente_id`) y en la abreviatura que no
-- coincide con el nombre de la tabla (`fleteroctacte` guarda `fletectacte_*`).
-- Renombrar acá obligaría a leer dos veces cada consulta del perfilado contra
-- la estructura real.

-- 🔑 **Cada importe entra dos veces.** Las 15 columnas de plata del legado son
-- `float(10,2)`, o sea **precisión simple**: la columna `x` trae lo que el
-- sistema viejo muestra —el `float` formateado a 2 decimales— y la columna
-- `x_crudo` trae el mismo valor casteado a `DECIMAL(20,6)`, que es lo que
-- realmente hay adentro del float. Para $1.234.567,89 eso da `1234567.88` y
-- `1234567.875000`: la diferencia entre las dos columnas **es** la pérdida del
-- float, medida sobre los datos reales en vez de estimada.
--
-- Lo que ninguna de las dos recupera es lo que la persona tipeó: eso se perdió
-- en 2021 al guardarlo. Por eso el entregable del gate es un **reporte de
-- diferencias** para que el cliente lo valide, no un número que cuadre.

DROP SCHEMA IF EXISTS legado CASCADE;
CREATE SCHEMA legado;

CREATE TABLE legado.clientes (
    cliente_id TEXT, cliente_razonsocial TEXT, cliente_direccion TEXT,
    cliente_cp TEXT, cliente_localidad TEXT, cliente_tel TEXT, cliente_cel TEXT,
    cliente_fax TEXT, cliente_email TEXT, cliente_condicion_iva TEXT,
    cliente_cuit TEXT, cliente_contacto TEXT, cliente_observaciones TEXT
);

CREATE TABLE legado.fleteros (
    fletero_id TEXT, fletero_razonsocial TEXT, fletero_direccion TEXT,
    fletero_cp TEXT, fletero_localidad TEXT, fletero_tel TEXT, fletero_cel TEXT,
    fletero_fax TEXT, fletero_mail TEXT, fletero_condicion_iva TEXT,
    fletero_cuit TEXT, fletero_contacto TEXT, fletero_observaciones TEXT
);

CREATE TABLE legado.proveedores (
    proveedor_id TEXT, proveedor_razonsocial TEXT, proveedor_direccion TEXT,
    proveedor_cp TEXT, proveedor_localidad TEXT, proveedor_tel TEXT,
    proveedor_cel TEXT, proveedor_fax TEXT, proveedor_mail TEXT,
    proveedor_condicion_iva TEXT, proveedor_cuit TEXT, proveedor_contacto TEXT,
    proveedor_observaciones TEXT
);

CREATE TABLE legado.choferes (
    chofer_id TEXT, chofer_nombre TEXT, chofer_dni TEXT, chofer_chasis TEXT,
    chofer_acoplado TEXT, chofer_telefono TEXT, chofer_flete_id TEXT
);

CREATE TABLE legado.origen (origen_id TEXT, origen_nombre TEXT);

CREATE TABLE legado.destino (destino_id TEXT, destino_nombre TEXT);

CREATE TABLE legado.orden_carga (
    carga_id TEXT, carga_fecha TEXT, carga_cliente_id TEXT, carga_origen_id TEXT,
    carga_destino_id TEXT, carga_remito TEXT, carga_tipo TEXT, carga_cantidad TEXT,
    carga_fletero_id TEXT, carga_chofer_id TEXT, carga_fsuitrans TEXT,
    carga_factura TEXT, carga_importe TEXT, carga_importe_crudo TEXT, carga_iva TEXT, carga_iva_crudo TEXT, carga_total TEXT, carga_total_crudo TEXT,
    carga_comision TEXT, carga_comision_crudo TEXT, carga_facturado TEXT, carga_razonsocial TEXT
);

CREATE TABLE legado.facturas (
    factura_fecha TEXT, factura_cliente_id TEXT, factura_tipo TEXT,
    factura_nro TEXT, factura_neto TEXT, factura_neto_crudo TEXT, factura_iva TEXT, factura_iva_crudo TEXT, factura_total TEXT, factura_total_crudo TEXT,
    factura_razonsocial TEXT
);

CREATE TABLE legado.clientectacte (
    clientectacte_id TEXT, clientectacte_carga_id TEXT, clientectacte_fecha TEXT,
    clientectacte_factura TEXT, clientectacte_cliente_id TEXT,
    clientectacte_tipo_mov TEXT, clientectacte_descripcion TEXT,
    clientectacte_importe1 TEXT, clientectacte_importe1_crudo TEXT, clientectacte_importe2 TEXT, clientectacte_importe2_crudo TEXT,
    clientectacte_novedad_id TEXT
);

-- La tabla se llama `fleteroctacte` y sus columnas `fletectacte_*`. No es un
-- error de transcripción: es así en el legado.
CREATE TABLE legado.fleteroctacte (
    fletectacte_id TEXT, fletectacte_carga_id TEXT, fletectacte_fecha TEXT,
    fletectacte_fletero_id TEXT, fletectacte_comprobante TEXT,
    fletectacte_tipo_mov TEXT, fletectacte_importe1 TEXT, fletectacte_importe1_crudo TEXT,
    fletectacte_importe2 TEXT, fletectacte_importe2_crudo TEXT, fletectacte_novedad_id TEXT
);

CREATE TABLE legado.ctacteprov (
    ctacteprov_id TEXT, ctacteprov_proveedor_id TEXT, ctacteprov_fecha TEXT,
    ctacteprov_tipo TEXT, ctacteprov_nrocomprob TEXT, ctacteprov_descripcion TEXT,
    ctacteprov_importe1 TEXT, ctacteprov_importe1_crudo TEXT, ctacteprov_importe2 TEXT, ctacteprov_importe2_crudo TEXT, ctacteprov_novedad_id TEXT,
    ctacteprov_fleteroctacte_id TEXT, ctacteprov_fletero_id TEXT
);

CREATE TABLE legado.novedades (
    novedad_id TEXT, novedad_fecha TEXT, novedad_tipo TEXT, novedad_efectivo TEXT,
    novedad_cliente_id TEXT, novedad_fletero_id TEXT, novedad_proveedor_id TEXT,
    novedad_recibo TEXT, novedad_descripcion TEXT, novedad_importe1 TEXT, novedad_importe1_crudo TEXT,
    novedad_importe2 TEXT, novedad_importe2_crudo TEXT
);

CREATE TABLE legado.sucesos (
    sucesos_id TEXT, sucesos_fecha TEXT, sucesos_hora TEXT, sucesos_tipo TEXT,
    sucesos_usuario TEXT, sucesos_ordencarga TEXT, sucesos_novedades TEXT
);

-- Se copia por completitud del espejo. **No se migra**: los usuarios los maneja
-- LibraAuth, y estas claves son MD5 sin sal.
CREATE TABLE legado.usuarios (usuario_nombre TEXT, usuario_clave TEXT);
