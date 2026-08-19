#!/bin/bash
# Paso 1 de F6: extracción del sistema legado de Suitrans.
#
# Se corre EN LA CUENTA cPanel `suitrans` (SSH o cPanel > Terminal), no acá.
#
#   DB_NAME=xxx DB_USER=xxx DB_PASS='xxx' bash 01-extraer.sh
#
# Qué hace:
#   - `mysqldump` COMPLETO (estructura + datos) con `--single-transaction`:
#     InnoDB, así que **no bloquea producción** ni la deja esperando.
#   - Extrae con `--default-character-set=latin1`, que devuelve los bytes tal
#     como están guardados. Las columnas son `latin1_general_ci` dentro de
#     tablas declaradas `utf8mb3`: pedirle utf8 al servidor lo haría convertir
#     de un charset que no es el real, y eso es el doble encoding que después no
#     se puede deshacer.
#   - Deja una **sonda de encoding**: el HEX de los primeros bytes de unos pocos
#     valores con acentos. Es lo único que dice si adentro de esas columnas hay
#     bytes latin1 (`E9` = é) o bytes UTF-8 (`C3A9` = é), que es la decisión que
#     abre el paso siguiente. Sin la sonda hay que adivinar.
#   - Cuenta las filas de cada tabla, para poder comparar contra lo que entre al
#     staging.
#
# Qué NO hace: no escribe, no borra ni modifica nada. En la base sólo hace
# SELECT y mysqldump. No toca `public_html`.
#
# El resultado es UN `.tar.gz` fuera de `public_html`, con su SHA-256.
# 🔴 Ese archivo tiene los datos reales de los clientes de Suitrans: se baja por
# un canal privado y no se sube a ningún repo.

set -u

STAMP="$(date +%Y%m%d-%H%M)"
OUT="$HOME/dump-suitrans-$STAMP"
DB_NAME="${DB_NAME:-}"; DB_USER="${DB_USER:-}"; DB_PASS="${DB_PASS:-}"
DB_HOST="${DB_HOST:-localhost}"

if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASS" ]; then
  echo "ERROR: faltan credenciales." >&2
  echo "Uso: DB_NAME=xxx DB_USER=xxx DB_PASS='xxx' bash 01-extraer.sh" >&2
  echo "Están en ~/public_html/sistema/conexion.php" >&2
  exit 1
fi

mkdir -p "$OUT" || exit 1
chmod 700 "$OUT"
echo "==> Salida: $OUT"

# Las credenciales van por archivo de opciones y no por la línea de comandos:
# un `-p` en el comando lo ve cualquiera con `ps` mientras corre, y queda en el
# historial del shell.
CNF="$OUT/.my.cnf"
umask 077
cat > "$CNF" <<EOF
[client]
host=$DB_HOST
user=$DB_USER
password=$DB_PASS
EOF

corriendo() { mysql --defaults-extra-file="$CNF" --default-character-set=latin1 \
                    -N -B "$DB_NAME" -e "$1" 2>/dev/null; }

# ----------------------------------------------------------------- 1. el dump
echo "==> mysqldump completo (estructura + datos)"
mysqldump --defaults-extra-file="$CNF" \
          --default-character-set=latin1 \
          --single-transaction --quick --routines --events \
          --skip-lock-tables \
          "$DB_NAME" > "$OUT/20-datos-latin1.sql" 2>"$OUT/20-datos-latin1.err"

if [ ! -s "$OUT/20-datos-latin1.sql" ]; then
  echo "ERROR: el dump salió vacío. Mirá $OUT/20-datos-latin1.err" >&2
  exit 1
fi

# Un dump que corta a la mitad —por timeout o por cuota— deja un archivo grande
# y creíble. La marca final de mysqldump es la única forma barata de saber que
# llegó hasta el final.
if ! tail -5 "$OUT/20-datos-latin1.sql" | grep -q "Dump completed"; then
  echo "ERROR: el dump NO terminó (falta la marca 'Dump completed')." >&2
  echo "No sirve: rehacerlo antes de bajar nada." >&2
  exit 1
fi
echo "    $(du -h "$OUT/20-datos-latin1.sql" | cut -f1), completo"

# ------------------------------------------------------------- 2. los conteos
echo "==> conteos exactos por tabla"
{
  echo "# Conteo exacto de filas por tabla (SELECT COUNT(*), no la estimación)"
  echo "# Fecha: $(date '+%d-%m-%Y %H:%M %Z')"
  for t in choferes clientectacte clientes ctacteprov destino facturas \
           fleteroctacte fleteros novedades orden_carga origen proveedores \
           sucesos usuarios; do
    printf '%s\t%s\n' "$t" "$(corriendo "SELECT COUNT(*) FROM \`$t\`;")"
  done
} > "$OUT/21-conteos.txt"
cat "$OUT/21-conteos.txt"

# ---------------------------------------------------- 3. la sonda de encoding
# Sólo el HEX de los primeros bytes, y de pocas filas: alcanza para decidir el
# charset y evita volcar nombres de clientes a la pantalla.
echo "==> sonda de encoding (hex de valores con acentos)"
{
  echo "# Sonda de encoding — HEX de los primeros 24 bytes de valores no-ASCII"
  echo "#"
  echo "# Cómo se lee: E9 suelto = latin1 (é). C3A9 = UTF-8 (é). Si aparecen"
  echo "# C383C2A9, ya hay doble encoding EN LA BASE y eso se decide aparte."
  echo
  for par in "clientes:cliente_razonsocial" "clientes:cliente_localidad" \
             "fleteros:fletero_razonsocial" "destino:destino_nombre" \
             "origen:origen_nombre" "orden_carga:carga_tipo" \
             "fleteroctacte:fletectacte_tipo_mov" "novedades:novedad_descripcion"; do
    tabla="${par%%:*}"; col="${par##*:}"
    echo "## $tabla.$col"
    corriendo "SELECT HEX(SUBSTRING(\`$col\`,1,24)) FROM \`$tabla\`
               WHERE \`$col\` REGEXP '[^ -~]' LIMIT 5;"
    echo "   filas con bytes no-ASCII: $(corriendo "SELECT COUNT(*) FROM \`$tabla\`
               WHERE \`$col\` REGEXP '[^ -~]';")"
    echo
  done
} > "$OUT/22-sonda-encoding.txt"

# --------------------------------------------------------- 4. empaquetar
rm -f "$CNF"
TAR="$HOME/dump-suitrans-$STAMP.tar.gz"
tar -czf "$TAR" -C "$HOME" "dump-suitrans-$STAMP" || exit 1
chmod 600 "$TAR"
rm -rf "$OUT"

echo
echo "==> Listo: $TAR"
echo "    $(du -h "$TAR" | cut -f1)"
echo "    sha256: $(sha256sum "$TAR" 2>/dev/null | cut -d' ' -f1)"
echo
echo "Bajalo por SFTP o por el File Manager de cPanel y pasámelo."
echo "🔴 Tiene datos reales de clientes: canal privado, y no va a ningún repo."
