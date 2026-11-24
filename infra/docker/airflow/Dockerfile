FROM apache/airflow:2.10.3-python3.11

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless=17.* \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    pydantic==2.9.2 \
    pyyaml==6.0.2 \
    jsonschema==4.23.0 \
    cryptography==50.0.0 \
    dbt-core==1.8.5 \
    dbt-postgres==1.8.5 \
    openlineage-airflow==1.24.0
