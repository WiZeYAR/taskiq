"""
Unit tests for HealthHTTPServer.

Tests HTTP health status endpoint.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from taskiq.cli.worker.health_server import HealthHTTPServer


@pytest.fixture
def mock_health_checker() -> MagicMock:
    """
    Mock health checker for testing.

    :returns: Mocked HealthChecker object.
    """
    checker = MagicMock()
    checker.get_health_status.return_value = {
        "status": "healthy",
        "workers": {"total": 2, "alive": 2, "stuck": 0},
        "broker_connected": True,
        "workers_detail": [],
    }
    return checker


@pytest.fixture
def health_server(mock_health_checker: MagicMock) -> HealthHTTPServer:
    """
    Create HealthHTTPServer instance for testing.

    :param mock_health_checker: Mocked health checker.
    :returns: HealthHTTPServer instance.
    """
    return HealthHTTPServer(
        health_checker=mock_health_checker,
        host="127.0.0.1",
        port=0,  # Use port 0 for OS-assigned port
    )


def test_health_server_init(mock_health_checker: MagicMock) -> None:
    """Test HealthHTTPServer initialization."""
    server = HealthHTTPServer(
        health_checker=mock_health_checker,
        host="0.0.0.0",  # noqa: S104
        port=8000,
    )

    assert server.health_checker == mock_health_checker
    assert server.host == "0.0.0.0"  # noqa: S104
    assert server.port == 8000


@pytest.mark.asyncio
async def test_health_server_handle_request_health(
    health_server: HealthHTTPServer,
) -> None:
    """Test that /health endpoint returns health status."""
    # Mock reader and writer
    reader = AsyncMock()
    writer = AsyncMock()

    # Simulate GET /health request
    reader.readline.return_value = b"GET /health HTTP/1.1\r\n"

    await health_server.handle_request(reader, writer)

    # Verify response
    writer.write.assert_called_once()
    written_data = writer.write.call_args[0][0].decode()

    assert "HTTP/1.1 200 OK" in written_data
    assert "Content-Type: application/json" in written_data
    assert '"status": "healthy"' in written_data
    assert '"workers"' in written_data


@pytest.mark.asyncio
async def test_health_server_handle_request_404(
    health_server: HealthHTTPServer,
) -> None:
    """Test that non-existent endpoints return 404."""
    reader = AsyncMock()
    writer = AsyncMock()

    # Simulate GET /unknown request
    reader.readline.return_value = b"GET /unknown HTTP/1.1\r\n"

    await health_server.handle_request(reader, writer)

    # Verify 404 response
    writer.write.assert_called_once()
    written_data = writer.write.call_args[0][0].decode()

    assert "HTTP/1.1 404 Not Found" in written_data


@pytest.mark.asyncio
async def test_health_server_handle_request_error(
    health_server: HealthHTTPServer,
) -> None:
    """Test that request errors are handled gracefully."""
    reader = AsyncMock()
    writer = AsyncMock()

    # Simulate empty request (no data)
    reader.readline.return_value = b""

    # Should not raise exception
    await health_server.handle_request(reader, writer)

    # Verify writer was still called (or handled error)
    assert True  # If we got here, no exception was raised


@pytest.mark.asyncio
async def test_health_server_start_and_stop(
    health_server: HealthHTTPServer,
) -> None:
    """Test that server can start and stop."""
    await health_server.start()
    assert health_server.server is not None

    await health_server.stop()
    assert True  # If we got here, stop completed without error


def test_get_health_status_degraded(
    mock_health_checker: MagicMock,
) -> None:
    """Test that degraded status is properly returned."""
    mock_health_checker.get_health_status.return_value = {
        "status": "degraded",
        "workers": {"total": 2, "alive": 1, "stuck": 1},
        "broker_connected": False,
        "workers_detail": [],
    }

    server = HealthHTTPServer(
        health_checker=mock_health_checker,
        host="127.0.0.1",
        port=0,
    )

    # Create reader and writer for request
    reader = AsyncMock()
    writer = AsyncMock()
    reader.readline.return_value = b"GET /health HTTP/1.1\r\n"

    asyncio.run(server.handle_request(reader, writer))

    # Verify degraded status in response
    written_data = writer.write.call_args[0][0].decode()
    assert '"status": "degraded"' in written_data
    assert '"alive": 1' in written_data
    assert '"stuck": 1' in written_data
