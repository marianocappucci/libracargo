"""La barra de estado del pie (libracore ADR-075, libra-ui ADR-083): `GET /api/estado-del-sistema` está montada y,
para el admin, trae el respaldo y la versión del motor."""


def test_el_admin_ve_respaldo_y_version_del_motor(cliente):
    r = cliente.get("/api/estado-del-sistema")
    assert r.status_code == 200
    datos = r.json()
    assert datos["usuario"]["rol"] == "admin" and datos["libraedge"] is None
    assert datos["respaldo"] is not None and datos["version"]["motor"]
