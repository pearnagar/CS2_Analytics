#!/usr/bin/env bash
# Automated setup + interactive diagnostics for the CS2 Analytics (Steam Market) stack.
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

NAMESPACE="default"
RELEASE="cs2-analytics"
CHART_PATH="./charts/cs2-analytics"
DB_POD="cs2-db-0"

declare -A PF_PIDS=()

log()  { echo -e "${BLUE}[run_project]${RESET} $*"; }
ok()   { echo -e "${GREEN}[ok]${RESET} $*"; }
warn() { echo -e "${YELLOW}[warn]${RESET} $*"; }
err()  { echo -e "${RED}[error]${RESET} $*" >&2; }

cleanup() {
  local key pid
  for key in "${!PF_PIDS[@]}"; do
    pid="${PF_PIDS[$key]}"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      log "Stopping ${key} port-forward (pid ${pid})..."
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    fi
  done
}
trap cleanup EXIT

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "'$1' is required but not found on PATH"; exit 1; }
}

# --- Setup ---

trigger_scraper_job() {
  local job_name="cs2-scraper-manual-$(date +%s)"
  log "Triggering manual scraper run '${job_name}' for initial test data..."
  kubectl create job --from=cronjob/cs2-scraper "$job_name" >/dev/null
  log "Waiting for it to finish (up to 5 minutes — Steam's Market API can be slow or rate-limited)..."
  if kubectl wait --for=condition=Complete "job/${job_name}" --timeout=300s >/dev/null 2>&1; then
    ok "Manual scraper run completed successfully."
  else
    warn "Manual scraper run did not finish cleanly — check logs with menu option [1]."
    warn "This is most often Steam Market API rate-limiting, not a bug in the pipeline."
  fi
}

setup_stack() {
  log "Deploying/upgrading Helm release '${RELEASE}'..."
  if ! helm upgrade --install "$RELEASE" "$CHART_PATH"; then
    err "helm upgrade failed — aborting."
    exit 1
  fi
  ok "Helm release deployed."

  log "Waiting for PostgreSQL (cs2-db StatefulSet) to be ready..."
  if ! kubectl rollout status statefulset/cs2-db --timeout=120s; then
    err "cs2-db did not become ready in time — aborting."
    exit 1
  fi
  ok "PostgreSQL is ready."

  log "Checking whether the market_data table exists..."
  local table_check
  table_check=$(kubectl exec "$DB_POD" -- psql -U admin -d cs2_stats -tAc "SELECT to_regclass('market_data');" 2>/dev/null | tr -d '[:space:]')
  if [ "$table_check" = "market_data" ]; then
    ok "market_data table exists."
  else
    warn "market_data table not found yet — it's created automatically on the scraper's first run."
  fi

  local row_count
  row_count=$(kubectl exec "$DB_POD" -- psql -U admin -d cs2_stats -tAc "SELECT COUNT(*) FROM market_data;" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$row_count" ] && [ "$row_count" -gt 0 ] 2>/dev/null; then
    # Skip triggering a fresh scrape if data already exists — Steam's Market API
    # rate-limits aggressively, and re-triggering on every script run compounds it.
    ok "market_data already has ${row_count} row(s) — skipping manual scrape to avoid unnecessary Steam API calls."
  else
    trigger_scraper_job
  fi
}

# --- Menu actions ---

view_scraper_logs() {
  log "Finding the most recent scraper pod..."
  local pod
  pod=$(kubectl get pods --sort-by=.metadata.creationTimestamp -o custom-columns=NAME:.metadata.name --no-headers 2>/dev/null | grep '^cs2-scraper' | tail -1)
  if [ -z "$pod" ]; then
    warn "No scraper pods found yet."
    return
  fi
  log "Streaming logs from ${pod} (Ctrl+C to stop and return to menu)..."
  kubectl logs -f "$pod" || true
}

connect_postgres() {
  log "Querying latest 10 rows from market_data on ${DB_POD}..."
  kubectl exec "$DB_POD" -- psql -U admin -d cs2_stats -c \
    "SELECT item_name, lowest_price, volume, scraped_at FROM market_data ORDER BY scraped_at DESC LIMIT 10;" \
    || warn "Query failed — the table may not exist yet."
}

launch_port_forward() {
  local key="$1" service="$2" local_port="$3" remote_port="$4" label="$5" note="${6:-}"
  local pid="${PF_PIDS[$key]:-}"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    ok "${label} port-forward already running (pid ${pid}) — http://localhost:${local_port}"
    return
  fi
  log "Starting port-forward to ${label}..."
  kubectl port-forward "svc/${service}" "${local_port}:${remote_port}" >"/tmp/run_project_${key}_pf.log" 2>&1 &
  pid=$!
  PF_PIDS[$key]=$pid
  sleep 2
  if kill -0 "$pid" 2>/dev/null; then
    ok "${label} available at: http://localhost:${local_port}${note:+  ($note)}"
    log "Running in the background (pid ${pid}) — stopped automatically when you exit this script."
  else
    err "Port-forward for ${label} failed to start:"
    cat "/tmp/run_project_${key}_pf.log"
    unset "PF_PIDS[$key]"
  fi
}

launch_frontend()     { launch_port_forward frontend     cs2-frontend-service                    8080 80   "Frontend Dashboard"; }
launch_grafana()      { launch_port_forward grafana       prometheus-grafana                      3000 80   "Grafana" "default login: admin / prom-operator unless changed"; }
launch_prometheus()   { launch_port_forward prometheus    prometheus-kube-prometheus-prometheus   9090 9090 "Prometheus"; }
launch_alertmanager() { launch_port_forward alertmanager  prometheus-kube-prometheus-alertmanager 9093 9093 "Alertmanager"; }

cluster_status() {
  echo -e "${BOLD}--- Pods ---${RESET}"
  kubectl get pods -o wide
  echo -e "${BOLD}--- Services ---${RESET}"
  kubectl get svc
  echo -e "${BOLD}--- Secrets (names/types only — values are never shown) ---${RESET}"
  kubectl get secrets
}

# --- Main ---

require_cmd kubectl
require_cmd helm

echo -e "${BOLD}${BLUE}=== CS2 Analytics — Automated Setup & Diagnostics ===${RESET}"
setup_stack

while true; do
  echo ""
  echo -e "${BOLD}CS2 Analytics — Diagnostics Menu${RESET}"
  PS3=$'\n'"Choose an option: "
  options=(
    "View Scraper Logs"
    "Connect to Postgres CLI (latest 10 market_data rows)"
    "Launch Frontend Dashboard"
    "Launch Grafana Dashboard"
    "Launch Prometheus"
    "Launch Alertmanager"
    "Cluster Status Overview"
    "Exit"
  )
  select opt in "${options[@]}"; do
    case "$REPLY" in
      1) view_scraper_logs; break ;;
      2) connect_postgres; break ;;
      3) launch_frontend; break ;;
      4) launch_grafana; break ;;
      5) launch_prometheus; break ;;
      6) launch_alertmanager; break ;;
      7) cluster_status; break ;;
      8) log "Exiting..."; exit 0 ;;
      *) warn "Invalid choice: ${REPLY}"; break ;;
    esac
  done
done
