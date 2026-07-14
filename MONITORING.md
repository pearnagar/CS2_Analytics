# CS2 Analytics — Observability Guide

Covers the Prometheus Operator resources added to `charts/cs2-analytics/templates/`: `prometheusrule.yaml`, `alertmanagerconfig.yaml`, `grafana-dashboard-platform.yaml`. These integrate with the existing `kube-prometheus-stack` release (Helm release name **`prometheus`** in this cluster — not the chart's default name; every new CRD below carries `release: prometheus` specifically to match that release's `ruleSelector`/`alertmanagerConfigSelector`).

## Known gaps in this setup (read before trusting the panels)

- **No `postgres_exporter`.** `DatabaseDown` and any DB-health signal here comes from `kube-state-metrics`'s view of pod readiness (`cs2-db-0`'s `pg_isready` probe), not from Postgres internals. There's no visibility into connection counts, replication, query latency, etc. Adding `prometheus-community/postgres-exporter` is the natural next step if that's needed.
- **No Postgres Grafana datasource.** The "business metrics" panel doesn't query `market_data` via SQL — it queries `cs2_market_lowest_price_usd`/`cs2_market_volume`, Prometheus gauges that `cs2-api`'s custom collector (`api/main.py`) computes from `market_data` on every `/metrics` scrape. Same underlying data, different path — SQL panels would need a separate Postgres datasource provisioned into Grafana, which doesn't exist in this cluster.
- **Job history is bounded.** "Last N scraper runs" is really "however many Job objects `kube-state-metrics` can currently see," which is capped by `successfulJobsHistoryLimit`/`failedJobsHistoryLimit` (now 10/10, bumped from 3/3 as part of this change — see `scraper.successfulJobsHistoryLimit`/`scraper.failedJobsHistoryLimit` in `values.yaml`). Once a Job ages out of that limit, Kubernetes garbage-collects it and its metrics disappear with it.
- **Slack webhook is a mock placeholder** (`monitoring.alerts.slackWebhookUrl` in `values.yaml`) — `https://hooks.slack.com/services/REPLACE/ME/WITH_REAL_WEBHOOK`. Alertmanager will attempt real HTTP POSTs to it and fail silently (visible in Alertmanager's own logs) until you override it with a real incoming-webhook URL.

## Metrics reference

| Metric | Source | Used for |
|---|---|---|
| `kube_job_status_failed` | kube-state-metrics | `ScraperJobFailed` alert, failure-count stat panel |
| `kube_job_status_succeeded` | kube-state-metrics | success-count stat panel, success-rate panel |
| `kube_job_status_active` | kube-state-metrics | "active runs right now" stat panel |
| `kube_pod_status_ready{condition="true"}` | kube-state-metrics | `DatabaseDown` alert |
| `kube_pod_container_status_restarts_total` | kube-state-metrics | `PodCrashLooping` alert |
| `http_requests_total`, rate + status label | `prometheus-fastapi-instrumentator` (cs2-api `/metrics`) | `HighApiErrorRate` alert, RED "errors" |
| `container_cpu_usage_seconds_total` | cAdvisor (via kubelet, scraped by kube-prometheus-stack by default) | CPU panel |
| `container_memory_working_set_bytes` | cAdvisor | Memory panel |
| `cs2_market_lowest_price_usd`, `cs2_market_volume` | custom collector in `api/main.py`, reads `market_data` per scrape | business-metrics panel |

Golden Signals / RED mapping: `HighApiErrorRate` = Errors, the API's existing `p95 request latency` panel (from the original `grafana-dashboard.json`) = Duration/Latency, `http_requests_total` rate = Rate/Traffic. `PodCrashLooping` and `DatabaseDown` are Saturation/Availability signals at the infra layer, not RED in the strict sense (nothing upstream of them is "requests").

## Applying

```powershell
helm upgrade --install cs2-analytics ./charts/cs2-analytics --set monitoring.alerts.slackWebhookUrl=<your-real-webhook>
```

Verify the Operator picked everything up:

```powershell
kubectl get prometheusrule cs2-analytics-rules
kubectl get alertmanagerconfig cs2-analytics-routes
kubectl get configmap cs2-platform-overview-dashboard -o jsonpath='{.metadata.labels}'
```

Then in Prometheus (`kubectl port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090`), check **Status → Rules** for the four new alert rules, and **Status → Config** → Alertmanager tab (or the Alertmanager UI directly) to confirm the route tree loaded. In Grafana, the dashboard should appear automatically within the sidecar's poll interval (usually under a minute) — search for "CS2 Platform Overview".

## Testing the alerts

**`PodCrashLooping`** — cheapest one to trigger on purpose:
```powershell
kubectl exec cs2-api-<pod-suffix> -- sh -c "kill 1"
```
Repeat 4 times within 15 minutes (the container restarts each time due to `restartPolicy`) and the alert fires. Clean up by letting it stabilize — no state to revert.

**`ScraperJobFailed`** — already firing in this cluster's actual current state (Steam Market API rate-limiting has caused every recent scraper run to fail) — check `kubectl get jobs | grep cs2-scraper` for `Failed` entries, and the alert should already be active in Prometheus. This one didn't need to be manufactured.

**`HighApiErrorRate`** — hardest to trigger safely without touching production code, since there's no existing endpoint that deliberately 500s. Simplest non-destructive option: temporarily scale `cs2-db` to 0 replicas (`kubectl scale statefulset/cs2-db --replicas=0`), which makes `/api/market` return `503`s (a 5xx, matching the alert's `status=~"5.."` matcher) as soon as its connection retries exhaust. **Scale it back to 1 immediately after confirming the alert** — this also indirectly exercises `DatabaseDown`.

**`DatabaseDown`** — same action as above (`kubectl scale statefulset/cs2-db --replicas=0`) triggers this one directly and immediately, since `cs2-db-0` disappears entirely (hits the `absent()` branch of the alert expression). Scale back to 1 to restore.

After any test, confirm resolution in Alertmanager's UI (`kubectl port-forward svc/prometheus-kube-prometheus-alertmanager 9093:9093`) — a resolved alert should show a "resolved" notification in Slack too, since `sendResolved: true` is set on the receiver.
