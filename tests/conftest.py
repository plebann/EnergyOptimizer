"""Pytest configuration for tests."""
import socket as _socket_module
import sys

# Save the real socket.socket before pytest-socket replaces it
_original_socket = _socket_module.socket


def pytest_load_initial_conftests(early_config, parser, args):
    """Restore socket before plugins initialize."""
    # Restore original socket to bypass pytest-socket blocking
    _socket_module.socket = _original_socket


def pytest_configure(config):
    """Configure pytest."""
    # Ensure socket is restored
    _socket_module.socket = _original_socket
    config.addinivalue_line("markers", "unit: Simple unit tests without async/network requirements")

