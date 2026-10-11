"""FastAPI application entry point."""

from fastapi import FastAPI

from api.routes_jobs import build_router
from connectors.registry import load_registry
from workers import runtime
from workers.pipeline import JobRunner


def create_app(runner: JobRunner | None = None) -> FastAPI:
    app = FastAPI(title="property-intel")
    registry = load_registry()

    if runner is None:
        runner = runtime.get_runner() or runtime.build_default_runner()

    app.include_router(
        build_router(runner, runner.store, runner.audit, runner.evidence_store)
    )

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "registry_version": registry.registry_version,
            "activation": registry.activation,
        }

    return app


app = create_app()
