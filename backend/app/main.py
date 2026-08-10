"""Point d'entrée FastAPI — API v1 complète (étape 5).

La couche API expose des résultats calculés par les services ; le solveur et
la session sont injectés via app.api.deps (remplaçables sans toucher aux
routes). L'écart D1 (health seul à l'étape 1) est levé.
"""

from fastapi import FastAPI
from sqlalchemy import text

from .api.routes import router
from .db import engine

app = FastAPI(title="Menu Optimizer API", version="0.5.0")
app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
