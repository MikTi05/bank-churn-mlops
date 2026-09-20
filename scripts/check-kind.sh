#!/usr/bin/env bash

set -euo pipefail

CLUSTER_NAME="bank-churn-mlops"
KUBE_CONTEXT="kind-${CLUSTER_NAME}"
IMAGE_NAME="bank-churn-service:1.0"
SERVICE_NAME="bank-churn-service"
LOCAL_PORT="${BANK_CHURN_PORT:-8080}"
BASE_URL="http://127.0.0.1:${LOCAL_PORT}"
PORT_FORWARD_PID=""
PORT_FORWARD_LOG=""

cleanup() {
    if [[ -n "${PORT_FORWARD_PID}" ]] && kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
        kill "${PORT_FORWARD_PID}" 2>/dev/null || true
        wait "${PORT_FORWARD_PID}" 2>/dev/null || true
    fi
    if [[ -n "${PORT_FORWARD_LOG}" && -f "${PORT_FORWARD_LOG}" ]]; then
        rm -f -- "${PORT_FORWARD_LOG}"
    fi
}
trap cleanup EXIT INT TERM

for tool in docker kind kubectl curl; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "Required tool is not installed: ${tool}" >&2
        exit 1
    fi
done

if ! kind get clusters | grep -qx "${CLUSTER_NAME}"; then
    kind create cluster --name "${CLUSTER_NAME}"
fi

docker build -t "${IMAGE_NAME}" .
kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"

kubectl --context "${KUBE_CONTEXT}" apply -f k8s/
kubectl --context "${KUBE_CONTEXT}" rollout status \
    deployment/${SERVICE_NAME} --timeout=180s
kubectl --context "${KUBE_CONTEXT}" wait \
    --for=condition=Ready pod \
    --selector=app=${SERVICE_NAME} \
    --timeout=180s

READY_REPLICAS="$(
    kubectl --context "${KUBE_CONTEXT}" get deployment "${SERVICE_NAME}" \
        -o jsonpath='{.status.readyReplicas}'
)"
if [[ "${READY_REPLICAS}" != "2" ]]; then
    echo "Expected 2 ready replicas, got ${READY_REPLICAS:-0}" >&2
    exit 1
fi

kubectl --context "${KUBE_CONTEXT}" get pods \
    --selector=app=${SERVICE_NAME}

EXISTING_HEALTH="$(curl --fail --silent "${BASE_URL}/health" 2>/dev/null || true)"
if [[ "${EXISTING_HEALTH}" == *'"status":"ok"'* && "${EXISTING_HEALTH}" == *'"model_version":"1.0.0"'* ]]; then
    echo "Using the existing API port-forward on 127.0.0.1:${LOCAL_PORT}"
else
    PORT_FORWARD_LOG="$(mktemp "${TMPDIR:-/tmp}/bank-churn-port-forward.XXXXXX")"
    kubectl --context "${KUBE_CONTEXT}" port-forward \
        service/${SERVICE_NAME} "${LOCAL_PORT}:80" >"${PORT_FORWARD_LOG}" 2>&1 &
    PORT_FORWARD_PID=$!

    for _ in {1..30}; do
        if curl --fail --silent "${BASE_URL}/health" >/dev/null 2>&1; then
            break
        fi
        if ! kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
            cat "${PORT_FORWARD_LOG}" >&2
            exit 1
        fi
        sleep 1
    done
fi

echo "Health response:"
curl --fail --silent --show-error "${BASE_URL}/health"
echo

echo "Prediction response:"
curl --fail --silent --show-error \
    -X POST "${BASE_URL}/v1/predict" \
    -H "Content-Type: application/json" \
    -d '{"CreditScore":619,"Geography":"France","Gender":"Female","Age":42,"Tenure":2,"Balance":0.0,"NumOfProducts":1,"HasCrCard":1,"IsActiveMember":1,"EstimatedSalary":101348.88}'
echo
