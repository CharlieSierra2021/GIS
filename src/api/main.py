"""FastAPI application entry point."""

from fastapi import FastAPI

from connectors.registry import load_registry


def create_app() -> FastAPI:
    app = FastAPI(title="property-intel")
    registry = load_registry()

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "registry_version": registry.registry_version,
            "activation": registry.activation,
        }

    return app


app = create_app()
