/*M!999999\- enable the sandbox mode */ 

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*M!100616 SET @OLD_NOTE_VERBOSITY=@@NOTE_VERBOSITY, NOTE_VERBOSITY=0 */;
DROP TABLE IF EXISTS `choferes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `choferes` (
  `chofer_id` int(11) NOT NULL AUTO_INCREMENT,
  `chofer_nombre` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `chofer_dni` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `chofer_chasis` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `chofer_acoplado` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `chofer_telefono` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `chofer_flete_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`chofer_id`)
) ENGINE=InnoDB AUTO_INCREMENT=196 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `clientectacte`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `clientectacte` (
  `clientectacte_id` int(11) NOT NULL AUTO_INCREMENT,
  `clientectacte_carga_id` int(11) DEFAULT NULL,
  `clientectacte_fecha` date NOT NULL,
  `clientectacte_factura` int(11) DEFAULT NULL,
  `clientectacte_cliente_id` int(11) NOT NULL,
  `clientectacte_tipo_mov` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `clientectacte_descripcion` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `clientectacte_importe1` float(10,2) DEFAULT NULL,
  `clientectacte_importe2` float(10,2) DEFAULT NULL,
  `clientectacte_novedad_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`clientectacte_id`)
) ENGINE=InnoDB AUTO_INCREMENT=6277 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `clientes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `clientes` (
  `cliente_id` int(11) NOT NULL AUTO_INCREMENT,
  `cliente_razonsocial` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `cliente_direccion` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `cliente_cp` int(11) NOT NULL,
  `cliente_localidad` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `cliente_tel` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `cliente_cel` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `cliente_fax` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `cliente_email` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `cliente_condicion_iva` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `cliente_cuit` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `cliente_contacto` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `cliente_observaciones` varchar(100) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  PRIMARY KEY (`cliente_id`)
) ENGINE=InnoDB AUTO_INCREMENT=76 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `ctacteprov`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `ctacteprov` (
  `ctacteprov_id` int(11) NOT NULL AUTO_INCREMENT,
  `ctacteprov_proveedor_id` int(11) DEFAULT NULL,
  `ctacteprov_fecha` date NOT NULL,
  `ctacteprov_tipo` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `ctacteprov_nrocomprob` int(11) DEFAULT NULL,
  `ctacteprov_descripcion` varchar(110) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `ctacteprov_importe1` float(10,2) DEFAULT NULL,
  `ctacteprov_importe2` float(10,2) DEFAULT NULL,
  `ctacteprov_novedad_id` int(11) DEFAULT NULL,
  `ctacteprov_fleteroctacte_id` int(11) DEFAULT NULL,
  `ctacteprov_fletero_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`ctacteprov_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3343 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `destino`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `destino` (
  `destino_id` int(11) NOT NULL AUTO_INCREMENT,
  `destino_nombre` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  PRIMARY KEY (`destino_id`),
  UNIQUE KEY `destino_nombre` (`destino_nombre`)
) ENGINE=InnoDB AUTO_INCREMENT=101 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `facturas`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `facturas` (
  `factura_fecha` date NOT NULL,
  `factura_cliente_id` int(11) NOT NULL,
  `factura_tipo` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `factura_nro` int(11) NOT NULL,
  `factura_neto` float(10,2) NOT NULL,
  `factura_iva` float(10,2) NOT NULL,
  `factura_total` float(10,2) NOT NULL,
  `factura_razonsocial` int(11) NOT NULL,
  PRIMARY KEY (`factura_nro`,`factura_razonsocial`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `fleteroctacte`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `fleteroctacte` (
  `fletectacte_id` int(11) NOT NULL AUTO_INCREMENT,
  `fletectacte_carga_id` int(11) NOT NULL,
  `fletectacte_fecha` date NOT NULL,
  `fletectacte_fletero_id` int(11) NOT NULL,
  `fletectacte_comprobante` int(11) NOT NULL,
  `fletectacte_tipo_mov` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  `fletectacte_importe1` float(10,2) DEFAULT NULL,
  `fletectacte_importe2` float(10,2) DEFAULT NULL,
  `fletectacte_novedad_id` int(11) DEFAULT NULL,
  PRIMARY KEY (`fletectacte_id`)
) ENGINE=InnoDB AUTO_INCREMENT=13017 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `fleteros`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `fleteros` (
  `fletero_id` int(11) NOT NULL AUTO_INCREMENT,
  `fletero_razonsocial` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_direccion` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_cp` int(11) DEFAULT NULL,
  `fletero_localidad` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_tel` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_cel` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_fax` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_mail` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_condicion_iva` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_cuit` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_contacto` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `fletero_observaciones` varchar(100) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  PRIMARY KEY (`fletero_id`)
) ENGINE=InnoDB AUTO_INCREMENT=187 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `novedades`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `novedades` (
  `novedad_id` int(11) NOT NULL AUTO_INCREMENT,
  `novedad_fecha` date NOT NULL,
  `novedad_tipo` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `novedad_efectivo` tinyint(1) DEFAULT NULL,
  `novedad_cliente_id` int(11) DEFAULT NULL,
  `novedad_fletero_id` int(11) DEFAULT NULL,
  `novedad_proveedor_id` int(11) DEFAULT NULL,
  `novedad_recibo` int(11) DEFAULT NULL,
  `novedad_descripcion` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `novedad_importe1` float(10,2) DEFAULT NULL,
  `novedad_importe2` float(10,2) DEFAULT NULL,
  PRIMARY KEY (`novedad_id`)
) ENGINE=InnoDB AUTO_INCREMENT=8385 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `orden_carga`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `orden_carga` (
  `carga_id` int(11) NOT NULL AUTO_INCREMENT,
  `carga_fecha` date NOT NULL,
  `carga_cliente_id` int(11) NOT NULL,
  `carga_origen_id` int(11) NOT NULL,
  `carga_destino_id` int(11) NOT NULL,
  `carga_remito` varchar(20) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `carga_tipo` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `carga_cantidad` varchar(20) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `carga_fletero_id` int(11) DEFAULT NULL,
  `carga_chofer_id` int(11) DEFAULT NULL,
  `carga_fsuitrans` tinyint(1) DEFAULT NULL,
  `carga_factura` int(11) DEFAULT NULL,
  `carga_importe` float(10,2) DEFAULT NULL,
  `carga_iva` float(10,2) DEFAULT NULL,
  `carga_total` float(10,2) DEFAULT NULL,
  `carga_comision` float(10,2) DEFAULT NULL,
  `carga_facturado` tinyint(1) DEFAULT NULL,
  `carga_razonsocial` int(11) DEFAULT NULL,
  PRIMARY KEY (`carga_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4340 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `origen`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `origen` (
  `origen_id` int(11) NOT NULL AUTO_INCREMENT,
  `origen_nombre` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci NOT NULL,
  PRIMARY KEY (`origen_id`),
  UNIQUE KEY `origen_nombre` (`origen_nombre`)
) ENGINE=InnoDB AUTO_INCREMENT=48 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `proveedores`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `proveedores` (
  `proveedor_id` int(11) NOT NULL AUTO_INCREMENT,
  `proveedor_razonsocial` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_direccion` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_cp` int(11) DEFAULT NULL,
  `proveedor_localidad` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_tel` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_cel` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_fax` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_mail` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_condicion_iva` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_cuit` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_contacto` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `proveedor_observaciones` varchar(50) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  PRIMARY KEY (`proveedor_id`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `sucesos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `sucesos` (
  `sucesos_id` int(11) NOT NULL AUTO_INCREMENT,
  `sucesos_fecha` date NOT NULL,
  `sucesos_hora` time NOT NULL,
  `sucesos_tipo` varchar(40) CHARACTER SET utf8mb3 COLLATE utf8mb3_general_ci NOT NULL,
  `sucesos_usuario` varchar(11) CHARACTER SET utf8mb3 COLLATE utf8mb3_general_ci NOT NULL,
  `sucesos_ordencarga` int(11) NOT NULL,
  `sucesos_novedades` int(11) NOT NULL,
  PRIMARY KEY (`sucesos_id`)
) ENGINE=InnoDB AUTO_INCREMENT=15868 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `usuarios`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `usuarios` (
  `usuario_nombre` varchar(10) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL,
  `usuario_clave` varchar(32) CHARACTER SET latin1 COLLATE latin1_general_ci DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb3 COLLATE=utf8mb3_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*M!100616 SET NOTE_VERBOSITY=@OLD_NOTE_VERBOSITY */;

