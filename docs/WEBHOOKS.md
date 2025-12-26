# STET Alerting Integration Guide

## Table of Contents
- [Overview](#overview)
- [Integration Architecture](#integration-architecture)
- [Slack Integration](#slack-integration)
- [PagerDuty Integration](#pagerduty-integration)
- [Discord Integration](#discord-integration)
- [Microsoft Teams Integration](#microsoft-teams-integration)
- [Email Integration](#email-integration)
- [Custom Webhooks](#custom-webhooks)
- [Security Best Practices](#security-best-practices)
- [Testing & Validation](#testing--validation)
- [Monitoring Webhooks](#monitoring-webhooks)

---

## Overview

STET's alerting system monitors enforcement escalation levels and triggers webhooks when thresholds are exceeded. This guide provides production-ready examples for integrating with popular alerting platforms.

### Alert Trigger Conditions

| Escalation Level | When to Alert | Severity |
|-----------------|---------------|----------|
| NONE | Never | Info |
| WARN | ≥1 system STALE | Warning |
| CRITICAL | ≥1 system MISSING | Critical |

### Alert Frequency

- Check interval: 5 minutes (configurable)
- Deduplication: 15 minutes (prevent alert spam)
- Retry on failure: 3 attempts with exponential backoff

---

## Integration Architecture
```
┌─────────────────────────────────────────────────┐
│ STET Monitoring Script (Cron)                   │
│  - Polls /v1/enforcement/escalation             │
│  - Evaluates escalation level                   │
│  - Triggers webhooks on WARN/CRITICAL           │
└─────────────────────────────────────────────────┘
                    |
        ┌───────────┴───────────┐
        v                       v
┌───────────────┐       ┌───────────────┐
│ Slack         │       │ PagerDuty     │
│ (Team notify) │       │ (On-call)     │
└───────────────┘       └───────────────┘
        v                       v
┌───────────────┐       ┌───────────────┐
│ Email         │       │ Custom System │
│ (Ops team)    │       │ (Your API)    │
└───────────────┘       └───────────────┘
```

---

## Slack Integration

### 1. Create Slack Incoming Webhook

1. Go to https://api.slack.com/apps
2. Create new app → "From scratch"
3. Enable "Incoming Webhooks"
4. Add webhook to workspace
5. Copy webhook URL (e.g., `https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX`)

### 2. STET Slack Alert Script

**/opt/stet/scripts/alert-slack.sh:**
```bash
#!/bin/bash
set -e

API_URL="${STET_API_URL:-https://api.yourdomain.com}"
SLACK_WEBHOOK="${SLACK_WEBHOOK_URL}"
TENANT_ID="${STET_MONITORING_TENANT_ID}"
STATE_FILE="/tmp/stet-alert-state.json"

# Color codes
COLOR_WARN="#f4a261"
COLOR_CRITICAL="#e63946"

# Fetch current escalation
RESPONSE=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $TENANT_ID" || echo '{"escalation":"ERROR"}')

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')
EVALUATED_AT=$(echo "$RESPONSE" | jq -r '.evaluated_at')
SUMMARY=$(echo "$RESPONSE" | jq -c '.summary')
AFFECTED=$(echo "$RESPONSE" | jq -c '.affected_systems')

# Load previous state for deduplication
PREVIOUS_ESCALATION="NONE"
if [ -f "$STATE_FILE" ]; then
    PREVIOUS_ESCALATION=$(jq -r '.last_escalation' "$STATE_FILE")
    LAST_ALERT=$(jq -r '.last_alert_time' "$STATE_FILE")
    
    # Skip if same escalation within 15 minutes
    if [ "$ESCALATION" = "$PREVIOUS_ESCALATION" ]; then
        MINUTES_SINCE=$(( ($(date +%s) - $(date -d "$LAST_ALERT" +%s)) / 60 ))
        if [ "$MINUTES_SINCE" -lt 15 ]; then
            echo "Skipping duplicate alert (last: $MINUTES_SINCE min ago)"
            exit 0
        fi
    fi
fi

# Only alert on WARN or CRITICAL
if [ "$ESCALATION" != "WARN" ] && [ "$ESCALATION" != "CRITICAL" ]; then
    echo "Escalation level OK, no alert needed"
    # Save state
    echo "{\"last_escalation\":\"$ESCALATION\",\"last_alert_time\":\"$(date -Iseconds)\"}" > "$STATE_FILE"
    exit 0
fi

# Determine color and emoji
if [ "$ESCALATION" = "CRITICAL" ]; then
    COLOR="$COLOR_CRITICAL"
    EMOJI=":rotating_light:"
    TITLE="STET Enforcement CRITICAL"
else
    COLOR="$COLOR_WARN"
    EMOJI=":warning:"
    TITLE="STET Enforcement WARNING"
fi

# Build affected systems text
AFFECTED_TEXT=""
AFFECTED_COUNT=$(echo "$AFFECTED" | jq 'length')
if [ "$AFFECTED_COUNT" -gt 0 ]; then
    AFFECTED_TEXT=$(echo "$AFFECTED" | jq -r '.[] | "• *\(.system_id)*: \(.status)"' | head -5)
    if [ "$AFFECTED_COUNT" -gt 5 ]; then
        AFFECTED_TEXT="$AFFECTED_TEXT
...and $((AFFECTED_COUNT - 5)) more systems"
    fi
fi

# Send Slack notification
PAYLOAD=$(cat <<EOF
{
  "username": "STET Monitor",
  "icon_emoji": "$EMOJI",
  "attachments": [
    {
      "color": "$COLOR",
      "title": "$TITLE",
      "text": "Enforcement escalation detected at $EVALUATED_AT",
      "fields": [
        {
          "title": "Escalation Level",
          "value": "$ESCALATION",
          "short": true
        },
        {
          "title": "Total Systems",
          "value": "$(echo "$SUMMARY" | jq -r '.total_systems')",
          "short": true
        },
        {
          "title": "OK",
          "value": "$(echo "$SUMMARY" | jq -r '.ok')",
          "short": true
        },
        {
          "title": "STALE",
          "value": "$(echo "$SUMMARY" | jq -r '.stale')",
          "short": true
        },
        {
          "title": "MISSING",
          "value": "$(echo "$SUMMARY" | jq -r '.missing')",
          "short": true
        },
        {
          "title": "Affected Systems",
          "value": "$AFFECTED_TEXT",
          "short": false
        }
      ],
      "actions": [
        {
          "type": "button",
          "text": "View Dashboard",
          "url": "$API_URL/docs"
        }
      ]
    }
  ]
}
EOF
)

curl -X POST "$SLACK_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"

# Save state
echo "{\"last_escalation\":\"$ESCALATION\",\"last_alert_time\":\"$(date -Iseconds)\"}" > "$STATE_FILE"

echo "Slack alert sent: $ESCALATION"
```

### 3. Configuration
```bash
# /etc/stet/alerting.conf
export STET_API_URL="https://api.yourdomain.com"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
export STET_MONITORING_TENANT_ID="00000000-0000-0000-0000-000000000001"
```

### 4. Cron Schedule
```cron
# /etc/cron.d/stet-slack-alerts
*/5 * * * * root source /etc/stet/alerting.conf && /opt/stet/scripts/alert-slack.sh
```

### Expected Slack Message

**WARN:**
```
⚠️ STET Enforcement WARNING
Enforcement escalation detected at 2025-12-26T15:30:00Z

Escalation Level: WARN          Total Systems: 5
OK: 4                            STALE: 1
MISSING: 0

Affected Systems:
- downstream-2: STALE

[View Dashboard]
```

**CRITICAL:**
```
🚨 STET Enforcement CRITICAL
Enforcement escalation detected at 2025-12-26T15:35:00Z

Escalation Level: CRITICAL       Total Systems: 5
OK: 3                            STALE: 1
MISSING: 1

Affected Systems:
- downstream-2: STALE
- downstream-5: MISSING

[View Dashboard]
```

---

## PagerDuty Integration

### 1. Create PagerDuty Integration

1. Go to PagerDuty → Services → Add Integration
2. Select "Events API v2"
3. Copy integration key (e.g., `R02XXXXXXXXXXXXXXXXXXXXXXXXX`)

### 2. STET PagerDuty Alert Script

**/opt/stet/scripts/alert-pagerduty.sh:**
```bash
#!/bin/bash
set -e

API_URL="${STET_API_URL:-https://api.yourdomain.com}"
PAGERDUTY_KEY="${PAGERDUTY_INTEGRATION_KEY}"
TENANT_ID="${STET_MONITORING_TENANT_ID}"

# Fetch escalation
RESPONSE=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $TENANT_ID")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')
SUMMARY=$(echo "$RESPONSE" | jq -c '.summary')
AFFECTED=$(echo "$RESPONSE" | jq -c '.affected_systems')

# Only trigger PagerDuty on CRITICAL
if [ "$ESCALATION" != "CRITICAL" ]; then
    echo "Not CRITICAL, skipping PagerDuty"
    exit 0
fi

# Build incident details
MISSING_COUNT=$(echo "$SUMMARY" | jq -r '.missing')
STALE_COUNT=$(echo "$SUMMARY" | jq -r '.stale')

AFFECTED_LIST=$(echo "$AFFECTED" | jq -r '.[] | .system_id' | tr '\n' ',' | sed 's/,$//')

PAYLOAD=$(cat <<EOF
{
  "routing_key": "$PAGERDUTY_KEY",
  "event_action": "trigger",
  "dedup_key": "stet-enforcement-critical",
  "payload": {
    "summary": "STET: $MISSING_COUNT system(s) MISSING, $STALE_COUNT STALE",
    "severity": "critical",
    "source": "stet-monitor",
    "component": "enforcement",
    "group": "trust-verification",
    "class": "enforcement_failure",
    "custom_details": {
      "escalation_level": "$ESCALATION",
      "missing_systems": $MISSING_COUNT,
      "stale_systems": $STALE_COUNT,
      "affected_systems": "$AFFECTED_LIST",
      "dashboard_url": "$API_URL/docs"
    }
  }
}
EOF
)

# Send to PagerDuty
curl -X POST https://events.pagerduty.com/v2/enqueue \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"

echo "PagerDuty incident triggered"
```

### 3. Auto-Resolve on Recovery
```bash
#!/bin/bash
# /opt/stet/scripts/pagerduty-resolve.sh

if [ "$ESCALATION" = "NONE" ]; then
    PAYLOAD=$(cat <<EOF
{
  "routing_key": "$PAGERDUTY_KEY",
  "event_action": "resolve",
  "dedup_key": "stet-enforcement-critical"
}
EOF
    )
    
    curl -X POST https://events.pagerduty.com/v2/enqueue \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD"
    
    echo "PagerDuty incident resolved"
fi
```

---

## Discord Integration

### 1. Create Discord Webhook

1. Discord Server → Edit Channel → Integrations → Webhooks
2. Create webhook
3. Copy webhook URL

### 2. STET Discord Alert Script

**/opt/stet/scripts/alert-discord.sh:**
```bash
#!/bin/bash
set -e

DISCORD_WEBHOOK="${DISCORD_WEBHOOK_URL}"
API_URL="${STET_API_URL}"
TENANT_ID="${STET_MONITORING_TENANT_ID}"

RESPONSE=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $TENANT_ID")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')
SUMMARY=$(echo "$RESPONSE" | jq -c '.summary')

if [ "$ESCALATION" != "WARN" ] && [ "$ESCALATION" != "CRITICAL" ]; then
    exit 0
fi

# Determine color (decimal)
if [ "$ESCALATION" = "CRITICAL" ]; then
    COLOR=15158332  # Red
    TITLE="🚨 STET Enforcement CRITICAL"
else
    COLOR=16098851  # Orange
    TITLE="⚠️ STET Enforcement WARNING"
fi

PAYLOAD=$(cat <<EOF
{
  "username": "STET Monitor",
  "embeds": [
    {
      "title": "$TITLE",
      "color": $COLOR,
      "fields": [
        {
          "name": "Escalation",
          "value": "$ESCALATION",
          "inline": true
        },
        {
          "name": "OK",
          "value": "$(echo "$SUMMARY" | jq -r '.ok')",
          "inline": true
        },
        {
          "name": "STALE",
          "value": "$(echo "$SUMMARY" | jq -r '.stale')",
          "inline": true
        },
        {
          "name": "MISSING",
          "value": "$(echo "$SUMMARY" | jq -r '.missing')",
          "inline": true
        }
      ],
      "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    }
  ]
}
EOF
)

curl -X POST "$DISCORD_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"

echo "Discord alert sent"
```

---

## Microsoft Teams Integration

### 1. Create Teams Incoming Webhook

1. Teams channel → Connectors → Incoming Webhook
2. Configure webhook
3. Copy URL

### 2. STET Teams Alert Script

**/opt/stet/scripts/alert-teams.sh:**
```bash
#!/bin/bash
set -e

TEAMS_WEBHOOK="${TEAMS_WEBHOOK_URL}"
API_URL="${STET_API_URL}"
TENANT_ID="${STET_MONITORING_TENANT_ID}"

RESPONSE=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $TENANT_ID")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')
SUMMARY=$(echo "$RESPONSE" | jq -c '.summary')
AFFECTED=$(echo "$RESPONSE" | jq -c '.affected_systems')

if [ "$ESCALATION" != "WARN" ] && [ "$ESCALATION" != "CRITICAL" ]; then
    exit 0
fi

# Color
if [ "$ESCALATION" = "CRITICAL" ]; then
    COLOR="E63946"  # Red
    TITLE="STET Enforcement CRITICAL"
else
    COLOR="F4A261"  # Orange
    TITLE="STET Enforcement WARNING"
fi

# Build facts
FACTS=""
for system in $(echo "$AFFECTED" | jq -c '.[]'); do
    SYSTEM_ID=$(echo "$system" | jq -r '.system_id')
    STATUS=$(echo "$system" | jq -r '.status')
    FACTS="$FACTS{\"name\":\"$SYSTEM_ID\",\"value\":\"$STATUS\"},"
done
FACTS=$(echo "$FACTS" | sed 's/,$//')

PAYLOAD=$(cat <<EOF
{
  "@type": "MessageCard",
  "@context": "https://schema.org/extensions",
  "themeColor": "$COLOR",
  "title": "$TITLE",
  "summary": "Enforcement escalation: $ESCALATION",
  "sections": [
    {
      "activityTitle": "Escalation Summary",
      "facts": [
        {
          "name": "Level",
          "value": "$ESCALATION"
        },
        {
          "name": "Total Systems",
          "value": "$(echo "$SUMMARY" | jq -r '.total_systems')"
        },
        {
          "name": "OK",
          "value": "$(echo "$SUMMARY" | jq -r '.ok')"
        },
        {
          "name": "STALE",
          "value": "$(echo "$SUMMARY" | jq -r '.stale')"
        },
        {
          "name": "MISSING",
          "value": "$(echo "$SUMMARY" | jq -r '.missing')"
        }
      ]
    },
    {
      "activityTitle": "Affected Systems",
      "facts": [$FACTS]
    }
  ],
  "potentialAction": [
    {
      "@type": "OpenUri",
      "name": "View Dashboard",
      "targets": [
        {
          "os": "default",
          "uri": "$API_URL/docs"
        }
      ]
    }
  ]
}
EOF
)

curl -X POST "$TEAMS_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"

echo "Teams alert sent"
```

---

## Email Integration

### STET Email Alert Script

**/opt/stet/scripts/alert-email.sh:**
```bash
#!/bin/bash
set -e

API_URL="${STET_API_URL}"
TENANT_ID="${STET_MONITORING_TENANT_ID}"
ALERT_EMAIL="${STET_ALERT_EMAIL:-ops@yourdomain.com}"

RESPONSE=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $TENANT_ID")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')
EVALUATED_AT=$(echo "$RESPONSE" | jq -r '.evaluated_at')
SUMMARY=$(echo "$RESPONSE" | jq -c '.summary')
AFFECTED=$(echo "$RESPONSE" | jq -c '.affected_systems')

if [ "$ESCALATION" != "WARN" ] && [ "$ESCALATION" != "CRITICAL" ]; then
    exit 0
fi

# Build email body
EMAIL_BODY=$(cat <<EOF
STET Enforcement Alert
======================

Escalation Level: $ESCALATION
Evaluated At: $EVALUATED_AT

Summary:
--------
Total Systems: $(echo "$SUMMARY" | jq -r '.total_systems')
OK: $(echo "$SUMMARY" | jq -r '.ok')
STALE: $(echo "$SUMMARY" | jq -r '.stale')
MISSING: $(echo "$SUMMARY" | jq -r '.missing')

Affected Systems:
-----------------
$(echo "$AFFECTED" | jq -r '.[] | "\(.system_id): \(.status)"')

Dashboard: $API_URL/docs

---
This is an automated alert from STET Monitor
EOF
)

# Send via mailx (or sendmail, postfix, etc.)
echo "$EMAIL_BODY" | mail -s "STET Alert: $ESCALATION" "$ALERT_EMAIL"

echo "Email alert sent to $ALERT_EMAIL"
```

**Install mailutils:**
```bash
sudo apt install mailutils -y
```

---

## Custom Webhooks

### Generic Webhook Sender

**/opt/stet/scripts/alert-webhook.sh:**
```bash
#!/bin/bash
set -e

WEBHOOK_URL="${CUSTOM_WEBHOOK_URL}"
WEBHOOK_SECRET="${CUSTOM_WEBHOOK_SECRET}"
API_URL="${STET_API_URL}"
TENANT_ID="${STET_MONITORING_TENANT_ID}"

RESPONSE=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $TENANT_ID")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')

if [ "$ESCALATION" != "WARN" ] && [ "$ESCALATION" != "CRITICAL" ]; then
    exit 0
fi

# Add timestamp and signature
TIMESTAMP=$(date +%s)
SIGNATURE=$(echo -n "$RESPONSE$TIMESTAMP" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $2}')

# Send to custom webhook
curl -X POST "$WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -H "X-STET-Timestamp: $TIMESTAMP" \
    -H "X-STET-Signature: $SIGNATURE" \
    -d "$RESPONSE"

echo "Custom webhook sent"
```

### Webhook Receiver Example (Python Flask)
```python
from flask import Flask, request, abort
import hmac
import hashlib
import json

app = Flask(__name__)
WEBHOOK_SECRET = "your-secret-key"

@app.route('/stet-webhook', methods=['POST'])
def stet_webhook():
    # Verify signature
    timestamp = request.headers.get('X-STET-Timestamp')
    signature = request.headers.get('X-STET-Signature')
    body = request.get_data()
    
    expected_sig = hmac.new(
        WEBHOOK_SECRET.encode(),
        body + timestamp.encode(),
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_sig):
        abort(401, "Invalid signature")
    
    # Process webhook
    data = request.json
    escalation = data['escalation']
    summary = data['summary']
    
    if escalation == 'CRITICAL':
        # Your critical alert logic
        send_to_ops_team(data)
    elif escalation == 'WARN':
        # Your warning logic
        log_warning(data)
    
    return {'status': 'ok'}, 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

---

## Security Best Practices

### 1. Webhook URL Protection
```bash
# Store webhook URLs as secrets
sudo mkdir -p /etc/stet/secrets/webhooks
echo "https://hooks.slack.com/services/..." | \
    sudo tee /etc/stet/secrets/webhooks/slack
sudo chmod 600 /etc/stet/secrets/webhooks/*

# Load in scripts
SLACK_WEBHOOK_URL=$(cat /etc/stet/secrets/webhooks/slack)
```

### 2. Signature Verification

Always verify webhook signatures for custom integrations:
```bash
# Generate HMAC signature
SIGNATURE=$(echo -n "$PAYLOAD" | \
    openssl dgst -sha256 -hmac "$SECRET" | \
    awk '{print $2}')
```

### 3. Rate Limiting

Prevent webhook abuse:
```bash
# Limit to 1 alert per escalation level per 15 minutes
STATE_FILE="/tmp/stet-alert-${ESCALATION}.lock"
if [ -f "$STATE_FILE" ]; then
    AGE=$(($(date +%s) - $(stat -c %Y "$STATE_FILE")))
    if [ "$AGE" -lt 900 ]; then  # 15 minutes
        echo "Rate limited"
        exit 0
    fi
fi
touch "$STATE_FILE"
```

### 4. Retry Logic with Exponential Backoff
```bash
function send_with_retry() {
    local url=$1
    local payload=$2
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -sf -X POST "$url" -d "$payload"; then
            return 0
        fi
        
        sleep $((2 ** attempt))  # Exponential backoff
        attempt=$((attempt + 1))
    done
    
    echo "Failed after $max_attempts attempts" >&2
    return 1
}
```

---

## Testing & Validation

### 1. Test Alert Manually
```bash
# Simulate CRITICAL escalation
export STET_API_URL="https://api.yourdomain.com"
export STET_MONITORING_TENANT_ID="test-tenant-id"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Run script
/opt/stet/scripts/alert-slack.sh
```

### 2. Validate Webhook Payload
```bash
# Test webhook endpoint
curl -X POST https://your-webhook-receiver.com/test \
    -H "Content-Type: application/json" \
    -d '{
        "escalation": "CRITICAL",
        "summary": {"ok": 0, "stale": 0, "missing": 1},
        "affected_systems": [{"system_id": "test", "status": "MISSING"}]
    }'
```

### 3. End-to-End Test
```bash
#!/bin/bash
# /opt/stet/scripts/test-alerting.sh

echo "Testing STET alerting pipeline..."

# 1. Create test system that will be MISSING
TEST_TENANT="test-alerts-$(date +%s)"
TEST_SYSTEM="test-system-missing"

# 2. Query escalation (should be MISSING)
RESPONSE=$(curl -s "$STET_API_URL/v1/enforcement/escalation?system_id=$TEST_SYSTEM" \
    -H "X-Tenant-Id: $TEST_TENANT")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')

if [ "$ESCALATION" = "CRITICAL" ]; then
    echo "✓ Escalation correctly detected as CRITICAL"
else
    echo "✗ Expected CRITICAL, got $ESCALATION"
    exit 1
fi

# 3. Trigger alert script
export STET_MONITORING_TENANT_ID="$TEST_TENANT"
/opt/stet/scripts/alert-slack.sh

echo "✓ Alert test complete - check Slack/PagerDuty"
```

---

## Monitoring Webhooks

### Webhook Health Check
```bash
#!/bin/bash
# /opt/stet/scripts/check-webhook-health.sh

WEBHOOK_LOG="/var/log/stet/webhooks.log"
ALERT_EMAIL="ops@yourdomain.com"

# Count webhook failures in last hour
FAILURES=$(grep -c "Failed to send webhook" "$WEBHOOK_LOG" | tail -1)

if [ "$FAILURES" -gt 5 ]; then
    echo "WARNING: $FAILURES webhook failures in last hour" | \
        mail -s "STET Webhook Health Alert" "$ALERT_EMAIL"
fi
```

### Webhook Metrics
```bash
# Log all webhook attempts
function log_webhook() {
    local target=$1
    local status=$2
    local response_time=$3
    
    echo "$(date -Iseconds) | $target | $status | ${response_time}ms" >> \
        /var/log/stet/webhook-metrics.log
}

# Example usage
START=$(date +%s%N)
if curl -sf -X POST "$SLACK_WEBHOOK" -d "$PAYLOAD"; then
    END=$(date +%s%N)
    DURATION=$(( (END - START) / 1000000 ))
    log_webhook "slack" "success" "$DURATION"
else
    log_webhook "slack" "failure" "0"
fi
```

---

## Production Checklist

### Pre-Deployment

- [ ] Webhook URLs stored securely (not in git)
- [ ] Test alerts sent successfully
- [ ] Signature verification tested (if applicable)
- [ ] Rate limiting configured
- [ ] Retry logic implemented
- [ ] Deduplication working
- [ ] Logging enabled

### Post-Deployment

- [ ] Verify alerts received within 5 minutes
- [ ] Check webhook metrics for failures
- [ ] Test auto-resolve (if implemented)
- [ ] Document escalation procedures
- [ ] Train on-call team on alerts

---

## Example: Complete Alert Pipeline

**/opt/stet/scripts/alert-all.sh:**
```bash
#!/bin/bash
set -e

# Configuration
source /etc/stet/alerting.conf

# Fetch escalation
RESPONSE=$(curl -sf "$STET_API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: $STET_MONITORING_TENANT_ID")

ESCALATION=$(echo "$RESPONSE" | jq -r '.escalation')

# Route to appropriate channels
case "$ESCALATION" in
    CRITICAL)
        /opt/stet/scripts/alert-pagerduty.sh &  # Page on-call
        /opt/stet/scripts/alert-slack.sh &      # Notify team
        /opt/stet/scripts/alert-email.sh &      # Email ops
        wait
        ;;
    WARN)
        /opt/stet/scripts/alert-slack.sh &      # Notify team only
        wait
        ;;
    NONE)
        # Check if we need to resolve
        /opt/stet/scripts/pagerduty-resolve.sh
        ;;
esac

echo "Alert pipeline complete: $ESCALATION"
```

---

## Additional Resources

- [Slack Incoming Webhooks](https://api.slack.com/messaging/webhooks)
- [PagerDuty Events API](https://developer.pagerduty.com/docs/events-api-v2/overview/)
- [Discord Webhooks Guide](https://discord.com/developers/docs/resources/webhook)
- [Microsoft Teams Connectors](https://docs.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/)

---

**Document Version:** 1.0  
**Last Updated:** December 2025  
**Maintainer:** Keith Rawlings-Brown
