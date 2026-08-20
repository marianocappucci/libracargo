-- Datos sintéticos con las patologías documentadas del legado de Suitrans.
--
-- 🔑 **No son datos de Suitrans.** Son inventados, y están puestos para que el
-- perfilado tenga qué encontrar: si el informe midiera sobre una base sana, un
-- perfilado que no mide nada daría exactamente el mismo resultado que uno que
-- funciona.
--
-- Cada patología convive con su control —una relación con huérfanos y otra sin
-- ellos, una columna truncada y otra no— para que los tests puedan afirmar los
-- ceros además de los positivos.

SET SESSION sql_mode = '';

-- Clientes. El 2 y el 3 comparten CUIT: es el insumo del reporte de fusión.
-- El acento del cliente 1 es la muestra que decide la codificación.
INSERT INTO clientes VALUES
 (1,'Agro del Oeste','San Martín 450',6600,'Mercedes','2324-441122','','','a@x.com','RI','30-71234567-9','José Pérez',''),
 (2,'Molinos Suipacha','Belgrano 12',6612,'Suipacha','','','','','RI','30-70987654-3','',''),
 (3,'Molinos Suipacha SA','Belgrano 12',6612,'Suipacha','','','','','RI','30709876543','','duplicado por CUIT');

-- Fleteros: sin patología, son el control del bloque de maestros.
INSERT INTO fleteros VALUES
 (1,'Transportes Aguirre','Ruta 5 km 100',6600,'Mercedes','','','','','MT','20-24567890-1','',''),
 (2,'Cargas del Sur','Alsina 900',8000,'Bahía Blanca','','','','','RI','20-11223344-5','',''),
 (3,'OFICINA','',0,'','','','','','RI','','','');

INSERT INTO proveedores VALUES
 (1,'Gomería Central','Mitre 30',6600,'Mercedes','','','','','RI','30-55667788-9','','');

-- El chofer 2 apunta a un fletero que no existe: huérfano.
INSERT INTO choferes VALUES
 (1,'Ramón Ferreyra','24567890','AB123CD','AC456EF','',1),
 (2,'Julio Aguirre','20345678','AD789GH','','',77);

INSERT INTO origen VALUES (1,'Suipacha'),(2,'Mercedes');
INSERT INTO destino VALUES (1,'Rosario'),(2,'Bahía Blanca');

-- Órdenes de carga. Las patologías, en orden:
--   #1 sana, facturada, con su factura existente.
--   #2 cliente 999 inexistente → huérfano.
--   #3 fecha 0000-00-00.
--   #4 cantidad con texto pegado, y facturada SIN factura que la respalde.
--   #5 importe que el float32 no representa: 1234567.89 queda en 1234567.875.
INSERT INTO orden_carga VALUES
 (1,'2026-08-03',1,1,1,'0001-00012345','Cereal','30000',1,1,1,1041,845000.00,177450.00,1022450.00,84500.00,1,1),
 (2,'2026-08-05',999,1,2,'0001-00012346','Cereal','28500',1,1,1,NULL,500000.00,105000.00,605000.00,50000.00,0,1),
 (3,'0000-00-00',2,2,1,'0001-00012347','General','140 bultos',2,NULL,1,NULL,610500.50,128205.11,738705.61,61050.05,0,2),
 (4,'2026-08-12',1,1,2,'0001-00012348','Cereal','varios',1,2,1,9999,398000.00,83580.00,481580.00,39800.00,1,1),
 (5,'2026-08-14',2,2,2,'0001-00012349','Cereal','12.5',2,1,1,NULL,1234567.89,259259.26,1493827.15,123456.79,0,1);

INSERT INTO facturas VALUES ('2026-08-10',1,'A',1041,845000.00,177450.00,1022450.00,1);

-- Cuenta corriente de clientes. La fila 2 mueve las DOS columnas a la vez, que
-- es lo que rompe la lectura "importe1 = debe, importe2 = haber". La 3 tiene la
-- descripción cortada en 50 caracteres exactos.
INSERT INTO clientectacte VALUES
 (1,1,'2026-08-03',1041,1,'FACTURA A 0001-1041','Venta',1022450.00,0.00,NULL),
 (2,NULL,'2026-08-14',NULL,1,'AJUSTE','Ajuste de saldo',5000.00,5000.00,NULL),
 (3,NULL,'2026-08-15',NULL,2,'COBRO','SUIPACHA - BUENOS AIRES - 30000 - CEREAL - 0001-00012345',0.00,300000.00,1),
 (4,NULL,'2026-08-16',NULL,1,'AJUSTE','Ajuste con el signo al reves',0.00,-5000.00,NULL),
 (5,NULL,'0000-00-00',NULL,1,'COBRO','Fecha en cero, con contrapartida',1000.00,0.00,1);

-- Cuenta corriente de fleteros: la fila 1 tiene el tipo_mov cortado en 50.
INSERT INTO fleteroctacte VALUES
 (1,1,'2026-08-03',1,0,'SUIPACHA - BUENOS AIRES - 30000 - CEREAL - 0001-00012345',84500.00,0.00,NULL),
 (2,2,'2026-08-05',1,0,'COMISION',50000.00,0.00,NULL),
 (3,0,'2026-08-16',2,0,'PAGO',0.00,120000.00,2);

INSERT INTO ctacteprov VALUES
 (1,1,'2026-08-07','FACTURA',881,'Cubiertas',95000.00,0.00,NULL,NULL,NULL),
 (2,1,'2026-08-18','PAGO',NULL,'Pago parcial',0.00,45000.00,3,NULL,1);

INSERT INTO novedades VALUES
 (1,'2026-08-15','COBRO',1,2,NULL,NULL,210,'Cobro Molinos',300000.00,0.00),
 (2,'2026-08-16','PAGO',0,NULL,2,NULL,144,'Pago Cargas del Sur',0.00,120000.00),
 (3,'2026-08-18','PAGO',1,NULL,NULL,1,145,'Pago gomería',0.00,45000.00);

INSERT INTO sucesos VALUES
 (1,'2026-08-03','09:15:00','alta orden','marta',1,0),
 (2,'2026-08-15','17:40:00','alta novedad','marta',0,1);

INSERT INTO usuarios VALUES ('marta','5f4dcc3b5aa765d61d8327deb882cf99');
