#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-app/static/icons/connectors}"
mkdir -p "$OUT_DIR"

# Prefer to derive connector ids from the registry.
CONNECTOR_IDS=()
if [ -x ".venv/bin/python" ]; then
  mapfile -t CONNECTOR_IDS < <(.venv/bin/python - <<'PY'
from app.connectors import connector_utils
for cid in sorted(connector_utils.connector_classes.keys()):
    print(cid)
PY
  )
fi

if [ ${#CONNECTOR_IDS[@]} -eq 0 ]; then
  CONNECTOR_IDS=(
    slack teams google_chat discord telegram whatsapp reddit_chat twitter instagram_dm facebook_messenger linkedin pinterest
    webhook jira_service_desk asana trello notion coda calendar outlook_calendar zoom meet
    imap gmail outlook zendesk freshdesk intercom help_scout linear salesforce hubspot pipedrive zoho
    github gitlab bitbucket circleci jenkins pagerduty opsgenie servicenow datadog newrelic splunk
    cloudwatch s3 gdrive dropbox sftp airtable postgres mysql bigquery snowflake kafka rabbitmq
    sample mcp broadcast rest_callback
    mastodon matrix mattermost rocketchat signal wechat viber twitch zulip skype mqtt nats redis_pubsub google_pubsub
  )
fi

# Brand icons via Simple Icons
# https://cdn.simpleicons.org/<slug>
# Associative array: connector id -> simple-icons slug
declare -A SIMPLE_ICON_MAP=(
  [slack]=slack
  [teams]=microsoftteams
  [google_chat]=googlechat
  [discord]=discord
  [telegram]=telegram
  [whatsapp]=whatsapp
  [twitter]=x
  [instagram_dm]=instagram
  [facebook_messenger]=messenger
  [linkedin]=linkedin
  [pinterest]=pinterest
  [reddit_chat]=reddit
  [github]=github
  [gitlab]=gitlab
  [bitbucket]=bitbucket
  [circleci]=circleci
  [jenkins]=jenkins
  [pagerduty]=pagerduty
  [opsgenie]=opsgenie
  [servicenow]=servicenow
  [datadog]=datadog
  [newrelic]=newrelic
  [splunk]=splunk
  [jira_service_desk]=jira
  [asana]=asana
  [trello]=trello
  [notion]=notion
  [coda]=coda
  [linear]=linear
  [hubspot]=hubspot
  [pipedrive]=pipedrive
  [zoho]=zoho
  [salesforce]=salesforce
  [intercom]=intercom
  [zendesk]=zendesk
  [freshdesk]=freshdesk
  [help_scout]=helpscout
  [gmail]=gmail
  [outlook]=microsoftoutlook
  [calendar]=googlecalendar
  [outlook_calendar]=microsoftoutlook
  [meet]=googlemeet
  [zoom]=zoom
  [gdrive]=googledrive
  [dropbox]=dropbox
  [s3]=amazons3
  [cloudwatch]=amazoncloudwatch
  [bigquery]=googlebigquery
  [snowflake]=snowflake
  [airtable]=airtable
  [kafka]=apachekafka
  [rabbitmq]=rabbitmq
  [postgres]=postgresql
  [mysql]=mysql
  [mastodon]=mastodon
  [matrix]=matrix
  [mattermost]=mattermost
  [rocketchat]=rocketchat
  [signal]=signal
  [wechat]=wechat
  [viber]=viber
  [twitch]=twitch
  [zulip]=zulip
  [skype]=skype
  [mqtt]=mqtt
  [nats]=nats
  [redis_pubsub]=redis
  [google_pubsub]=googlecloud
)

# Neutral/system icons via Lucide
# https://unpkg.com/lucide-static@latest/icons/<name>.svg
# Associative array: connector id -> lucide icon name
declare -A LUCIDE_ICON_MAP=(
  [webhook]=link
  [imap]=mail
  [sftp]=server
  [sample]=beaker
  [mcp]=plug
  [broadcast]=megaphone
  [rest_callback]=api
)

fetch_simple() {
  local id="$1" slug="$2"
  local url="https://cdn.simpleicons.org/${slug}"
  local out="${OUT_DIR}/${id}.svg"
  echo "[simple] ${id} -> ${slug}"
  if ! curl -fsSL "$url" -o "$out"; then
    echo "[warn] simple icon not found for ${id} (${slug}), falling back to lucide"
    fetch_lucide "$id" "plug"
  fi
}

fetch_lucide() {
  local id="$1" name="$2"
  local url="https://unpkg.com/lucide-static@latest/icons/${name}.svg"
  local out="${OUT_DIR}/${id}.svg"
  echo "[lucide] ${id} -> ${name}"
  if ! curl -fsSL "$url" -o "$out"; then
    echo "[warn] lucide icon not found for ${id} (${name}), skipping"
    return 0
  fi
}

for id in "${CONNECTOR_IDS[@]}"; do
  if [[ -n "${SIMPLE_ICON_MAP[$id]:-}" ]]; then
    fetch_simple "$id" "${SIMPLE_ICON_MAP[$id]}"
  elif [[ -n "${LUCIDE_ICON_MAP[$id]:-}" ]]; then
    fetch_lucide "$id" "${LUCIDE_ICON_MAP[$id]}"
  else
    fetch_lucide "$id" "plug"
  fi
  sleep 0.05

  # Common aliases for template compatibility
  if [[ "$id" == "twitter" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/x.svg"; fi
  if [[ "$id" == "outlook" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/microsoft_outlook.svg"; fi
  if [[ "$id" == "outlook_calendar" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/calendar_outlook.svg"; fi
  if [[ "$id" == "calendar" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/google_calendar.svg"; fi
  if [[ "$id" == "gdrive" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/google_drive.svg"; fi
  if [[ "$id" == "facebook_messenger" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/facebook.svg"; fi
  if [[ "$id" == "instagram_dm" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/instagram.svg"; fi
  if [[ "$id" == "reddit_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/reddit.svg"; fi
  if [[ "$id" == "jira_service_desk" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/jira.svg"; fi
  if [[ "$id" == "help_scout" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/helpscout.svg"; fi
  if [[ "$id" == "pagerduty" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/page_duty.svg"; fi
  if [[ "$id" == "opsgenie" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/ops_genie.svg"; fi
  if [[ "$id" == "newrelic" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/new_relic.svg"; fi
  if [[ "$id" == "datadog" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/data_dog.svg"; fi
  if [[ "$id" == "splunk" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/splunk_logo.svg"; fi
  if [[ "$id" == "cloudwatch" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/aws_cloudwatch.svg"; fi
  if [[ "$id" == "s3" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/amazon_s3.svg"; fi
  if [[ "$id" == "bigquery" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/google_bigquery.svg"; fi
  if [[ "$id" == "gmail" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/google_gmail.svg"; fi
  if [[ "$id" == "meet" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/google_meet.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat.svg"; fi
  if [[ "$id" == "teams" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/microsoft_teams.svg"; fi
  if [[ "$id" == "slack" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/slack_logo.svg"; fi
  if [[ "$id" == "linkedin" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/linked_in.svg"; fi
  if [[ "$id" == "whatsapp" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/whats_app.svg"; fi
  if [[ "$id" == "snowflake" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/snow_flake.svg"; fi
  if [[ "$id" == "airtable" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/air_table.svg"; fi
  if [[ "$id" == "circleci" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/circle_ci.svg"; fi
  if [[ "$id" == "github" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/git_hub.svg"; fi
  if [[ "$id" == "gitlab" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/git_lab.svg"; fi
  if [[ "$id" == "bitbucket" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/bit_bucket.svg"; fi
  if [[ "$id" == "pipedrive" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/pipe_drive.svg"; fi
  if [[ "$id" == "hubspot" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/hub_spot.svg"; fi
  if [[ "$id" == "freshdesk" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/fresh_desk.svg"; fi
  if [[ "$id" == "instagram_dm" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/ig.svg"; fi
  if [[ "$id" == "facebook_messenger" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/messenger.svg"; fi
  if [[ "$id" == "google_pubsub" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gcp.svg"; fi
  if [[ "$id" == "redis_pubsub" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/redis.svg"; fi
  if [[ "$id" == "matrix" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/matrix_org.svg"; fi
  if [[ "$id" == "wechat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/we_chat.svg"; fi
  if [[ "$id" == "viber" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/vi_ber.svg"; fi
  if [[ "$id" == "twitch" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/twitch_tv.svg"; fi
  if [[ "$id" == "zulip" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/zu_lip.svg"; fi
  if [[ "$id" == "skype" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/sky_pe.svg"; fi
  if [[ "$id" == "mqtt" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/mqtt_icon.svg"; fi
  if [[ "$id" == "nats" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/nats_io.svg"; fi
  if [[ "$id" == "mastodon" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/mastodon_social.svg"; fi
  if [[ "$id" == "mattermost" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/matter_most.svg"; fi
  if [[ "$id" == "rocketchat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/rocket_chat.svg"; fi
  if [[ "$id" == "signal" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/signal_app.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_logo.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/googlechat.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/g_chat.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/g_chat_icon.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_icon.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/g_chat_mark.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchatmark.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/g_chatmark.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_2.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_3.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_4.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_5.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_6.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_7.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_8.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_9.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_10.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_11.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_12.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_13.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_14.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_15.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_16.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_17.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_18.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_19.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_20.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_21.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_22.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_23.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_24.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_25.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_26.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_27.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_28.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_29.svg"; fi
  if [[ "$id" == "google_chat" ]]; then cp -f "${OUT_DIR}/${id}.svg" "${OUT_DIR}/gchat_mark_30.svg"; fi

done
