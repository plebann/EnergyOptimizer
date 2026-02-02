"""Pytest configuration for tests."""
import asyncio
import socket as _socket_module
import sys

import pytest

# Save the real socket.socket before pytest-socket replaces it
_original_socket = _socket_module.socket
_original_socketpair = getattr(_socket_module, "socketpair", None)


def _restore_socket_module() -> None:
    """Restore socket module functions patched by pytest-socket."""
    _socket_module.socket = _original_socket
    if _original_socketpair is not None:
        _socket_module.socketpair = _original_socketpair


def pytest_load_initial_conftests(early_config, parser, args):
    """Restore socket before plugins initialize."""
    # Restore original socket to bypass pytest-socket blocking
    _restore_socket_module()


def pytest_configure(config):
    """Configure pytest."""
    # Ensure socket is restored
    _restore_socket_module()
    plugin_manager = config.pluginmanager
    plugin_manager.set_blocked("pytest_socket")
    plugin_manager.set_blocked("socket")
    pytest_socket_plugin = plugin_manager.get_plugin("pytest_socket")
    if pytest_socket_plugin is not None:
        plugin_manager.unregister(pytest_socket_plugin)
    config.addinivalue_line("markers", "unit: Simple unit tests without async/network requirements")


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef, request):
    """Restore socket before fixtures are created."""
    if fixturedef.argname == "event_loop":
        _restore_socket_module()


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_post_finalizer(fixturedef, request):
    """Restore socket after fixtures teardown."""
    if fixturedef.argname == "event_loop":
        _restore_socket_module()


@pytest.fixture(autouse=True, scope="session")
def _restore_socket_session():
    """Restore socket for the entire test session to bypass pytest-socket."""
    _restore_socket_module()
    yield
    _restore_socket_module()


@pytest.fixture(scope="session")
def event_loop_policy():
    """Return the event loop policy for pytest-asyncio."""
    return asyncio.DefaultEventLoopPolicy()

