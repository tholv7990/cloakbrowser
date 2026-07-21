from manager_backend.config import ManagerSettings


def test_default_allowed_origin_matches_manager_frontend_dev_server() -> None:
    assert ManagerSettings().allowed_origin == "http://127.0.0.1:5273"
