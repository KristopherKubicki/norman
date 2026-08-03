#!/usr/bin/env bash
set -euo pipefail

# Reconcile the existing named Evergreen resources. This deliberately avoids
# SAM/CloudFormation ownership changes and only writes AWS state with --apply.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APPLY=false
AWS_PROFILE_NAME=${AWS_PROFILE:-personal-bedrock}
AWS_REGION_NAME=${AWS_REGION:-us-east-2}
API_ID=${EVERGREEN_SMS_API_ID:-lxrpar50a5}
INBOUND_FUNCTION=${EVERGREEN_SMS_INBOUND_FUNCTION:-evergreen-sms-inbound}
OUTBOUND_FUNCTION=${EVERGREEN_SMS_OUTBOUND_FUNCTION:-evergreen-sms-outbound}
COMPLETION_FUNCTION=${EVERGREEN_SMS_COMPLETION_FUNCTION:-evergreen-sms-completion}
INBOUND_ROLE=${EVERGREEN_SMS_INBOUND_ROLE:-evergreen-sms-inbound-role}
OUTBOUND_ROLE=${EVERGREEN_SMS_OUTBOUND_ROLE:-evergreen-sms-outbound-role}
COMPLETION_ROLE=${EVERGREEN_SMS_COMPLETION_ROLE:-evergreen-sms-completion-role}
TABLE_NAME=${EVERGREEN_SMS_TABLE:-evergreen-sms-conversations}
INBOUND_QUEUE_NAME=${EVERGREEN_SMS_INBOUND_QUEUE:-evergreen-sms-inbound}
OUTBOUND_QUEUE_NAME=${EVERGREEN_SMS_OUTBOUND_QUEUE:-evergreen-sms-outbound}
COMPLETION_QUEUE_NAME=${EVERGREEN_SMS_COMPLETION_QUEUE:-evergreen-sms-completion}
INBOUND_DLQ_NAME=${EVERGREEN_SMS_INBOUND_DLQ:-evergreen-sms-inbound-dlq}
OUTBOUND_DLQ_NAME=${EVERGREEN_SMS_OUTBOUND_DLQ:-evergreen-sms-outbound-dlq}
COMPLETION_DLQ_NAME=${EVERGREEN_SMS_COMPLETION_DLQ:-evergreen-sms-completion-dlq}

usage() {
  cat <<'EOF'
Usage: deploy_existing.sh [--apply] [--profile PROFILE] [--region REGION]

Without --apply, this prints the resources it would reconcile and exits
without making AWS changes. --apply never sends an SMS.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=true
      ;;
    --profile)
      AWS_PROFILE_NAME=${2:?--profile requires a value}
      shift
      ;;
    --region)
      AWS_REGION_NAME=${2:?--region requires a value}
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "${APPLY}" != true ]]; then
  cat <<EOF
Plan only. Re-run with --apply to reconcile:
  profile: ${AWS_PROFILE_NAME}
  region: ${AWS_REGION_NAME}
  DynamoDB table: ${TABLE_NAME}
  queues: ${INBOUND_QUEUE_NAME}, ${COMPLETION_QUEUE_NAME}, ${OUTBOUND_QUEUE_NAME}
  functions: ${INBOUND_FUNCTION}, ${COMPLETION_FUNCTION}, ${OUTBOUND_FUNCTION}
  roles: ${INBOUND_ROLE}, ${COMPLETION_ROLE}, ${OUTBOUND_ROLE}

No AWS resources were changed and no SMS was sent.
EOF
  exit 0
fi

for command in aws jq zip; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "missing required command: ${command}" >&2
    exit 1
  }
done

AWS=(aws --profile "${AWS_PROFILE_NAME}" --region "${AWS_REGION_NAME}")
ACCOUNT_ID=$("${AWS[@]}" sts get-caller-identity --query Account --output text)
LAMBDA_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
WEBHOOK_URL=${TWILIO_WEBHOOK_URL:-"https://${API_ID}.execute-api.${AWS_REGION_NAME}.amazonaws.com/twilio/inbound"}

queue_url() {
  local queue_name=$1
  "${AWS[@]}" sqs get-queue-url \
    --queue-name "${queue_name}" \
    --query QueueUrl \
    --output text 2>/dev/null || \
    "${AWS[@]}" sqs create-queue \
      --queue-name "${queue_name}" \
      --query QueueUrl \
      --output text
}

queue_arn() {
  local queue_url_value=$1
  "${AWS[@]}" sqs get-queue-attributes \
    --queue-url "${queue_url_value}" \
    --attribute-names QueueArn \
    --query 'Attributes.QueueArn' \
    --output text
}

set_queue_delivery_policy() {
  local queue_url_value=$1
  local dlq_arn=$2
  local redrive
  local attributes
  redrive=$(jq -cn --arg arn "${dlq_arn}" \
    '{deadLetterTargetArn:$arn,maxReceiveCount:"5"}')
  attributes=$(jq -cn --arg redrive "${redrive}" \
    '{VisibilityTimeout:"180",RedrivePolicy:$redrive}')
  "${AWS[@]}" sqs set-queue-attributes \
    --queue-url "${queue_url_value}" \
    --attributes "${attributes}"
}

ensure_table() {
  if ! "${AWS[@]}" dynamodb describe-table --table-name "${TABLE_NAME}" \
    >/dev/null 2>&1; then
    "${AWS[@]}" dynamodb create-table \
      --table-name "${TABLE_NAME}" \
      --billing-mode PAY_PER_REQUEST \
      --attribute-definitions \
        AttributeName=pk,AttributeType=S \
        AttributeName=sk,AttributeType=S \
      --key-schema \
        AttributeName=pk,KeyType=HASH \
        AttributeName=sk,KeyType=RANGE >/dev/null
    "${AWS[@]}" dynamodb wait table-exists --table-name "${TABLE_NAME}"
  fi
  local ttl_status
  ttl_status=$("${AWS[@]}" dynamodb describe-time-to-live \
    --table-name "${TABLE_NAME}" \
    --query 'TimeToLiveDescription.TimeToLiveStatus' \
    --output text)
  if [[ "${ttl_status}" != ENABLED && "${ttl_status}" != ENABLING ]]; then
    "${AWS[@]}" dynamodb update-time-to-live \
      --table-name "${TABLE_NAME}" \
      --time-to-live-specification Enabled=true,AttributeName=expires_at >/dev/null
  fi
}

ensure_role() {
  local role_name=$1
  if ! "${AWS[@]}" iam get-role --role-name "${role_name}" >/dev/null 2>&1; then
    "${AWS[@]}" iam create-role \
      --role-name "${role_name}" \
      --assume-role-policy-document "${LAMBDA_TRUST}" >/dev/null
  fi
  "${AWS[@]}" iam get-role \
    --role-name "${role_name}" \
    --query 'Role.Arn' \
    --output text
}

put_role_policy() {
  local role_name=$1
  local policy_name=$2
  local policy_document=$3
  "${AWS[@]}" iam put-role-policy \
    --role-name "${role_name}" \
    --policy-name "${policy_name}" \
    --policy-document "${policy_document}"
}

function_environment() {
  local function_name=$1
  "${AWS[@]}" lambda get-function-configuration \
    --function-name "${function_name}" \
    --query 'Environment.Variables' \
    --output json
}

update_function_environment() {
  local function_name=$1
  local variables=$2
  local environment
  environment=$(jq -cn --argjson values "${variables}" '{Variables:$values}')
  "${AWS[@]}" lambda update-function-configuration \
    --function-name "${function_name}" \
    --environment "${environment}" >/dev/null
  "${AWS[@]}" lambda wait function-updated --function-name "${function_name}"
}

update_function_code() {
  local function_name=$1
  local artifact=$2
  "${AWS[@]}" lambda update-function-code \
    --function-name "${function_name}" \
    --zip-file "fileb://${artifact}" >/dev/null
  "${AWS[@]}" lambda wait function-updated --function-name "${function_name}"
}

ensure_sqs_mapping() {
  local function_name=$1
  local source_arn=$2
  local mapping_id
  mapping_id=$("${AWS[@]}" lambda list-event-source-mappings \
    --function-name "${function_name}" \
    --event-source-arn "${source_arn}" \
    --query 'EventSourceMappings[0].UUID' \
    --output text)
  if [[ "${mapping_id}" == None || -z "${mapping_id}" ]]; then
    "${AWS[@]}" lambda create-event-source-mapping \
      --function-name "${function_name}" \
      --event-source-arn "${source_arn}" \
      --batch-size 10 \
      --function-response-types ReportBatchItemFailures \
      --enabled >/dev/null
  else
    "${AWS[@]}" lambda update-event-source-mapping \
      --uuid "${mapping_id}" \
      --batch-size 10 \
      --function-response-types ReportBatchItemFailures \
      --enabled >/dev/null
  fi
}

INBOUND_QUEUE_URL=$(queue_url "${INBOUND_QUEUE_NAME}")
OUTBOUND_QUEUE_URL=$(queue_url "${OUTBOUND_QUEUE_NAME}")
COMPLETION_QUEUE_URL=$(queue_url "${COMPLETION_QUEUE_NAME}")
INBOUND_DLQ_URL=$(queue_url "${INBOUND_DLQ_NAME}")
OUTBOUND_DLQ_URL=$(queue_url "${OUTBOUND_DLQ_NAME}")
COMPLETION_DLQ_URL=$(queue_url "${COMPLETION_DLQ_NAME}")
set_queue_delivery_policy "${INBOUND_QUEUE_URL}" "$(queue_arn "${INBOUND_DLQ_URL}")"
set_queue_delivery_policy "${OUTBOUND_QUEUE_URL}" "$(queue_arn "${OUTBOUND_DLQ_URL}")"
set_queue_delivery_policy "${COMPLETION_QUEUE_URL}" "$(queue_arn "${COMPLETION_DLQ_URL}")"
ensure_table

SECRET_ARN=$(
  "${AWS[@]}" lambda get-function-configuration \
    --function-name "${INBOUND_FUNCTION}" \
    --query 'Environment.Variables.TWILIO_AUTH_TOKEN_SECRET_ARN' \
    --output text
)
if [[ -z "${SECRET_ARN}" || "${SECRET_ARN}" == None ]]; then
  SECRET_ARN=${TWILIO_AUTH_TOKEN_SECRET_ARN:-}
fi
if [[ -z "${SECRET_ARN}" || "${SECRET_ARN}" == None ]]; then
  echo "TWILIO_AUTH_TOKEN_SECRET_ARN must be set on ${INBOUND_FUNCTION} or in the environment" >&2
  exit 1
fi

TABLE_ARN="arn:aws:dynamodb:${AWS_REGION_NAME}:${ACCOUNT_ID}:table/${TABLE_NAME}"
INBOUND_QUEUE_ARN=$(queue_arn "${INBOUND_QUEUE_URL}")
OUTBOUND_QUEUE_ARN=$(queue_arn "${OUTBOUND_QUEUE_URL}")
COMPLETION_QUEUE_ARN=$(queue_arn "${COMPLETION_QUEUE_URL}")
INBOUND_ROLE_ARN=$(ensure_role "${INBOUND_ROLE}")
OUTBOUND_ROLE_ARN=$(ensure_role "${OUTBOUND_ROLE}")
COMPLETION_ROLE_ARN=$(ensure_role "${COMPLETION_ROLE}")

LOG_POLICY='{"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],"Resource":"*"}'
INBOUND_POLICY=$(jq -cn \
  --arg table "${TABLE_ARN}" \
  --arg queue "${INBOUND_QUEUE_ARN}" \
  --arg secret "${SECRET_ARN}" \
  --argjson logs "${LOG_POLICY}" \
  '{Version:"2012-10-17",Statement:[$logs,{Effect:"Allow",Action:["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:TransactWriteItems"],Resource:$table},{Effect:"Allow",Action:["sqs:SendMessage"],Resource:$queue},{Effect:"Allow",Action:["secretsmanager:GetSecretValue"],Resource:$secret}]}')
OUTBOUND_POLICY=$(jq -cn \
  --arg table "${TABLE_ARN}" \
  --arg queue "${OUTBOUND_QUEUE_ARN}" \
  --arg secret "${SECRET_ARN}" \
  --argjson logs "${LOG_POLICY}" \
  '{Version:"2012-10-17",Statement:[$logs,{Effect:"Allow",Action:["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem"],Resource:$table},{Effect:"Allow",Action:["sqs:ReceiveMessage","sqs:DeleteMessage","sqs:GetQueueAttributes"],Resource:$queue},{Effect:"Allow",Action:["secretsmanager:GetSecretValue"],Resource:$secret}]}')
COMPLETION_POLICY=$(jq -cn \
  --arg table "${TABLE_ARN}" \
  --arg source "${COMPLETION_QUEUE_ARN}" \
  --arg target "${OUTBOUND_QUEUE_ARN}" \
  --argjson logs "${LOG_POLICY}" \
  '{Version:"2012-10-17",Statement:[$logs,{Effect:"Allow",Action:["dynamodb:GetItem","dynamodb:UpdateItem"],Resource:$table},{Effect:"Allow",Action:["sqs:ReceiveMessage","sqs:DeleteMessage","sqs:GetQueueAttributes"],Resource:$source},{Effect:"Allow",Action:["sqs:SendMessage"],Resource:$target}]}')
put_role_policy "${INBOUND_ROLE}" evergreen-sms-inbound-access "${INBOUND_POLICY}"
put_role_policy "${OUTBOUND_ROLE}" evergreen-sms-outbound-access "${OUTBOUND_POLICY}"
put_role_policy "${COMPLETION_ROLE}" evergreen-sms-completion-access "${COMPLETION_POLICY}"

PACKAGE_DIR=$(mktemp -d)
ARTIFACT=$(mktemp --suffix=.zip)
rm -f "${ARTIFACT}"
cleanup() {
  rm -rf "${PACKAGE_DIR}" "${ARTIFACT}"
}
trap cleanup EXIT
find "${SCRIPT_DIR}" -maxdepth 1 -type f -name '*.py' -exec cp {} "${PACKAGE_DIR}" \;
(
  cd "${PACKAGE_DIR}"
  zip -q "${ARTIFACT}" ./*.py
)

INBOUND_ENV=$(function_environment "${INBOUND_FUNCTION}" | jq -c \
  --arg table "${TABLE_NAME}" \
  --arg queue "${INBOUND_QUEUE_URL}" \
  --arg secret "${SECRET_ARN}" \
  --arg webhook "${WEBHOOK_URL}" \
  '(. // {})
   | del(.TWILIO_AUTH_TOKEN)
   | .SMS_CONVERSATIONS_TABLE = $table
   | .INBOUND_QUEUE_URL = $queue
   | .TWILIO_AUTH_TOKEN_SECRET_ARN = $secret
   | .TWILIO_WEBHOOK_URL = $webhook
   | .TWILIO_VALIDATE_SIGNATURE = "1"
   | .SMS_BURST_SECONDS = (.SMS_BURST_SECONDS // "8")
   | .SMS_CONVERSATION_IDLE_SECONDS = (.SMS_CONVERSATION_IDLE_SECONDS // "86400")')
OUTBOUND_ENV=$(function_environment "${OUTBOUND_FUNCTION}" | jq -c \
  --arg table "${TABLE_NAME}" \
  --arg secret "${SECRET_ARN}" \
  '(. // {})
   | del(.TWILIO_AUTH_TOKEN)
   | .SMS_CONVERSATIONS_TABLE = $table
   | .TWILIO_AUTH_TOKEN_SECRET_ARN = $secret')
COMPLETION_ENV=$(jq -cn \
  --arg table "${TABLE_NAME}" \
  --arg queue "${OUTBOUND_QUEUE_URL}" \
  '{SMS_CONVERSATIONS_TABLE:$table,OUTBOUND_QUEUE_URL:$queue}')

"${AWS[@]}" lambda update-function-configuration \
  --function-name "${INBOUND_FUNCTION}" \
  --role "${INBOUND_ROLE_ARN}" \
  --runtime python3.12 \
  --handler inbound_handler.lambda_handler \
  --timeout 30 \
  --memory-size 256 >/dev/null
"${AWS[@]}" lambda wait function-updated --function-name "${INBOUND_FUNCTION}"
"${AWS[@]}" lambda update-function-configuration \
  --function-name "${OUTBOUND_FUNCTION}" \
  --role "${OUTBOUND_ROLE_ARN}" \
  --runtime python3.12 \
  --handler outbound_handler.lambda_handler \
  --timeout 30 \
  --memory-size 256 >/dev/null
"${AWS[@]}" lambda wait function-updated --function-name "${OUTBOUND_FUNCTION}"
if ! "${AWS[@]}" lambda get-function \
  --function-name "${COMPLETION_FUNCTION}" >/dev/null 2>&1; then
  "${AWS[@]}" lambda create-function \
    --function-name "${COMPLETION_FUNCTION}" \
    --runtime python3.12 \
    --role "${COMPLETION_ROLE_ARN}" \
    --handler completion_handler.lambda_handler \
    --timeout 30 \
    --memory-size 256 \
    --zip-file "fileb://${ARTIFACT}" \
    --environment "$(jq -cn --argjson values "${COMPLETION_ENV}" '{Variables:$values}')" \
    --description "Durable Evergreen SMS completion processor" >/dev/null
  "${AWS[@]}" lambda wait function-active --function-name "${COMPLETION_FUNCTION}"
else
  "${AWS[@]}" lambda update-function-configuration \
    --function-name "${COMPLETION_FUNCTION}" \
    --role "${COMPLETION_ROLE_ARN}" \
    --runtime python3.12 \
    --handler completion_handler.lambda_handler \
    --timeout 30 \
    --memory-size 256 >/dev/null
  "${AWS[@]}" lambda wait function-updated --function-name "${COMPLETION_FUNCTION}"
fi

update_function_environment "${INBOUND_FUNCTION}" "${INBOUND_ENV}"
update_function_environment "${OUTBOUND_FUNCTION}" "${OUTBOUND_ENV}"
update_function_environment "${COMPLETION_FUNCTION}" "${COMPLETION_ENV}"
update_function_code "${INBOUND_FUNCTION}" "${ARTIFACT}"
update_function_code "${OUTBOUND_FUNCTION}" "${ARTIFACT}"
update_function_code "${COMPLETION_FUNCTION}" "${ARTIFACT}"
ensure_sqs_mapping "${OUTBOUND_FUNCTION}" "${OUTBOUND_QUEUE_ARN}"
ensure_sqs_mapping "${COMPLETION_FUNCTION}" "${COMPLETION_QUEUE_ARN}"

cat <<EOF
Evergreen SMS cloud resources reconciled:
  inbound queue: ${INBOUND_QUEUE_URL}
  completion queue: ${COMPLETION_QUEUE_URL}
  outbound queue: ${OUTBOUND_QUEUE_URL}
  conversations table: ${TABLE_NAME}
  inbound webhook: ${WEBHOOK_URL}

No SMS was sent by this deployment.
EOF
