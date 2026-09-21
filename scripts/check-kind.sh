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
CURL_OPTIONS=(--fail --silent --show-error --noproxy '*' --connect-timeout 2 --max-time 10)

cleanup() {
    if [[ -n "${PORT_FORWARD_PID}" ]]; then
        kill "${PORT_FORWARD_PID}" 2>/dev/null || true
        wait "${PORT_FORWARD_PID}" 2>/dev/null || true
    fi
    if [[ -n "${PORT_FORWARD_LOG}" && -f "${PORT_FORWARD_LOG}" ]]; then
        rm -f -- "${PORT_FORWARD_LOG}"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

check_port_forward() {
    if ! kill -0 "${PORT_FORWARD_PID}" 2>/dev/null; then
        echo "Project port-forward stopped or failed to bind 127.0.0.1:${LOCAL_PORT}." >&2
        echo "If the port is occupied, choose another one with BANK_CHURN_PORT." >&2
        cat "${PORT_FORWARD_LOG}" >&2
        exit 1
    fi
}

for tool in docker kind kubectl curl; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "Required tool is not installed: ${tool}" >&2
        exit 1
    fi
done

CLUSTERS="$(kind get clusters)"
if ! grep -qx "${CLUSTER_NAME}" <<<"${CLUSTERS}"; then
    kind create cluster --name "${CLUSTER_NAME}"
fi

docker build -t "${IMAGE_NAME}" .
kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"

kubectl --context "${KUBE_CONTEXT}" --namespace default apply -f k8s/
PREVIOUS_GENERATION="$(
    kubectl --context "${KUBE_CONTEXT}" --namespace default get deployment "${SERVICE_NAME}" \
        -o jsonpath='{.metadata.generation}'
)"
kubectl --context "${KUBE_CONTEXT}" --namespace default rollout restart \
    deployment/${SERVICE_NAME}
RESTART_GENERATION="$(
    kubectl --context "${KUBE_CONTEXT}" --namespace default get deployment "${SERVICE_NAME}" \
        -o jsonpath='{.metadata.generation}'
)"
if [[ "${RESTART_GENERATION}" == "${PREVIOUS_GENERATION}" ]]; then
    echo "Deployment did not change: cannot confirm a new rollout for the loaded image." >&2
    exit 1
fi
kubectl --context "${KUBE_CONTEXT}" --namespace default rollout status \
    deployment/${SERVICE_NAME} --timeout=180s

# rollout status already waits for the new replicas; a label-wide Pod wait can
# accidentally keep waiting for an old Pod that is being terminated.
DEPLOYMENT_STATE="$(
    kubectl --context "${KUBE_CONTEXT}" --namespace default get deployment "${SERVICE_NAME}" \
        -o jsonpath='{.metadata.generation} {.status.observedGeneration} {.spec.replicas} {.status.replicas} {.status.updatedReplicas} {.status.readyReplicas} {.status.availableReplicas}'
)"
if [[ "${DEPLOYMENT_STATE}" != "${RESTART_GENERATION} ${RESTART_GENERATION} 2 2 2 2 2" ]]; then
    echo "Expected the new Deployment generation with exactly 2 updated, ready and available replicas." >&2
    echo "Actual generation/observed/desired/total/updated/ready/available: ${DEPLOYMENT_STATE}" >&2
    exit 1
fi

kubectl --context "${KUBE_CONTEXT}" --namespace default get pods \
    --selector=app=${SERVICE_NAME}

PORT_FORWARD_LOG="$(mktemp "${TMPDIR:-/tmp}/bank-churn-port-forward.XXXXXX")"
kubectl --context "${KUBE_CONTEXT}" --namespace default port-forward \
    --address 127.0.0.1 service/${SERVICE_NAME} "${LOCAL_PORT}:80" >"${PORT_FORWARD_LOG}" 2>&1 &
PORT_FORWARD_PID=$!
PORT_FORWARD_DEADLINE=$((SECONDS + 30))
PORT_FORWARD_READY=false
while (( SECONDS < PORT_FORWARD_DEADLINE )); do
    check_port_forward
    if grep -Fq "Forwarding from 127.0.0.1:${LOCAL_PORT} -> " "${PORT_FORWARD_LOG}"; then
        PORT_FORWARD_READY=true
        break
    fi
    sleep 1
done
if [[ "${PORT_FORWARD_READY}" != true ]]; then
    echo "Timed out after 30s waiting for the project port-forward on 127.0.0.1:${LOCAL_PORT}." >&2
    cat "${PORT_FORWARD_LOG}" >&2
    exit 1
fi

echo "Health response:"
check_port_forward
curl "${CURL_OPTIONS[@]}" "${BASE_URL}/health"
check_port_forward
echo

echo "Prediction response:"
check_port_forward
curl "${CURL_OPTIONS[@]}" \
    -X POST "${BASE_URL}/v1/predict" \
    -H "Content-Type: application/json" \
    -d '{"CreditScore":619,"Geography":"France","Gender":"Female","Age":42,"Tenure":2,"Balance":0.0,"NumOfProducts":1,"HasCrCard":1,"IsActiveMember":1,"EstimatedSalary":101348.88}'
check_port_forward
echo
