"""Contratos de la puerta de entrada del dashboard: quien ve el login y quien ve la app."""

from __future__ import annotations

import dash
import pytest
from dash import dcc
from flask import session as flask_session

from config.users import USERS
from dashboard.auth import (
    IDENTITY_PROOF_FIELD,
    add_identity_proof,
    current_dashboard_user_data,
)
from dashboard.callbacks.auth_callbacks import register_auth_callbacks
from dashboard.layout import create_app_layout


ADMIN = next(name for name, user in USERS.items() if user.get("role") == "admin")


@pytest.fixture
def client():
    """Un Dash real con el layout y los callbacks de autenticacion de produccion.

    El layout se asigna como callable, igual que `dashboard/app.py`: es lo que permite que
    `user-info-store` nazca con la identidad de la sesion activa.
    """
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.layout = create_app_layout
    app.server.secret_key = "test-secret-key-with-enough-entropy"
    register_auth_callbacks(app)
    app.server.testing = True
    with app.server.test_client() as test_client:
        test_client.get("/")  # fuerza el setup del servidor y el mapa de callbacks
        test_client.dash_app = app
        yield test_client


def _login(test_client, username):
    with test_client.session_transaction() as session:
        session["dashboard_user"] = username


def _page_for(test_client, store_data):
    """Que devuelve `display_page` para ese valor de user-info-store."""
    response = test_client.post(
        "/_dash-update-component",
        json={
            "output": "page-content.children",
            "outputs": {"id": "page-content", "property": "children"},
            "inputs": [
                {"id": "user-info-store", "property": "data", "value": store_data}
            ],
            "changedPropIds": ["user-info-store.data"],
        },
    )
    assert response.status_code == 200
    return "login" if "login-button" in response.get_data(as_text=True) else "dashboard"


def _seeded_store(test_client):
    """El `data` con que sale user-info-store en la respuesta de _dash-layout."""

    def find(node):
        if isinstance(node, dict):
            props = node.get("props", {})
            if props.get("id") == "user-info-store":
                return props.get("data")
            for value in props.values():
                found = find(value)
                if found is not None:
                    return found
        if isinstance(node, list):
            for value in node:
                found = find(value)
                if found is not None:
                    return found
        return None

    response = test_client.get("/_dash-layout")
    assert response.status_code == 200
    return find(response.get_json())


def test_a_visitor_without_a_session_gets_the_login_page(client):
    assert _page_for(client, None) == "login"


def test_a_fresh_tab_of_an_authenticated_user_gets_the_dashboard(client):
    """La regresion que dejaba el despliegue pegado en el login.

    `user-info-store` es `storage_type='session'`, o sea sessionStorage, que es *por pestana*.
    Una pestana nueva o un enlace directo llegan sin nada, aunque la cookie de sesion de Flask
    identifique perfectamente al usuario. El gate de `display_page` exige el proof firmado, asi
    que sin reemitirlo desde la sesion un usuario autenticado veia el formulario de login una y
    otra vez, y el log decia las dos cosas a la vez: "authenticated_user: admin" y
    "Showing login page".
    """
    _login(client, ADMIN)
    assert _page_for(client, None) == "dashboard"


def test_a_tab_carrying_user_data_without_a_proof_gets_the_dashboard(client):
    """El otro origen del mismo sintoma, y el que no se arregla sembrando el layout.

    Una pestana que guardo datos de usuario antes de que el proof existiera trae un dict sin
    `_identity_proof`, y `dcc.Store` le da precedencia a lo que ya tiene sessionStorage sobre
    el `data` que trae el layout. La reemision en `display_page` es lo que cubre este caso.
    """
    _login(client, ADMIN)
    user = USERS[ADMIN]
    stale = {
        "username": ADMIN,
        "name": user.get("name", ADMIN),
        "role": user.get("role"),
        "clients": user.get("clients", []),
    }
    assert IDENTITY_PROOF_FIELD not in stale
    assert _page_for(client, stale) == "dashboard"


def test_user_data_without_a_proof_is_not_enough_on_its_own(client):
    """Y el gate no se ablanda: sin sesion en el servidor, un dict sin firma no entra.

    Este es el caso que separa "reemitir un proof para alguien que el servidor ya reconoce" de
    "creerle al navegador lo que dice ser". Sin la cookie, el mismo dict del test anterior tiene
    que quedarse afuera.
    """
    stale = {"username": ADMIN, "name": "quien sea", "role": "admin", "clients": []}
    assert _page_for(client, stale) == "login"


def test_a_session_naming_an_unknown_user_gets_the_login_page(client):
    _login(client, "no-existe")
    assert _page_for(client, None) == "login"
    assert _seeded_store(client) is None


def test_the_root_layout_seeds_the_store_from_the_active_session(client):
    """La otra mitad del fix: el store nace con identidad, no en None.

    Importa mas alla de `display_page` -- varios callbacks leen `user-info-store` (el selector
    de clientes, el sidebar, las paginas de predictivo), y con el store vacio reciben None en
    la primera carga de cada pestana.
    """
    assert _seeded_store(client) is None  # sin sesion, nada que sembrar

    _login(client, ADMIN)
    seeded = _seeded_store(client)
    assert isinstance(seeded, dict)
    assert seeded["username"] == ADMIN
    assert seeded[IDENTITY_PROOF_FIELD]


def test_the_root_layout_must_stay_callable_to_be_able_to_read_the_session():
    """`app.layout = create_app_layout()` -- con parentesis -- vuelve a romper todo lo de arriba.

    Evaluado al importar no hay request context, `current_dashboard_user_data()` devuelve None y
    el store queda fijo en ese None para todos los visitantes. El sintoma no seria un error sino
    el login otra vez, asi que conviene que falle aca.
    """
    import dashboard.app as dashboard_app

    assert callable(dashboard_app.app.layout), (
        "dashboard/app.py debe asignar el callable create_app_layout, no su resultado"
    )

    # Y sin request context el sembrado se degrada a None en vez de reventar.
    store = next(
        child
        for child in create_app_layout().children
        if isinstance(child, dcc.Store) and child.id == "user-info-store"
    )
    assert store.data is None


def test_logging_out_survives_the_reissue(client):
    """El riesgo que introduce reemitir el proof: que ya no se pueda salir.

    `display_page` ahora reconstruye la identidad cuando el navegador no trae proof, y despues
    del logout el store queda justamente en None. Si el logout no limpiara la sesion de Flask,
    la reemision devolveria al usuario al dashboard y cerrar sesion seria imposible.
    """
    _login(client, ADMIN)
    assert _page_for(client, None) == "dashboard"

    # La clave del logout lleva el hash de `allow_duplicate`, asi que se busca en vez de
    # escribirse a mano: un hash pegado en el test se rompe con cualquier cambio de firma.
    key = next(
        k
        for k in client.dash_app.callback_map
        if "user-info-store.data@" in k and "erp-validator-operator-store" in k
    )
    response = client.post(
        "/_dash-update-component",
        json={
            "output": key,
            "outputs": [
                {"id": "user-info-store", "property": "data"},
                {"id": "erp-validator-operator-store", "property": "data"},
            ],
            "inputs": [
                {"id": "logout-button", "property": "n_clicks", "value": 1}
            ],
            "changedPropIds": ["logout-button.n_clicks"],
        },
    )
    assert response.status_code == 200

    assert _page_for(client, None) == "login"
    assert _seeded_store(client) is None


def test_the_reissued_identity_matches_a_freshly_signed_one(client):
    """Lo que se reemite es lo mismo que emitiria un login, no una version recortada."""
    _login(client, ADMIN)
    with client.application.test_request_context("/"):
        flask_session["dashboard_user"] = ADMIN
        reissued = current_dashboard_user_data()
        user = USERS[ADMIN]
        signed = add_identity_proof(
            {
                "username": ADMIN,
                "name": user.get("name", ADMIN),
                "role": user.get("role"),
                "clients": user.get("clients", []),
            }
        )

    assert set(reissued) == set(signed)
    assert {k: v for k, v in reissued.items() if k != IDENTITY_PROOF_FIELD} == {
        k: v for k, v in signed.items() if k != IDENTITY_PROOF_FIELD
    }
