import socket

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--scope-address",
        default="192.168.0.9",
        help="IP/hostname of the real scope used by hardware tests",
    )


@pytest.fixture(scope="session")
def scope_address(request):
    return request.config.getoption("--scope-address")


def _reachable(host: str) -> bool:
    try:
        with socket.create_connection((host, 111), timeout=3):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    hardware = [item for item in items if "hardware" in item.keywords]
    if not hardware:
        return
    host = config.getoption("--scope-address")
    if not _reachable(host):
        skip = pytest.mark.skip(reason=f"scope not reachable at {host}:111")
        for item in hardware:
            item.add_marker(skip)
