# CS2 Analytics Engine

A small analytics stack for Counter-Strike 2 data: a Steam Community Market price-tracking scraper, a FastAPI read API, a static dashboard, deployed via Helm to Kubernetes (developed against Minikube) with Prometheus/Grafana observability.

## Architecture

```
                        ┌─────────────────────┐
                        │ Steam Community Market│
                        └──────────┬───────────┘
                                   │ (CronJob, every 10 min)
                                   ▼
┌────────────┐   pg    ┌──────────────────┐   SELECT   ┌────────────┐   proxy   ┌────────────┐
│ Postgres    │◄───────│  scraper          │            │  api        │◄─────────│  frontend   │
│ (StatefulSet)│───────►│  (CronJob)        │            │ (FastAPI)   │  /api/*  │ (nginx)     │
└────────────┘         └──────────────────┘   ┌────────►└────────────┘           └────────────┘
                                                │ scrapes /metrics
                                          ┌─────┴──────┐
                                          │ Prometheus  │──► Grafana
                                          └────────────┘
```

All four services are deployed as one Helm release (`charts/cs2-analytics`). An NGINX Ingress
routes `cs2.<ip>.sslip.io`, `api.<ip>.sslip.io`, `grafana.<ip>.sslip.io`,
`prometheus.<ip>.sslip.io`, and `alerts.<ip>.sslip.io` to the frontend, API, and monitoring stack
respectively — no hosts-file editing required (see "DNS" below).

## Directory layout

- `api/` — FastAPI service, single read endpoint `GET /api/stats` (behind an API key), `/healthz` + `/readyz` probes, `/metrics` for Prometheus.
- `scraper/app/` — Steam Community Market price-overview client, transform, and DB-insert modules, run as a Kubernetes CronJob (writes time-series rows to `market_data` for Grafana charting). `scraper/tests/` has the pytest suite for the transform logic.
- `frontend/` — static HTML/JS dashboard served by nginx, which also reverse-proxies `/api/*` to the API service (same-origin, so the browser never needs the API key).
- `charts/cs2-analytics/` — the Helm chart for the whole stack (all k8s manifests live here as templates; there is no separate raw-manifest directory).
- `.github/workflows/deploy.yml` — CI: Dockerfile lint (hadolint) + Helm lint on every push/PR, build + Trivy scan per service, push + (currently commented-out) Helm deploy on push to `main`.

## Local setup (Minikube)

1. **Cluster + registry**: `minikube start`, then build and load the 3 images so they're usable with `imagePullPolicy: Never`:
   ```
   docker build -t cs2_analytics-api:latest ./api
   docker build -t cs2_analytics-scraper:latest ./scraper
   docker build -t cs2_analytics-frontend:latest ./frontend
   minikube image load cs2_analytics-api:latest
   minikube image load cs2_analytics-scraper:latest
   minikube image load cs2_analytics-frontend:latest
   ```
2. **Ingress**: `minikube addons enable ingress` (see `ingress_instructions.txt`).
3. **Secrets**: override the placeholder values before deploying — at minimum `postgres.password` and `security.apiKey`. The items tracked by the scraper are configured via `scraper.marketItems` (a list of Steam Market `market_hash_name` strings; 5 sensible defaults are already set in `values.yaml`):
   ```
   helm upgrade --install cs2-analytics ./charts/cs2-analytics \
     --set postgres.password=<your-password> \
     --set security.apiKey=<your-api-key>
   ```
4. **Monitoring** (optional): see `monitoring_instructions.txt` for installing `kube-prometheus-stack` and importing `grafana-dashboard.json`.

## DNS — no hosts-file editing

The ingress hostnames are [sslip.io](https://sslip.io) addresses that encode the Minikube IP directly (e.g. `cs2.192-168-49-2.sslip.io` resolves to `192.168.49.2` over real public DNS). If your Minikube IP differs from `192.168.49.2`, update the `*Host` fields in `charts/cs2-analytics/values.yaml` and regenerate `charts/cs2-analytics/templates/tls-secret.yaml`'s cert SANs to match before deploying.

## Tests

```
cd scraper
pip install -r requirements-dev.txt
pytest tests/
```

## Security notes

- Every container runs as a non-root user with `readOnlyRootFilesystem` where feasible.
- `postgres.password` and `security.apiKey` in `values.yaml` are placeholders — override them at deploy time (`--set` or a private values file); don't commit real values. Migrating these to [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) is the natural next step so encrypted values can be committed safely.
- The TLS cert in `templates/tls-secret.yaml` is self-signed; browsers will warn. [mkcert](https://github.com/FiloSottile/mkcert) is the recommended free upgrade to eliminate that warning locally.
