"""Backup y restore: que el ZIP traiga los datos, y que reponerlo los devuelva.

Estos tests no miran el proceso —que el endpoint conteste 200, que no tire
excepción— sino el **producto**. Es a propósito: el historial de este módulo en
la familia es una lista de backups que salieron "bien" y estaban vacíos, y todos
devolvían éxito. Un test que sólo mira el código de respuesta los habría dado
por buenos a todos.

Los dos que importan de verdad son:

- el ZIP trae el dump y **pesa algo**, y
- restaurarlo **devuelve los datos** — no que conteste `ok`.

El segundo existe porque el modo de falla real de un restore es contestar bien y
no hacer nada: si el proceso sigue con la conexión vieja abierta, la pantalla
dice que salió y los datos son los de antes.
"""

import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

ADMIN, CLAVE = "admin", "clave-de-prueba"


@pytest.fixture
def cliente(engine, sesion, tmp_path, monkeypatch):
    """La app con los backups cayendo en un directorio temporal.

    Depende de `sesion` sólo por su limpieza de tablas al final; el test no la
    usa. Importa que no la use: una `Session` con una transacción abierta se
    quedaría con los locks de las tablas, y el `pg_restore --clean` —que las
    tiene que dropear— esperaría a que alguien la cierre.
    """
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", ADMIN)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(
        database_url=os.environ["DATABASE_URL"], entorno="test", debug=False,
        directorio_de_datos=str(tmp_path),
    )
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    assert c.post("/auth/login", json={"username": ADMIN, "password": CLAVE}).status_code == 200
    c.carpeta = tmp_path / "backups"
    yield c
    AuthBase.metadata.drop_all(engine)


def _dumps_del_zip(contenido: bytes) -> dict[str, int]:
    """Los archivos de `bases/` del ZIP, con su tamaño."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        return {
            os.path.basename(i.filename): i.file_size
            for i in z.infolist()
            if i.filename.startswith("bases/") and not i.is_dir()
        }


def test_el_zip_trae_la_base_y_no_viene_vacia(cliente):
    """Lo que hay que medir es el contenido, no que el endpoint haya contestado.

    Un `pg_dump` que falla a mitad deja un archivo con nombre de backup y cero
    bytes adentro, y el ZIP se arma igual. El tamaño es lo que separa un backup
    de un archivo que se llama como uno.
    """
    r = cliente.get("/api/config/backup-ahora")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    dumps = _dumps_del_zip(r.content)
    assert set(dumps) == {"libracargo.dump"}, dumps
    # Un dump de un schema real no baja de unos pocos KB ni comprimido. El
    # umbral es flojo a propósito: lo que cierra es el caso de los 0 bytes.
    assert dumps["libracargo.dump"] > 1000, dumps


def _razones_sociales(cliente) -> list[str]:
    return [t["razon_social"] for t in cliente.get("/api/terceros").json()]


def test_restaurar_deja_la_base_como_estaba(cliente):
    """El test que justifica todo el resto, y se mide en las DOS direcciones.

    Modo de falla que cierra: el restore contesta `ok`, la pantalla dice que
    salió bien, y los datos siguen siendo los de antes porque el proceso nunca
    soltó la conexión vieja. Preguntar por el dato **después** es la única forma
    de distinguir las dos cosas.

    Y se pregunta por dos: que vuelva el que estaba en el backup **y que se vaya
    el que se creó después**. Sólo lo primero lo cumpliría también un restore
    que no hiciera nada, porque el de antes ya estaba ahí.

    No se usa el borrado como observable a propósito: en este producto la baja
    es lógica y la fila sobrevive, así que "borrar y ver si vuelve" no
    distinguiría un restore bueno de uno que no corrió.
    """
    cliente.post("/api/terceros", json={"razon_social": "Antes SA", "es_cliente": True})
    copia = cliente.get("/api/config/backup-ahora").content

    cliente.post("/api/terceros", json={"razon_social": "Después SRL", "es_cliente": True})
    assert "Después SRL" in _razones_sociales(cliente), "el control de que el alta entró"

    r = cliente.post("/api/config/restore",
                     files={"backup_file": ("copia.zip", copia, "application/zip")})
    assert r.status_code == 200, r.text
    assert r.json()["bases_restauradas"] == ["libracargo.dump"]

    quedan = _razones_sociales(cliente)
    assert "Antes SA" in quedan, "el restore contestó ok y no repuso nada"
    assert "Después SRL" not in quedan, "quedó lo posterior al backup: no se reemplazó nada"


def test_antes_de_restaurar_se_guarda_el_estado_anterior(cliente):
    """Restaurar es lo más destructivo que se puede apretar desde una pantalla.

    El backup previo es la única vuelta atrás si el archivo que subieron no era
    el que el cliente creía. Que exista el archivo, no que la respuesta lo
    nombre: el nombre lo puede devolver igual una implementación que no lo
    escribió.
    """
    copia = cliente.get("/api/config/backup-ahora").content
    r = cliente.post("/api/config/restore",
                     files={"backup_file": ("copia.zip", copia, "application/zip")})
    assert r.status_code == 200, r.text

    previo = cliente.carpeta / r.json()["backup_previo"]
    assert previo.exists(), f"{previo} no está: no hay vuelta atrás"
    assert "antes_restore" in previo.name
    assert _dumps_del_zip(previo.read_bytes())["libracargo.dump"] > 1000


def test_el_backup_a_pedido_queda_listado(cliente):
    assert cliente.get("/api/config/backups").json() == []
    assert cliente.post("/api/config/backups").status_code == 200

    listado = cliente.get("/api/config/backups").json()
    assert len(listado) == 1
    assert listado[0]["filename"].endswith(".zip")
    assert (cliente.carpeta / listado[0]["filename"]).exists()


def test_un_archivo_que_no_es_un_backup_se_rechaza(cliente):
    """422 y no 500: el archivo se leyó perfecto, lo que no sirve es el contenido."""
    r = cliente.post("/api/config/restore",
                     files={"backup_file": ("cualquiera.zip", b"no soy un zip", "application/zip")})
    assert r.status_code == 422
    assert "backup" in r.json()["detail"].lower()


def test_el_backup_de_otro_producto_de_la_familia_se_rechaza(cliente):
    """Los seis productos bajan un ZIP con la misma forma y nombres parecidos.

    Sin este chequeo, restaurar el de al lado deja la instancia con la base de
    otro sistema — un error fácil de cometer desde una carpeta de Descargas y
    muy difícil de deshacer.
    """
    ajeno = io.BytesIO()
    with zipfile.ZipFile(ajeno, "w") as z:
        z.writestr("bases/contalibra.dump", b"PGDMP" + b"\0" * 100)

    r = cliente.post("/api/config/restore",
                     files={"backup_file": ("ajeno.zip", ajeno.getvalue(), "application/zip")})
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert "contalibra.dump" in detalle and "libracargo.dump" in detalle, detalle


def test_todo_esto_es_solo_para_administradores(cliente, engine):
    """Un backup es la base entera en un archivo: quien lo baja se lleva todo.

    Se prueban los cinco endpoints y no uno de muestra. El gate va en el router,
    así que alcanzaría con uno... hasta el día que alguien monte una ruta más
    con su propia dependencia.
    """
    assert cliente.post("/api/usuarios", json={
        "username": "operador", "name": "Operador", "role": "staff",
        "password": "otra-clave-de-prueba",
    }).status_code == 201

    otro = TestClient(cliente.app, base_url="https://testserver")
    assert otro.post("/auth/login", json={
        "username": "operador", "password": "otra-clave-de-prueba"}).status_code == 200

    assert otro.get("/api/config/backups").status_code == 403
    assert otro.post("/api/config/backups").status_code == 403
    assert otro.get("/api/config/backup-ahora").status_code == 403
    assert otro.get("/api/config/backups/loquesea.zip").status_code == 403
    assert otro.post("/api/config/restore", files={
        "backup_file": ("x.zip", b"x", "application/zip")}).status_code == 403


def test_no_se_puede_bajar_un_archivo_de_afuera_de_la_carpeta(cliente):
    """El nombre viene de la URL: sin el chequeo, `../../etc/passwd` lo sirve."""
    assert cliente.get("/api/config/backups/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
    # El control de que la ruta normal sí funciona está en
    # `test_el_backup_a_pedido_queda_listado`: sin él, un 404 constante haría
    # pasar esta aserción con el endpoint entero roto.
