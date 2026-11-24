# ReconLake Architecture

## System & Network Segmentation Diagram

ReconLake isolates services across segmented internal Docker networks (`ingest_net`, `data_net`, `serving_net`, `observability_net`). Only Traefik exposes TLS port `8443` on `proxy_net`.

```mermaid
graph TD
    subgraph proxy_net["Proxy Tier (Exposed TLS :8443)"]
        TR[Traefik + mkcert TLS]
    end

    subgraph ingest_net["Ingest Network (Internal)"]
        K[Kafka KRaft - No ZooKeeper]
        SW[SeaweedFS S3 API: bronze / silver / gold / quarantine]
    end

    subgraph data_net["Data Processing Network (Internal)"]
        SP[PySpark + Delta Lake]
        AF[Apache Airflow 2.10]
        PG[PostgreSQL 16 + RLS]
        OB[OpenBao Transit / Local Key Service]
        MQ[Marquez OpenLineage]
    end

    subgraph serving_net["Serving Network (Internal)"]
        SS[Apache Superset]
    end

    subgraph observability_net["Observability Network (Internal)"]
        PR[Prometheus]
        GR[Grafana]
        AM[Alertmanager]
    end

    TR -->|HTTPS| SS
    TR -->|HTTPS| GR
    K --> SP
    SP --> SW
    SP --> PG
    SP --> OB
    AF --> SP
    AF --> MQ
    AF --> AM
    PG --> SS
    PR --> SP
    PR --> AF
    PR --> PG
    PR --> AM
    GR --> PR
```
