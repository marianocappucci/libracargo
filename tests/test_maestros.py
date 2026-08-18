"""Los seis ABM de maestros. Es el criterio de terminado de F2 en el ROADMAP.

Cada ABM se recorre entero —alta, listado, edición y baja— y además se prueba
lo que **no** tiene que dejar hacer: la unicidad, el acceso sin sesión y las
reglas propias de cada tabla. Un ABM que sólo prueba el camino feliz pasa igual
teniendo la validación rota.
"""

import os

import pytest
from fastapi.testclient import TestClient
from libraauth.models import Base as AuthBase

from app.config import Config
from app.main import crear_app

USUARIO, CLAVE = "admin", "clave-de-prueba"

#: Un cuerpo mínimo válido por maestro, para no repetirlo en cada test.
MINIMOS = {
    "terceros": {"razon_social": "Transportes del Sur", "es_cliente": True},
    "localidades": {"nombre": "Suipacha"},
    "choferes": {"nombre": "Juan Perez"},
    "vehiculos": {"patente_chasis": "AB123CD"},
    "razones-sociales": {"nombre": "Suitrans"},
    "tipos-carga": {"nombre": "Cereal"},
}
#: Con qué campo se distingue una fila de otra en cada maestro.
ETIQUETA = {
    "terceros": "razon_social", "localidades": "nombre", "choferes": "nombre",
    "vehiculos": "patente_chasis", "razones-sociales": "nombre", "tipos-carga": "nombre",
}


@pytest.fixture
def cliente(engine, sesion, monkeypatch):
    """Un cliente ya logueado. `https` porque la cookie de sesión es `Secure`.

    Depende de `sesion` **por su limpieza**, no por usarla: ese fixture trunca
    las tablas del dominio al terminar. Sin eso las filas se acumulan entre
    tests y los síntomas no se parecen a la causa — un listado con filas de
    más, y un alta que choca contra un duplicado del test anterior.
    """
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("LIBRACARGO_ADMIN_USERNAME", USUARIO)
    monkeypatch.setenv("LIBRACARGO_ADMIN_PASSWORD", CLAVE)
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    c = TestClient(crear_app(cfg), base_url="https://testserver")
    r = c.post("/auth/login", json={"username": USUARIO, "password": CLAVE})
    assert r.status_code == 200, r.text
    yield c
    AuthBase.metadata.drop_all(engine)


@pytest.mark.parametrize("recurso", list(MINIMOS))
def test_sin_sesion_no_se_entra(recurso, engine, monkeypatch):
    """El control que hace que los demás signifiquen algo.

    Sin esto, los tests de abajo pasarían igual con los routers montados sin
    ninguna dependencia de autenticación, y los maestros quedarían abiertos.
    """
    monkeypatch.setenv("ENV", "development")
    AuthBase.metadata.drop_all(engine)
    AuthBase.metadata.create_all(engine)
    cfg = Config(database_url=os.environ["DATABASE_URL"], entorno="test", debug=False)
    anonimo = TestClient(crear_app(cfg, sembrar_admin=False), base_url="https://testserver")
    try:
        assert anonimo.get(f"/api/{recurso}").status_code == 401
    finally:
        AuthBase.metadata.drop_all(engine)


@pytest.mark.parametrize("recurso", list(MINIMOS))
def test_el_ciclo_completo_de_cada_abm(cliente, recurso):
    campo = ETIQUETA[recurso]
    cuerpo = dict(MINIMOS[recurso])

    alta = cliente.post(f"/api/{recurso}", json=cuerpo)
    assert alta.status_code == 201, alta.text
    creado = alta.json()
    id_ = creado["id"]
    assert creado["activo"] is True

    listado = cliente.get(f"/api/{recurso}").json()
    assert [x["id"] for x in listado] == [id_]

    uno = cliente.get(f"/api/{recurso}/{id_}")
    assert uno.status_code == 200
    assert uno.json()[campo] == creado[campo]

    editado = dict(cuerpo)
    editado[campo] = "ZZ999ZZ" if recurso == "vehiculos" else "Nombre Cambiado"
    r = cliente.put(f"/api/{recurso}/{id_}", json=editado)
    assert r.status_code == 200, r.text
    assert r.json()[campo] == editado[campo]

    baja = cliente.delete(f"/api/{recurso}/{id_}")
    assert baja.status_code == 200
    assert baja.json()["activo"] is False
    # Baja LÓGICA: la fila sigue existiendo. Si algún día esto empieza a dar
    # 404, alguien cambió el borrado y se está llevando el historial.
    assert cliente.get(f"/api/{recurso}/{id_}").status_code == 200


@pytest.mark.parametrize("recurso", list(MINIMOS))
def test_el_listado_por_defecto_muestra_tambien_los_dados_de_baja(cliente, recurso):
    """`activo` sin valor es *todos*, y tiene que serlo.

    Con un default en `True`, la fila dada de baja desaparece de la única
    pantalla desde la que se la puede volver a activar.
    """
    id_ = cliente.post(f"/api/{recurso}", json=MINIMOS[recurso]).json()["id"]
    cliente.delete(f"/api/{recurso}/{id_}")
    assert [x["id"] for x in cliente.get(f"/api/{recurso}").json()] == [id_]
    assert cliente.get(f"/api/{recurso}?activo=true").json() == []
    assert [x["id"] for x in cliente.get(f"/api/{recurso}?activo=false").json()] == [id_]


@pytest.mark.parametrize(
    "recurso", ["localidades", "razones-sociales", "tipos-carga", "vehiculos"]
)
def test_el_duplicado_es_409_y_no_un_500(cliente, recurso):
    """Las cuatro tablas con unicidad declarada.

    Sin traducir el error de integridad, esto sale como 500 con el traceback de
    psycopg — que arrastra el statement completo, o sea los valores de la fila.
    """
    assert cliente.post(f"/api/{recurso}", json=MINIMOS[recurso]).status_code == 201
    choque = cliente.post(f"/api/{recurso}", json=MINIMOS[recurso])
    assert choque.status_code == 409, choque.text
    detalle = choque.json()["detail"]
    assert "restriccion" in detalle
    # El mensaje nombra la restricción y nada más: ni el statement ni los datos.
    assert MINIMOS[recurso][ETIQUETA[recurso]] not in detalle


@pytest.mark.parametrize("recurso,columna", [("localidades", "activa"),
                                             ("razones-sociales", "activa")])
def test_activo_es_uniforme_en_la_api_aunque_la_columna_sea_activa(
    cliente, sesion, recurso, columna
):
    """Las dos tablas donde el nombre difiere, en las dos direcciones.

    Se mira la columna real, no sólo lo que devuelve la API: si el mapeo
    estuviera escribiendo en otro lado, la respuesta podría decir `false` y la
    base seguir en `true`.
    """
    from sqlalchemy import text

    id_ = cliente.post(f"/api/{recurso}", json=MINIMOS[recurso]).json()["id"]
    tabla = "localidades" if recurso == "localidades" else "razones_sociales"

    def leer():
        return sesion.execute(
            text(f"select {columna} from {tabla} where id = :i"), {"i": id_}
        ).scalar_one()

    assert leer() is True
    assert cliente.delete(f"/api/{recurso}/{id_}").json()["activo"] is False
    sesion.commit()
    assert leer() is False


def test_un_tercero_sin_ningun_rol_no_se_puede_dar_de_alta(cliente):
    """En el legado eran tres maestros y el rol era implícito.

    Acá la tabla es una sola, así que un tercero sin rol es una fila que existe,
    no aparece en ninguna pantalla, y nadie entiende por qué.
    """
    r = cliente.post("/api/terceros", json={"razon_social": "Sin Rol SA"})
    assert r.status_code == 422
    assert "cliente, fletero o proveedor" in r.text


def test_el_filtro_por_rol(cliente):
    cliente.post("/api/terceros", json={"razon_social": "Cliente SA", "es_cliente": True})
    cliente.post("/api/terceros", json={"razon_social": "Fletero SRL", "es_fletero": True})

    clientes = cliente.get("/api/terceros/rol/cliente").json()
    assert [t["razon_social"] for t in clientes] == ["Cliente SA"]
    fleteros = cliente.get("/api/terceros/rol/fletero").json()
    assert [t["razon_social"] for t in fleteros] == ["Fletero SRL"]
    assert cliente.get("/api/terceros/rol/chofer").status_code == 404


def test_la_patente_se_guarda_en_mayusculas(cliente):
    """Y por eso el mismo camión en minúscula choca en vez de entrar dos veces."""
    r = cliente.post("/api/vehiculos", json={"patente_chasis": "ab123cd"})
    assert r.status_code == 201
    assert r.json()["patente_chasis"] == "AB123CD"
    assert cliente.post("/api/vehiculos", json={"patente_chasis": "Ab123Cd"}).status_code == 409


def test_un_texto_vacio_se_guarda_como_ausencia(cliente):
    """`""` y `NULL` no son lo mismo para una restricción de unicidad.

    Dos altas sin CUIT guardando `''` chocarían entre sí; con `NULL` no, porque
    en PostgreSQL `NULL` no colisiona con `NULL`.
    """
    r = cliente.post(
        "/api/terceros", json={"razon_social": "Sin CUIT", "cuit": "   ", "es_cliente": True}
    )
    assert r.status_code == 201
    assert r.json()["cuit"] is None


def test_la_busqueda_mira_varios_campos(cliente):
    cliente.post("/api/terceros", json={"razon_social": "Agro Norte", "es_cliente": True,
                                        "localidad": "Chivilcoy"})
    cliente.post("/api/terceros", json={"razon_social": "Otro SA", "es_cliente": True})
    assert len(cliente.get("/api/terceros?q=chivil").json()) == 1   # por localidad
    assert len(cliente.get("/api/terceros?q=agro").json()) == 1     # por razon social
    assert len(cliente.get("/api/terceros?q=nada-de-esto").json()) == 0


def test_lo_que_no_existe_da_404(cliente):
    assert cliente.get("/api/terceros/999999").status_code == 404
    assert cliente.put("/api/terceros/999999", json=MINIMOS["terceros"]).status_code == 404
    assert cliente.delete("/api/terceros/999999").status_code == 404
