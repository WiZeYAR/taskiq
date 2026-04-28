"""
HTTP server for worker health status.

Runs on the main process and exposes health status from HealthChecker.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from taskiq.cli.worker.health_checker import (
        HealthChecker,
        HealthStatus,
    )

logger = logging.getLogger("taskiq.health-server")


class HealthHTTPServer:
    """
    Simple HTTP server for health status endpoints.

    :param health_checker: HealthChecker instance to get status from.
    :param host: Host to bind to (default: 0.0.0.0).
    :param port: Port to bind to.
    """

    def __init__(
        self,
        health_checker: "HealthChecker",
        host: str = "0.0.0.0",  # noqa: S104
        port: int = 8000,
    ) -> None:
        self.health_checker = health_checker
        self.host = host
        self.port = port
        self.server: Any = None

    async def handle_request(self, reader: Any, writer: Any) -> None:
        """
        Handle incoming HTTP requests.

        :param reader: StreamReader for request.
        :param writer: StreamWriter for response.
        """
        try:
            request_line = await reader.readline()
            if not request_line:
                return

            parts = request_line.decode().strip().split()
            if len(parts) < 2:
                response = (
                    "HTTP/1.1 400 Bad Request\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(response.encode())
                await writer.drain()
                await writer.wait_closed()
                return

            method = parts[0]
            path = parts[1]

            if method == "GET" and path == "/health":
                status: HealthStatus = self.health_checker.get_health_status()
                response_body = json.dumps(status)
                http_status = (
                    "200 OK"
                    if status["status"] == "healthy"
                    else "503 Service Unavailable"
                )
                response = (
                    f"HTTP/1.1 {http_status}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    f"Connection: close\r\n"
                    f"\r\n"
                    f"{response_body}"
                )
            else:
                response = (
                    "HTTP/1.1 404 Not Found\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )

            writer.write(response.encode())
            await writer.drain()
            await writer.wait_closed()
        except Exception as e:
            logger.error(f"Error handling request: {e}")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as close_error:
                logger.debug(f"Error closing writer: {close_error}")

    async def start(self) -> None:
        """Start the HTTP server."""
        self.server = await asyncio.start_server(
            self.handle_request,
            self.host,
            self.port,
        )
        logger.info(
            f"Health check server listening on http://{self.host}:{self.port}/health",
        )
        async with self.server:
            await self.server.serve_forever()

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Health check server stopped")
