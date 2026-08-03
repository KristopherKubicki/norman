#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${NORMAN_TAIL_CERT_DOMAIN:-norman.tail94915.ts.net}"
CERT_DIR="${NORMAN_TAIL_CERT_DIR:-/etc/caddy/certs}"
CERT_PATH="${CERT_DIR}/${DOMAIN}.crt"
KEY_PATH="${CERT_DIR}/${DOMAIN}.key"
MIN_VALIDITY="${NORMAN_TAIL_CERT_MIN_VALIDITY:-720h}"
RENEW_WINDOW_SECS="${NORMAN_TAIL_CERT_RENEW_WINDOW_SECS:-2592000}"

exec 9>/run/lock/norman-tail-cert-renew.lock
if ! flock -n 9; then
    echo "another ${DOMAIN} certificate refresh is already running"
    exit 0
fi

certificate_covers_domain() {
    openssl x509 -noout -ext subjectAltName -in "$1" |
        grep -Fq "DNS:${DOMAIN}"
}

verify_served_certificate() {
    local served_cert="${work_dir}/served.crt"
    openssl s_client \
        -connect 127.0.0.1:443 \
        -servername "${DOMAIN}" \
        -showcerts \
        </dev/null \
        2>/dev/null |
        openssl x509 -out "${served_cert}"
    openssl x509 -checkend 0 -noout -in "${served_cert}"
    certificate_covers_domain "${served_cert}"
}

if [[ -f "${CERT_PATH}" && -f "${KEY_PATH}" ]] &&
    openssl x509 -checkend "${RENEW_WINDOW_SECS}" -noout -in "${CERT_PATH}" &&
    certificate_covers_domain "${CERT_PATH}"; then
    echo "${DOMAIN} certificate is still valid beyond the renewal window"
    exit 0
fi

work_dir="$(mktemp -d)"
cleanup() {
    rm -rf "${work_dir}"
}
trap cleanup EXIT

mkdir -p "${CERT_DIR}"
chown root:caddy "${CERT_DIR}"
chmod 750 "${CERT_DIR}"

candidate_cert="${work_dir}/${DOMAIN}.crt"
candidate_key="${work_dir}/${DOMAIN}.key"
previous_cert="${work_dir}/previous.crt"
previous_key="${work_dir}/previous.key"
has_previous_cert=false

if [[ -f "${CERT_PATH}" && -f "${KEY_PATH}" ]]; then
    cp --preserve=mode "${CERT_PATH}" "${previous_cert}"
    cp --preserve=mode "${KEY_PATH}" "${previous_key}"
    has_previous_cert=true
fi

tailscale cert \
    --cert-file "${candidate_cert}" \
    --key-file "${candidate_key}" \
    --min-validity="${MIN_VALIDITY}" \
    "${DOMAIN}"

openssl x509 -checkend 0 -noout -in "${candidate_cert}"
certificate_covers_domain "${candidate_cert}"

if [[ -f "${CERT_PATH}" ]] && cmp -s "${candidate_cert}" "${CERT_PATH}"; then
    echo "${DOMAIN} certificate is already current"
    exit 0
fi

install -m 640 "${candidate_cert}" "${CERT_PATH}"
install -m 640 "${candidate_key}" "${KEY_PATH}"
chown root:caddy "${CERT_PATH}" "${KEY_PATH}"
if ! systemctl reload caddy || ! verify_served_certificate; then
    echo "Caddy did not serve the refreshed ${DOMAIN} certificate" >&2
    if [[ "${has_previous_cert}" == "true" ]]; then
        install -m 640 "${previous_cert}" "${CERT_PATH}"
        install -m 640 "${previous_key}" "${KEY_PATH}"
        chown root:caddy "${CERT_PATH}" "${KEY_PATH}"
        systemctl reload caddy || true
    fi
    exit 1
fi

echo "refreshed ${DOMAIN} certificate and reloaded Caddy"
