#!/usr/bin/env bash
# E2E validation for the cs2-scraper pipeline (env injection, connectivity,
# DB integration, and a live partial-failure smoke test). Mocked retry/429
# tests live separately in scraper/tests/test_market_client.py (pytest) —
# not repeated here against Steam's real servers.
set -uo pipefail

TS=$(date +%s)
DEBUG_POD="cs2-scraper-e2e-debug-${TS}"
E2E_CONFIGMAP="cs2-config-e2e-${TS}"
E2E_JOB="cs2-scraper-e2e-job-${TS}"
TEST_MARKER="__e2e_test_${TS}__"
FAILURES=0

log()  { echo "[test-pipeline] $*"; }
fail() { echo "[test-pipeline] FAIL: $*"; FAILURES=$((FAILURES + 1)); }
pass() { echo "[test-pipeline] PASS: $*"; }

cleanup() {
  log "Cleaning up test resources..."
  kubectl exec "$DEBUG_POD" -- python -c "
from app import db
conn = db.connect_with_retry('cs2-db-service', '5432', 'cs2_stats', '${DB_USER_FOR_CLEANUP:-admin}', __import__('os').environ['DB_PASSWORD'])
conn.autocommit = True
cur = conn.cursor()
cur.execute(\"DELETE FROM market_data WHERE item_name = %s;\", ('${TEST_MARKER}',))
conn.close()
" >/dev/null 2>&1 || true
  kubectl delete pod "$DEBUG_POD" --ignore-not-found=true --wait=false >/dev/null 2>&1
  kubectl delete job "$E2E_JOB" --ignore-not-found=true --wait=false >/dev/null 2>&1
  kubectl delete configmap "$E2E_CONFIGMAP" --ignore-not-found=true >/dev/null 2>&1
  log "Cleanup requested (pod/job deletions are async; check 'kubectl get pods' if you want to confirm)."
}
trap cleanup EXIT

# --- Step 0: ephemeral debug pod, same image + real env wiring, sleeps so we can exec into it ---
log "Creating debug pod ${DEBUG_POD}..."
cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${DEBUG_POD}
  labels:
    app: cs2-scraper-e2e-debug
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
  containers:
    - name: debug
      image: cs2_analytics-scraper:latest
      imagePullPolicy: Never
      command: ["sleep", "300"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: tmp
          mountPath: /tmp
      env:
        - name: PYTHONDONTWRITEBYTECODE
          value: "1"
        - name: DB_HOST
          value: cs2-db-service
        - name: DB_PORT
          value: "5432"
        - name: DB_NAME
          valueFrom:
            configMapKeyRef:
              name: cs2-config
              key: POSTGRES_DB
        - name: DB_USER
          valueFrom:
            configMapKeyRef:
              name: cs2-config
              key: POSTGRES_USER
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: cs2-secret
              key: POSTGRES_PASSWORD
        - name: MARKET_ITEMS
          valueFrom:
            configMapKeyRef:
              name: cs2-config
              key: MARKET_ITEMS
  volumes:
    - name: tmp
      emptyDir: {}
  restartPolicy: Never
EOF

if ! kubectl wait --for=condition=Ready "pod/${DEBUG_POD}" --timeout=60s >/dev/null 2>&1; then
  fail "debug pod never became Ready"
  exit 1
fi
pass "debug pod is Ready"

# --- Step 1: env var injection (presence only — never print DB_PASSWORD's value) ---
log "Step 1: environment variable injection"
kubectl exec "$DEBUG_POD" -- sh -c '
  for var in DB_HOST DB_PORT DB_NAME DB_USER MARKET_ITEMS; do
    val="$(printenv "$var" 2>/dev/null || true)"
    if [ -n "$val" ]; then echo "$var=$val"; else echo "$var=<MISSING>"; fi
  done
  if [ -n "$(printenv DB_PASSWORD 2>/dev/null || true)" ]; then
    echo "DB_PASSWORD=<present, redacted>"
  else
    echo "DB_PASSWORD=<MISSING>"
  fi
' | while IFS= read -r line; do
  case "$line" in
    *"<MISSING>"*) fail "env var: $line" ;;
    *) pass "env var: $line" ;;
  esac
done

# --- Step 2: connectivity ---
log "Step 2: network connectivity"
STEAM_CHECK=$(kubectl exec "$DEBUG_POD" -- python -c "
import requests
r = requests.get('https://steamcommunity.com/market/priceoverview/',
                  params={'appid': 730, 'currency': 1, 'market_hash_name': 'AK-47 | Redline (Field-Tested)'},
                  headers={'User-Agent': 'cs2-scraper/1.0 (e2e-test)'}, timeout=10)
print(r.status_code)
" 2>&1)
if echo "$STEAM_CHECK" | grep -qE '^(200|429)$'; then
  pass "Steam Market API reachable (HTTP ${STEAM_CHECK})"
else
  fail "Steam Market API unreachable: ${STEAM_CHECK}"
fi

DB_CHECK=$(kubectl exec "$DEBUG_POD" -- python -c "
import socket
try:
    socket.create_connection(('cs2-db-service', 5432), timeout=5).close()
    print('OK')
except OSError as exc:
    print(f'FAIL:{exc}')
" 2>&1)
if [ "$DB_CHECK" = "OK" ]; then
  pass "cs2-db-service:5432 reachable"
else
  fail "cs2-db-service unreachable: ${DB_CHECK}"
fi

# --- Step 3: DB integration (schema + tagged insert + type/timestamp check + cleanup) ---
log "Step 3: database integration"
DB_RESULT=$(kubectl exec "$DEBUG_POD" -- python -c "
import os
from app import db
from app.market_transform import build_market_row

conn = db.connect_with_retry(os.environ['DB_HOST'], os.environ['DB_PORT'], os.environ['DB_NAME'], os.environ['DB_USER'], os.environ['DB_PASSWORD'])
conn.autocommit = True
db.ensure_market_schema(conn)

row = build_market_row('${TEST_MARKER}', {'success': True, 'lowest_price': '\$9.99', 'volume': '42'})
db.insert_market_row(conn, row)

cur = conn.cursor()
cur.execute('SELECT item_name, lowest_price, volume, scraped_at, pg_typeof(lowest_price), pg_typeof(volume) FROM market_data WHERE item_name = %s;', ('${TEST_MARKER}',))
result = cur.fetchone()
conn.close()
print(result)
" 2>&1)

if echo "$DB_RESULT" | grep -q "${TEST_MARKER}" && echo "$DB_RESULT" | grep -q "numeric" && echo "$DB_RESULT" | grep -q "integer"; then
  pass "schema OK, tagged row inserted with correct types: ${DB_RESULT}"
else
  fail "DB integration check failed: ${DB_RESULT}"
fi
# (row is removed in the cleanup trap below)

# --- Step 4: partial-failure-continues live smoke test ---
log "Step 4: partial-failure-continues (live one-off Job with one bad item)"
kubectl create configmap "$E2E_CONFIGMAP" \
  --from-literal=MARKET_ITEMS="___this_item_does_not_exist_e2e___,AK-47 | Redline (Field-Tested)" \
  >/dev/null

cat <<EOF | kubectl apply -f - >/dev/null
apiVersion: batch/v1
kind: Job
metadata:
  name: ${E2E_JOB}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 60
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: scraper
          image: cs2_analytics-scraper:latest
          imagePullPolicy: Never
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
          env:
            - name: PYTHONDONTWRITEBYTECODE
              value: "1"
            - name: DB_HOST
              value: cs2-db-service
            - name: DB_PORT
              value: "5432"
            - name: DB_NAME
              valueFrom:
                configMapKeyRef: {name: cs2-config, key: POSTGRES_DB}
            - name: DB_USER
              valueFrom:
                configMapKeyRef: {name: cs2-config, key: POSTGRES_USER}
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef: {name: cs2-secret, key: POSTGRES_PASSWORD}
            - name: MARKET_ITEMS
              valueFrom:
                configMapKeyRef: {name: ${E2E_CONFIGMAP}, key: MARKET_ITEMS}
      volumes:
        - name: tmp
          emptyDir: {}
      restartPolicy: Never
EOF

if kubectl wait --for=condition=Complete "job/${E2E_JOB}" --timeout=60s >/dev/null 2>&1; then
  JOB_LOGS=$(kubectl logs "job/${E2E_JOB}" 2>&1)
  if echo "$JOB_LOGS" | grep -q "Failed to fetch/record price for '___this_item_does_not_exist_e2e___'" \
     && echo "$JOB_LOGS" | grep -q "Recorded price for AK-47"; then
    pass "bad item logged-and-skipped, good item still recorded — loop did not abort"
  else
    fail "expected partial-failure log pattern not found:"$'\n'"${JOB_LOGS}"
  fi
else
  fail "one-off Job did not complete: $(kubectl logs "job/${E2E_JOB}" 2>&1)"
fi
# Clean up the real AK-47 row this smoke test legitimately inserted too.
kubectl exec "$DEBUG_POD" -- python -c "
import os
from app import db
conn = db.connect_with_retry(os.environ['DB_HOST'], os.environ['DB_PORT'], os.environ['DB_NAME'], os.environ['DB_USER'], os.environ['DB_PASSWORD'])
conn.autocommit = True
cur = conn.cursor()
cur.execute(\"DELETE FROM market_data WHERE item_name = 'AK-47 | Redline (Field-Tested)' AND scraped_at > now() - interval '5 minutes';\")
conn.close()
" >/dev/null 2>&1 || true

echo ""
if [ "$FAILURES" -eq 0 ]; then
  log "ALL CHECKS PASSED"
  exit 0
else
  log "${FAILURES} CHECK(S) FAILED"
  exit 1
fi
