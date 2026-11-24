# ReconLake project identity

Goal: a secure, reconciliation-first UPI-style transaction lakehouse using ONLY free open-source tools.
Data: synthetic only. Never use or request real personal data.
Stack: Python 3.11, PySpark + Delta Lake, Kafka (KRaft), SeaweedFS (S3), Airflow, dbt Core, PostgreSQL, Superset, OpenLineage/Marquez, Prometheus/Grafana, OpenBao.
Banned: MinIO, proprietary or paid services, cloud accounts, real credentials.
How to work: always plan first, then implement in small commits, then run tests and show evidence.
Definition of done: code + tests + docs + passing CI + a verification artifact.
