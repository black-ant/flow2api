"""Flow2API - Main Entry Point"""
import logging

import click
import uvicorn

from src.main import app


class DisplayHostServer(uvicorn.Server):
    """Keep the bind host unchanged, but print a friendlier local URL."""

    def _log_started_message(self, listeners):
        if self.config.fd is not None or self.config.uds is not None:
            return super()._log_started_message(listeners)

        addr_format = "%s://%s:%d"
        host = self.config.host or "0.0.0.0"
        display_host = "127.0.0.1" if host == "0.0.0.0" else host
        if ":" in display_host:
            addr_format = "%s://[%s]:%d"

        port = self.config.port
        if port == 0:
            port = listeners[0].getsockname()[1]

        protocol_name = "https" if getattr(self.config, "ssl", None) else "http"
        message = f"Uvicorn running on {addr_format} (Press CTRL+C to quit)"
        color_message = (
            "Uvicorn running on "
            + click.style(addr_format, bold=True)
            + " (Press CTRL+C to quit)"
        )
        logging.getLogger("uvicorn.error").info(
            message,
            protocol_name,
            display_host,
            port,
            extra={"color_message": color_message},
        )

if __name__ == "__main__":
    from src.core.config import config

    server = DisplayHostServer(
        uvicorn.Config(
            app,
            host=config.server_host,
            port=config.server_port,
            reload=False,
        )
    )
    server.run()
