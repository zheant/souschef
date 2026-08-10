FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" \
    "pydantic-settings>=2.3" "sqlalchemy>=2.0" "alembic>=1.13" \
    "psycopg2-binary>=2.9" "pulp>=2.8"
COPY . .
EXPOSE 8000
