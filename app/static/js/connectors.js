// connectors.js - dynamic connector management

function showError(input, message) {
  input.classList.add('is-invalid');
  let feedback = input.parentNode.querySelector('.invalid-feedback');
  if (!feedback) {
    feedback = document.createElement('div');
    feedback.className = 'invalid-feedback';
    input.parentNode.appendChild(feedback);
  }
  feedback.textContent = message;
}

function clearError(input) {
  input.classList.remove('is-invalid');
  const feedback = input.parentNode.querySelector('.invalid-feedback');
  if (feedback) feedback.textContent = '';
}

function debounce(fn, waitMs = 150) {
  let timer = null;
  return (...args) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn(...args), waitMs);
  };
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const CONNECTOR_CAPABILITY_SVGS = {
  inbound: `
    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M10 3v8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M6.5 9.5L10 13l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M4 16h12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>
    </svg>
  `,
  outbound: `
    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M10 17V9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M6.5 10.5L10 7l3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M4 4h12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>
    </svg>
  `,
  webhook: `
    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M7 7h-1a3 3 0 0 0 0 6h1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M13 7h1a3 3 0 0 1 0 6h-1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M8 10h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>
    </svg>
  `,
  sso: `
    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path d="M7.5 9.5a3.5 3.5 0 1 1 6.6 1.7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>
      <path d="M11 11.5l3.5 3.5v2h-2l-1-1h-1l-1-1h-1.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
    </svg>
  `,
};

function renderCapabilityIcon(key, { title, on }) {
  const svg = CONNECTOR_CAPABILITY_SVGS[key];
  if (!svg) return '';
  const safeTitle = escapeHtml(title || key);
  return `<span class="cap-icon cap-icon--${escapeHtml(key)} ${on ? 'is-on' : 'is-off'}" title="${safeTitle}">${svg}</span>`;
}


const CONNECTOR_CONFIG_DEFAULTS = {
  gmail: { host: 'imap.gmail.com', port: 993, use_ssl: true, mailbox: 'INBOX' },
  outlook: { host: 'outlook.office365.com', port: 993, use_ssl: true, mailbox: 'INBOX' },
  imap: { port: 993, use_ssl: true, mailbox: 'INBOX' },
  slack: { channel_id: '#general' },
  discord: { channel_id: 'general' },
  telegram: { chat_id: '@your_channel' },
  webhook: { allowed_ips: '*' },
  kafka: { group_id: 'norman' },
  snmp: { port: 1162, community: 'public' },
  arp: { sample_window_seconds: 10 },
  syslog: { port: 1514, listen: true },
  glimpser: { webhook_url: 'https://glimpser.example/webhooks/norman' },
  hubitat: { webhook_url: 'http://hubitat.local/apps/api/APP_ID/events?access_token=TOKEN' },
  activity_monitor: { webhook_url: 'http://hal.local:8789/api/activity', site: 'knox', zone: 'office', host: 'hal' },
  home_assistant: { webhook_url: 'http://homeassistant.local:8123/api/webhook/norman' },
  unifi: { webhook_url: 'https://unifi.local/proxy/network/integration/v1/webhook/norman' },
  pfsense_opnsense: { webhook_url: 'https://firewall.local/api/norman/events' },
  proxmox: { webhook_url: 'https://proxmox.local/api2/json/cluster/notifications/webhook' },
  docker_events: { webhook_url: 'http://docker-host.local:8080/events/webhook' },
  prometheus_alertmanager: { webhook_url: 'http://alertmanager.local:9093/api/v2/webhook' },
  ntfy: { webhook_url: 'https://ntfy.sh/your-topic', topic: 'your-topic' },
  pushover: { webhook_url: 'https://api.pushover.net/1/messages.json' },
  frigate: { webhook_url: 'http://frigate.local:5000/api/events/webhook' },
  tmux: { session: 'ops', target: 'ops:0.0', send_enter: true }
};


const CONNECTOR_QUICK_PRESETS = {
  slack: [
    {
      label: 'Team Channel',
      description: 'Post to a standard team channel.',
      config: { channel_id: '#general' }
    },
    {
      label: 'Incident Room',
      description: 'Route incident traffic to a dedicated room.',
      config: { channel_id: '#incidents' }
    }
  ],
  teams: [
    {
      label: 'Webhook Mode',
      description: 'Use Teams incoming webhook only.',
      config: { webhook_url: 'https://outlook.office.com/webhook/...' }
    },
    {
      label: 'Bot Mode',
      description: 'Use Azure app credentials and bot endpoint.',
      config: { scope: 'https://graph.microsoft.com/.default' }
    }
  ],
  discord: [
    {
      label: 'Webhook Mode',
      description: 'Post to Discord via webhook URL.',
      config: { webhook_url: 'https://discord.com/api/webhooks/...' }
    },
    {
      label: 'Bot Token Mode',
      description: 'Use bot token and channel id.',
      config: { channel_id: '123456789012345678' }
    }
  ],
  signal: [
    {
      label: 'Signal Service',
      description: 'Route through a Signal bridge endpoint.',
      config: { service_url: 'http://localhost:8080/v2/send', phone_number: '+15555551234' }
    }
  ],
  telegram: [
    {
      label: 'Public Channel',
      description: 'Send updates to a channel handle.',
      config: { chat_id: '@ops_channel' }
    },
    {
      label: 'Private Group',
      description: 'Send updates to a private group/chat id.',
      config: { chat_id: '-1000000000000' }
    }
  ],
  webhook: [
    {
      label: 'Open Ingest',
      description: 'Accept from anywhere while prototyping.',
      config: { allowed_ips: '*' }
    },
    {
      label: 'Locked Ingest',
      description: 'Restrict sources to private network CIDRs.',
      config: { allowed_ips: '10.0.0.0/8,192.168.0.0/16' }
    }
  ],
  imap: [
    {
      label: 'Secure Inbox',
      description: 'Default secure IMAP polling settings.',
      config: { mailbox: 'INBOX', use_ssl: true, port: 993 }
    }
  ],
  gmail: [
    {
      label: 'Gmail Inbox',
      description: 'Gmail IMAP defaults.',
      config: { host: 'imap.gmail.com', mailbox: 'INBOX', use_ssl: true, port: 993 }
    }
  ],
  outlook: [
    {
      label: 'Outlook Inbox',
      description: 'Office 365 IMAP defaults.',
      config: { host: 'outlook.office365.com', mailbox: 'INBOX', use_ssl: true, port: 993 }
    }
  ],
  kafka: [
    {
      label: 'Core Topic',
      description: 'Default stream topic for Norman.',
      config: { brokers: 'localhost:9092', topic: 'norman.events', group_id: 'norman' }
    }
  ],
  tmux: [
    {
      label: 'Ops Session',
      description: 'Route commands into a tmux operator pane.',
      config: { session: 'ops', target: 'ops:0.0', send_enter: true }
    },
    {
      label: 'Worker Pane',
      description: 'Target a specific worker pane in a named session.',
      config: { session: 'workers', target: 'workers:1.0', send_enter: true }
    }
  ],
  glimpser: [
    {
      label: 'Camera Event Webhook',
      description: 'Inbound event endpoint from a Glimpser instance.',
      config: { webhook_url: 'https://glimpser.example/webhooks/norman', site: 'home', camera: 'front_door' }
    },
    {
      label: 'Low-Latency Motion Feed',
      description: 'Routing-friendly motion summaries with confidence notes.',
      config: { camera: 'perimeter', min_confidence: 0.8 }
    }
  ],
  hubitat: [
    {
      label: 'Maker API Events',
      description: 'Use Hubitat Maker API event stream webhook.',
      config: { webhook_url: 'http://hubitat.local/apps/api/APP_ID/events?access_token=TOKEN', hub_id: 'main' }
    },
    {
      label: 'Presence + Motion',
      description: 'Prioritize occupancy and motion notes from home devices.',
      config: { event_filter: 'presence,motion', hub_id: 'home' }
    }
  ],
  activity_monitor: [
    {
      label: 'Desktop Activity Feed',
      description: 'Receive recent active/idle and screen-awake updates from a workstation.',
      config: { site: 'knox', zone: 'office', host: 'hal' }
    },
    {
      label: 'Office Workstation',
      description: 'Treat a desktop as the primary office engagement signal.',
      config: { site: 'knox', zone: 'office', host: 'hal', person: 'operator' }
    }
  ],
  home_assistant: [
    {
      label: 'Automation Webhook',
      description: 'Receive state and automation events from Home Assistant.',
      config: { webhook_url: 'http://homeassistant.local:8123/api/webhook/norman', instance: 'home', event_filter: 'state_changed' }
    }
  ],
  unifi: [
    {
      label: 'Network Alerts',
      description: 'Ingest UniFi Network controller alerts and events.',
      config: { webhook_url: 'https://unifi.local/proxy/network/integration/v1/webhook/norman', controller: 'network', site: 'default' }
    }
  ],
  pfsense_opnsense: [
    {
      label: 'Firewall Events',
      description: 'Receive firewall log summaries and automation notes.',
      config: { webhook_url: 'https://firewall.local/api/norman/events', firewall: 'edge', event_filter: 'block,allow,vpn' }
    }
  ],
  proxmox: [
    {
      label: 'Cluster Events',
      description: 'Track VM and node lifecycle events from Proxmox.',
      config: { webhook_url: 'https://proxmox.local/api2/json/cluster/notifications/webhook', cluster: 'homelab', node: 'pve1' }
    }
  ],
  docker_events: [
    {
      label: 'Container Lifecycle',
      description: 'Receive start/stop/restart events from Docker hosts.',
      config: { webhook_url: 'http://docker-host.local:8080/events/webhook', host: 'docker-ops', event_filter: 'container' }
    }
  ],
  prometheus_alertmanager: [
    {
      label: 'Alertmanager Inbound',
      description: 'Route alert groups from Prometheus Alertmanager.',
      config: { webhook_url: 'http://alertmanager.local:9093/api/v2/webhook', receiver: 'norman', route: 'default' }
    }
  ],
  ntfy: [
    {
      label: 'ntfy Topic Feed',
      description: 'Listen to ntfy topic notifications.',
      config: { webhook_url: 'https://ntfy.sh/your-topic', topic: 'your-topic' }
    }
  ],
  pushover: [
    {
      label: 'Pushover Messages',
      description: 'Normalize incoming Pushover alerts and pushes.',
      config: { webhook_url: 'https://api.pushover.net/1/messages.json', user_key: 'your-user-key' }
    }
  ],
  frigate: [
    {
      label: 'Frigate Detections',
      description: 'Ingest person/vehicle detection events from Frigate.',
      config: { webhook_url: 'http://frigate.local:5000/api/events/webhook', camera: 'front', zone: 'driveway' }
    }
  ]
};

const PASSIVE_SENSOR_PRESETS = {
  snmp: {
    connector_type: 'snmp',
    name: 'SNMP Sensor',
    config: { host: '0.0.0.0', port: 1162, community: 'public', listen: true },
    payload: {
      text: 'trap: link down on edge-switch-2',
      trap_oid: '1.3.6.1.6.3.1.1.5.3',
      severity: 'critical',
      signal_class: 'passive',
      passive_source: 'snmp',
      sensor_type: 'snmp'
    }
  },
  arp: {
    connector_type: 'arp',
    name: 'ARP Sensor',
    config: { listen_interface: 'eth0', sample_window_seconds: 10 },
    payload: {
      src_ip: '10.0.0.2',
      src_mac: 'aa:bb:cc:dd:ee:ff',
      dst_ip: '10.0.0.1',
      op: 'who-has',
      signal_class: 'passive',
      passive_source: 'arp',
      sensor_type: 'arp'
    }
  },
  syslog: {
    connector_type: 'syslog',
    name: 'Syslog Sensor',
    config: { host: '0.0.0.0', port: 1514, listen: true },
    payload: {
      text: '<34>1 switch-2 link flap',
      severity: 'warning',
      signal_class: 'passive',
      passive_source: 'syslog',
      sensor_type: 'syslog'
    }
  },
  glimpser: {
    connector_type: 'glimpser',
    name: 'Glimpser Feed',
    config: { camera: 'front_door', site: 'home' },
    payload: {
      event: 'motion.detected',
      camera: 'front_door',
      summary: 'person detected near front path',
      confidence: 93,
      image_url: 'https://glimpser.example/snapshots/front-door/latest.jpg',
      signal_class: 'passive',
      passive_source: 'glimpser',
      sensor_type: 'vision'
    }
  },
  hubitat: {
    connector_type: 'hubitat',
    name: 'Hubitat Feed',
    config: { hub_id: 'home' },
    payload: {
      displayName: 'Kitchen Motion',
      name: 'motion',
      value: 'active',
      deviceId: '42',
      source: 'DEVICE',
      locationId: 'home',
      signal_class: 'passive',
      passive_source: 'hubitat',
      sensor_type: 'home_automation'
    }
  },
  activity_monitor: {
    connector_type: 'activity_monitor',
    name: 'HAL Activity Feed',
    config: { site: 'knox', zone: 'office', host: 'hal' },
    payload: {
      host: 'hal',
      zone: 'office',
      site: 'knox',
      userActive: true,
      screenAwake: true,
      displayIdleSeconds: 14,
      sessionLocked: false,
      signal_class: 'passive',
      passive_source: 'activity_monitor',
      sensor_type: 'activity'
    }
  }
};

const STARTER_PACK_PRESETS = {
  slack: {
    connector_type: 'slack',
    name: 'Slack (Ops)',
    config: { channel_id: '#ops' },
  },
  discord: {
    connector_type: 'discord',
    name: 'Discord (Ops)',
    config: { channel_id: 'general' },
  },
  telegram: {
    connector_type: 'telegram',
    name: 'Telegram (Ops)',
    config: { chat_id: '@ops_channel' },
  },
  webhook: {
    connector_type: 'webhook',
    name: 'Webhook Ingest',
    config: { allowed_ips: '*' },
  },
  snmp: {
    connector_type: 'snmp',
    name: 'SNMP Sensor',
    config: { host: '0.0.0.0', port: 1162, community: 'public', listen: true },
  },
  arp: {
    connector_type: 'arp',
    name: 'ARP Sensor',
    config: { listen_interface: 'eth0', sample_window_seconds: 10 },
  },
  syslog: {
    connector_type: 'syslog',
    name: 'Syslog Sensor',
    config: { host: '0.0.0.0', port: 1514, listen: true },
  },
  glimpser: {
    connector_type: 'glimpser',
    name: 'Glimpser Feed',
    config: { camera: 'front_door', site: 'home' },
  },
  hubitat: {
    connector_type: 'hubitat',
    name: 'Hubitat Feed',
    config: { hub_id: 'home' },
  },
  activity_monitor: {
    connector_type: 'activity_monitor',
    name: 'HAL Activity Feed',
    config: { site: 'knox', zone: 'office', host: 'hal' },
  },
};

const MODAL_WEBHOOK_HELPERS = {
  glimpser: {
    title: 'Glimpser webhook target',
    hint: 'Paste this inbound URL into your Glimpser webhook destination.',
  },
  hubitat: {
    title: 'Hubitat event endpoint',
    hint: 'Use this URL in Hubitat Maker API or Rule Machine webhook actions.',
  },
  activity_monitor: {
    title: 'Activity monitor endpoint',
    hint: 'POST workstation active/idle updates from hal or another desktop here.',
  },
  home_assistant: {
    title: 'Home Assistant webhook target',
    hint: 'Use this URL in Home Assistant webhook automation triggers.',
  },
  unifi: {
    title: 'UniFi webhook target',
    hint: 'Use this URL in UniFi webhook integrations for site events.',
  },
  pfsense_opnsense: {
    title: 'Firewall webhook target',
    hint: 'Use this URL from pfSense/OPNsense automation hooks.',
  },
  proxmox: {
    title: 'Proxmox webhook target',
    hint: 'Route Proxmox notification webhook traffic here.',
  },
  docker_events: {
    title: 'Docker event webhook target',
    hint: 'Use this URL in your Docker event forwarder.',
  },
  prometheus_alertmanager: {
    title: 'Alertmanager webhook target',
    hint: 'Set this URL as a receiver webhook in Alertmanager.',
  },
  ntfy: {
    title: 'ntfy webhook target',
    hint: 'Forward ntfy topic messages to this endpoint.',
  },
  pushover: {
    title: 'Pushover webhook target',
    hint: 'Forward Pushover payloads to this endpoint.',
  },
  frigate: {
    title: 'Frigate webhook target',
    hint: 'Set this URL as the Frigate webhook destination.',
  },
};

function buildConnectorWebhookUrl(connectorType, connectorId = '{connector_id}') {
  return `${window.location.origin}/api/v1/connectors/webhooks/${connectorType}/${connectorId}`;
}

async function copyTextToClipboard(text) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    return false;
  }
}

function buildConnectorConfigTemplate(connectorType, fields) {
  const base = (fields || []).reduce((acc, field) => {
    acc[field] = '';
    return acc;
  }, {});
  return {
    ...base,
    ...(connectorDefaultsMap[connectorType] || {}),
    ...(CONNECTOR_CONFIG_DEFAULTS[connectorType] || {}),
  };
}


function isHttpUrl(value) {
  if (typeof value !== 'string') return false;
  return /^https?:\/\//i.test(value.trim());
}

function isPresentValue(value) {
  return !(value === null || value === undefined || value === '');
}

function getMissingRequiredFields(connectorType, config = {}, requiredFields = [], modeOverride = null) {
  const has = (key) => isPresentValue(config?.[key]);
  const effectiveRequired = getRequiredFieldsForMode(connectorType, config, requiredFields, modeOverride);
  return (effectiveRequired || []).filter((field) => !has(field));
}

function getConnectorModeOptions(connectorType) {
  if (connectorType === 'discord') {
    return [
      { id: 'bot', label: 'Bot Token' },
      { id: 'webhook', label: 'Webhook' },
    ];
  }
  if (connectorType === 'teams') {
    return [
      { id: 'bot', label: 'Bot Credentials' },
      { id: 'webhook', label: 'Webhook' },
    ];
  }
  return [];
}

function getPreferredConnectorMode(connectorType) {
  if (connectorType === 'discord' || connectorType === 'teams') {
    return 'webhook';
  }
  return null;
}

function detectConnectorMode(connectorType, config = {}) {
  const has = (key) => isPresentValue(config?.[key]);
  if (connectorType === 'discord') {
    if (has('webhook_url')) return 'webhook';
    if (has('token') || has('channel_id')) return 'bot';
    return getPreferredConnectorMode(connectorType) || 'bot';
  }
  if (connectorType === 'teams') {
    if (has('webhook_url')) return 'webhook';
    if (has('app_id') || has('app_password') || has('tenant_id') || has('bot_endpoint')) return 'bot';
    return getPreferredConnectorMode(connectorType) || 'bot';
  }
  return null;
}

function getRequiredFieldsForMode(connectorType, config = {}, requiredFields = [], modeOverride = null) {
  const mode = modeOverride || detectConnectorMode(connectorType, config);
  if (connectorType === 'discord') {
    return mode === 'webhook' ? ['webhook_url'] : ['token', 'channel_id'];
  }
  if (connectorType === 'teams') {
    return mode === 'webhook'
      ? ['webhook_url']
      : ['app_id', 'app_password', 'tenant_id', 'bot_endpoint'];
  }
  if (connectorType === 'signal') {
    return requiredFields.length ? requiredFields : ['service_url', 'phone_number'];
  }
  return requiredFields || [];
}

function clearRequiredFieldErrors() {
  document.querySelectorAll('[data-required-field].is-invalid').forEach((input) => {
    input.classList.remove('is-invalid');
  });
}

function markRequiredFieldErrors(missingFields = []) {
  clearRequiredFieldErrors();
  missingFields.forEach((field) => {
    const input = document.querySelector(`[data-required-field="${field}"]`);
    if (input) {
      input.classList.add('is-invalid');
    }
  });
}

function validateConnectorConfigByType(connectorType, config, requiredFields = [], item = null) {
  const errors = [];
  const warnings = [];
  const value = (key) => config?.[key];
  const has = (key) => isPresentValue(value(key));

  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    return {
      ok: false,
      errors: ['Config must be a JSON object.'],
      warnings,
    };
  }

  if (Array.isArray(requiredFields) && requiredFields.length) {
    const missing = getMissingRequiredFields(connectorType, config, requiredFields);
    missing.forEach((field) => {
      errors.push(`Missing required field: ${field}.`);
    });
  }

  if (connectorType === 'slack') {
    if (has('token') && typeof value('token') === 'string' && !/^xox[bap]-/i.test(value('token'))) {
      warnings.push('Slack token does not look like a standard xox token.');
    }
    if (has('channel_id') && typeof value('channel_id') === 'string') {
      const channel = value('channel_id');
      const valid = channel.startsWith('#') || /^[CGD][A-Z0-9]+$/i.test(channel);
      if (!valid) {
        warnings.push('Slack channel_id usually starts with # or looks like C/G/D + ID.');
      }
    }
  }

  if (connectorType === 'discord') {
    if (!has('webhook_url') && (!has('token') || !has('channel_id'))) {
      errors.push('Discord requires webhook_url, or token + channel_id.');
    }
    if (has('webhook_url') && !isHttpUrl(String(value('webhook_url')))) {
      errors.push('webhook_url must start with http:// or https://.');
    }
  }

  if (connectorType === 'teams') {
    const hasWebhook = has('webhook_url');
    const hasBotCreds = has('app_id') && has('app_password') && has('tenant_id') && has('bot_endpoint');
    if (!hasWebhook && !hasBotCreds) {
      errors.push('Teams requires webhook_url, or app_id + app_password + tenant_id + bot_endpoint.');
    }
    if (has('webhook_url') && !isHttpUrl(String(value('webhook_url')))) {
      errors.push('webhook_url must start with http:// or https://.');
    }
    if (has('bot_endpoint') && !isHttpUrl(String(value('bot_endpoint')))) {
      errors.push('bot_endpoint must start with http:// or https://.');
    }
  }

  if (connectorType === 'signal') {
    if (has('service_url') && !isHttpUrl(String(value('service_url')))) {
      errors.push('service_url must start with http:// or https://.');
    }
    if (has('phone_number')) {
      const phone = String(value('phone_number'));
      if (!/^\+?[1-9][0-9]{6,15}$/.test(phone)) {
        warnings.push('Signal phone_number should be an E.164-like number (e.g. +15551234567).');
      }
    }
  }

  if (connectorType === 'telegram') {
    if (has('token') && typeof value('token') === 'string' && !value('token').includes(':')) {
      warnings.push('Telegram token usually contains a colon.');
    }
  }

  if (['imap', 'gmail', 'outlook'].includes(connectorType)) {
    if (has('port')) {
      const port = Number.parseInt(value('port'), 10);
      if (!Number.isFinite(port) || port < 1 || port > 65535) {
        errors.push('IMAP port must be a number between 1 and 65535.');
      }
    }
    if (has('host') && typeof value('host') === 'string' && value('host').includes(' ')) {
      errors.push('IMAP host cannot contain spaces.');
    }
  }

  if (['discord', 'teams', 'jira_service_desk', 'github', 'gitlab', 'webhook'].includes(connectorType)) {
    ['webhook_url', 'url', 'base_url'].forEach((key) => {
      if (has(key) && !isHttpUrl(String(value(key)))) {
        errors.push(`${key} must start with http:// or https://.`);
      }
    });
  }

  if (connectorType === 'kafka') {
    if (has('brokers') && typeof value('brokers') === 'string' && !value('brokers').includes(':')) {
      warnings.push('Kafka brokers should include host:port.');
    }
  }

  if (item?.oauth && has('oauth_provider') && !has('oauth_access_token')) {
    warnings.push('oauth_provider is set but no oauth_access_token is present yet.');
  }

  return {
    ok: errors.length === 0,
    errors,
    warnings,
  };
}

function resolveConnectorPresets(connectorType, item = null) {
  const presets = [...(CONNECTOR_QUICK_PRESETS[connectorType] || [])];
  if (item?.oauth?.default_provider) {
    presets.unshift({
      label: 'Use SSO',
      description: 'Set provider and continue through OAuth flow.',
      config: { oauth_provider: item.oauth.default_provider }
    });
  }
  return presets;
}

function renderConnectorModalPresets(configInput, item, requiredFields = [], validationEl = null) {
  const host = document.getElementById('connector-modal-presets');
  if (!host) return;
  const presets = resolveConnectorPresets(item?.id || '', item);
  if (!presets.length) {
    host.classList.add('d-none');
    host.innerHTML = '';
    return;
  }

  host.classList.remove('d-none');
  host.innerHTML = `
    <div class="small text-muted">Quick presets</div>
    <div class="connector-modal__preset-grid">
      ${presets.map((preset, index) => `
        <button type="button" class="btn btn-outline-secondary btn-sm connector-modal__preset" data-preset-index="${index}" title="${preset.description || ''}">
          ${preset.label}
        </button>
      `).join('')}
    </div>
  `;

  host.querySelectorAll('[data-preset-index]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const index = Number.parseInt(btn.getAttribute('data-preset-index') || '-1', 10);
      const preset = presets[index];
      if (!preset) return;
      let config = {};
      try {
        config = parseModalConfigInput(configInput);
      } catch (err) {
        showError(configInput, 'Config must be valid JSON before applying a preset.');
        setModalValidation('Fix config JSON before applying presets.', 'danger', validationEl);
        return;
      }
      config = {
        ...config,
        ...(preset.config || {})
      };
      configInput.value = JSON.stringify(config, null, 2);
      clearError(configInput);
      syncRequiredEditorFromConfig(configInput, requiredFields);
      setModalValidation(`Applied preset: ${preset.label}.`, 'ok', validationEl);
    });
  });
}

let cachedConnectors = [];
let cachedBots = [];
let availableConnectorTypes = [];
let connectorFieldMap = {}
let connectorDefaultsMap = {};
let backendAvailableIds = new Set();
let statusPollTimer = null;
let connectorHealthById = new Map();
let statusPollInFlight = false;
let routingPollTimer = null;
let routingJobsInFlight = false;
let routingLoaded = false;
let routingRulesConnectorFilterId = null;
let approvalsPollTimer = null;
let approvalsInFlight = false;
let approvalsLastFetchAt = 0;
const APPROVALS_POLL_INTERVAL_MS = 15000;
const APPROVALS_MIN_FETCH_INTERVAL_MS = 2500;

let iconObserver = null;
const iconQueue = [];
let iconInFlight = 0;
const ICON_MAX_INFLIGHT = 6;

// In-memory icon fetch cache. This prevents the connectors catalog from
// hammering the server with repeated SVG requests when we rerender tiles.
const iconObjectUrlCache = new Map(); // src -> objectURL
const iconObjectUrlPending = new Map(); // src -> Promise<objectURL|null>

function getIconObjectUrl(src) {
  if (!src) return Promise.resolve(null);
  if (iconObjectUrlCache.has(src)) return Promise.resolve(iconObjectUrlCache.get(src));
  if (iconObjectUrlPending.has(src)) return iconObjectUrlPending.get(src);

  const promise = (async () => {
    try {
      const resp = await fetch(src, { cache: 'force-cache' });
      if (!resp.ok) return null;
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      iconObjectUrlCache.set(src, url);
      return url;
    } catch (err) {
      return null;
    } finally {
      iconObjectUrlPending.delete(src);
    }
  })();

  iconObjectUrlPending.set(src, promise);
  return promise;
}

window.addEventListener('beforeunload', () => {
  for (const url of iconObjectUrlCache.values()) {
    try { URL.revokeObjectURL(url); } catch (e) {}
  }
  iconObjectUrlCache.clear();
  iconObjectUrlPending.clear();
});

let catalogView = 'tiles';
let catalogGroup = 'none';
let catalogFilter = 'all';
let catalogRenderLimit = 72;
const CATALOG_RENDER_STEP = 72;
const MOBILE_CATALOG_RENDER_STEP = 36;
const CATALOG_VIEW_PREF_KEY = 'norman.connectors.catalog.view.v1';
function isNarrowViewport() {
  return (window.innerWidth || 0) > 0 && (window.innerWidth || 0) <= 720;
}
let catalogViewAuto = true;

function readCatalogViewPreference() {
  try {
    const raw = (localStorage.getItem(CATALOG_VIEW_PREF_KEY) || '').trim();
    return raw === 'tiles' || raw === 'list' ? raw : null;
  } catch (err) {
    return null;
  }
}

function writeCatalogViewPreference(view) {
  try {
    localStorage.setItem(CATALOG_VIEW_PREF_KEY, view);
  } catch (err) {
    // ignore storage errors
  }
}

function syncCatalogViewButtons() {
  document.querySelectorAll('[data-view]').forEach((btn) => {
    btn.classList.toggle('is-active', (btn.dataset.view || 'tiles') === catalogView);
  });
}
let installedConnectorTypes = new Set();
let connectorStatusByType = new Map();
let connectorBrokenTypes = new Set();
let catalogTooltips = [];
let connectorModal = null;
let activeModalConnector = null;
let activeModalMode = 'add';
let activeModalItem = null;
let activeModalRequiredFields = [];
let activeCatalogItemId = null;
let activeModalConnectionMode = null;
let lastModalDismissAt = 0;
const connectorRuleCountCache = new Map();
let connectorsFetchInFlight = null;
let connectorTypesFetchInFlight = null;
let connectorCacheTimer = null;
const ICON_PLACEHOLDER_SRC = 'data:image/gif;base64,R0lGODlhAQABAAAAACw=';
const CONNECTOR_TYPES_CACHE_KEY = 'norman.connectors.available.v1';
const CONNECTORS_CACHE_KEY = 'norman.connectors.list.v1';
const CONNECTOR_TYPES_CACHE_TTL_MS = 10 * 60 * 1000;
const CONNECTORS_CACHE_TTL_MS = 30 * 1000;
const CONNECTOR_RULE_COUNT_TTL_MS = 30 * 1000;
const ROUTING_RULE_FILTER_KEY = "norman.routing.rules.filter.connector_id";
const CONNECTORS_BACKOFF_MS = 15 * 1000;
const CONNECTORS_MIN_FETCH_INTERVAL_MS = 2500;
const CONNECTOR_TYPES_MIN_FETCH_INTERVAL_MS = 5000;
let connectorTypesBackoffUntil = 0;
let connectorsBackoffUntil = 0;
let connectorsLastFetchAt = 0;
let connectorTypesLastFetchAt = 0;
const webhookOnlyIds = new Set([
  'asana',
  'trello',
  'notion',
  'coda',
  'calendar',
  'outlook_calendar',
  'meet',
  'zendesk',
  'freshdesk',
  'help_scout',
  'linear',
  'hubspot',
  'pipedrive',
  'zoho',
  'bitbucket',
  'circleci',
  'jenkins',
  'opsgenie',
  'servicenow',
  'datadog',
  'newrelic',
  'splunk',
  'cloudwatch',
  's3',
  'gdrive',
  'dropbox',
  'sftp',
  'airtable',
  'postgres',
  'mysql',
  'bigquery',
  'snowflake',
  'rabbitmq',
  'glimpser',
  'hubitat',
  'activity_monitor',
  'home_assistant',
  'unifi',
  'pfsense_opnsense',
  'proxmox',
  'docker_events',
  'prometheus_alertmanager',
  'ntfy',
  'pushover',
  'frigate',
]);
const popularityOrder = [
  'slack',
  'teams',
  'google_chat',
  'discord',
  'telegram',
  'whatsapp',
  'gmail',
  'outlook',
  'imap',
  'zendesk',
  'freshdesk',
  'help_scout',
  'hubspot',
  'linear',
  'github',
  'gitlab',
  'jira_service_desk',
  'pagerduty',
  'datadog',
  'splunk',
  'cloudwatch',
  'prometheus_alertmanager',
  'home_assistant',
  'unifi',
  'pfsense_opnsense',
  'proxmox',
  'docker_events',
  'frigate',
  'ntfy',
  'pushover',
  's3',
  'gdrive',
  'dropbox',
];

const connectorCatalog = [
  { id: 'slack', name: 'Slack', category: 'Chat', desc: 'Slack events and outgoing responses.', fields: ['token', 'channel_id', 'signing_secret'] },
  { id: 'google_chat', name: 'Google Chat', category: 'Chat', desc: 'Google Chat rooms and spaces.', fields: ['service_account_key_path', 'space'] },
  { id: 'teams', name: 'Microsoft Teams', category: 'Chat', desc: 'Teams channels and bot posts.', fields: ['app_id', 'app_password', 'tenant_id', 'bot_endpoint', 'webhook_url', 'scope'] },
  { id: 'discord', name: 'Discord', category: 'Chat', desc: 'Discord channels and webhook events.', fields: ['token', 'channel_id', 'webhook_url'] },
  { id: 'telegram', name: 'Telegram', category: 'Chat', desc: 'Telegram bot updates.', fields: ['token', 'chat_id', 'webhook_secret'] },
  { id: 'whatsapp', name: 'WhatsApp', category: 'Chat', desc: 'WhatsApp messages via Twilio.', fields: ['account_sid', 'auth_token', 'from_number', 'to_number', 'status_callback_url'] },
  { id: 'reddit_chat', name: 'Reddit Chat', category: 'Community', desc: 'Reddit inbox and chat.', fields: ['client_id', 'client_secret', 'username', 'password', 'user_agent'] },
  { id: 'twitter', name: 'X / Twitter', category: 'Social', desc: 'Mentions, DMs, and replies.', fields: ['api_key', 'api_secret', 'access_token', 'access_token_secret', 'recipient_id'] },
  { id: 'instagram_dm', name: 'Instagram DM', category: 'Social', desc: 'Instagram comments & DMs.', fields: ['access_token', 'user_id'] },
  { id: 'facebook_messenger', name: 'Facebook Messenger', category: 'Social', desc: 'Page messages and comments.', fields: ['page_token', 'verify_token'] },
  { id: 'linkedin', name: 'LinkedIn', category: 'Social', desc: 'LinkedIn posts and inbox.', fields: ['access_token'] },
  { id: 'pinterest', name: 'Pinterest', category: 'Social', desc: 'Pinterest comments and pins.', fields: ['access_token', 'board_id'] },
  { id: 'webhook', name: 'Webhook', category: 'Inbound', desc: 'Generic HTTP webhook endpoint.', fields: ['secret', 'allowed_ips'] },
  { id: 'jira_service_desk', name: 'Jira Service Desk', category: 'Work', desc: 'Issue events and updates.', fields: ['url', 'email', 'api_token', 'project_key', 'webhook_secret'] },
  { id: 'asana', name: 'Asana', category: 'Work', desc: 'Project tasks and updates.', fields: ['webhook_url', 'verify_token'] },
  { id: 'trello', name: 'Trello', category: 'Work', desc: 'Board cards and activity.', fields: ['webhook_url', 'verify_token'] },
  { id: 'notion', name: 'Notion', category: 'Work', desc: 'Database updates and comments.', fields: ['webhook_url', 'verify_token'] },
  { id: 'coda', name: 'Coda', category: 'Work', desc: 'Docs and tables updates.', fields: ['webhook_url', 'verify_token'] },
  { id: 'calendar', name: 'Google Calendar', category: 'Calendar', desc: 'Event changes and reminders.', fields: ['webhook_url', 'verify_token'] },
  { id: 'outlook_calendar', name: 'Outlook Calendar', category: 'Calendar', desc: 'Calendar events and meetings.', fields: ['webhook_url', 'verify_token'] },
  { id: 'zoom', name: 'Zoom', category: 'Meetings', desc: 'Meetings, recordings, and chat.', fields: ['account_id', 'client_id', 'client_secret', 'webhook_secret'] },
  { id: 'meet', name: 'Google Meet', category: 'Meetings', desc: 'Meeting events and transcripts.', fields: ['webhook_url', 'verify_token'] },
  { id: 'imap', name: 'IMAP Email', category: 'Email', desc: 'Inbound email via IMAP.', fields: ['host', 'username', 'password', 'mailbox', 'use_ssl'] },
  { id: 'gmail', name: 'Gmail', category: 'Email', desc: 'Gmail inbox via IMAP (basic auth).', fields: ['username', 'password', 'mailbox', 'host', 'port', 'use_ssl'] },
  { id: 'outlook', name: 'Outlook Mail', category: 'Email', desc: 'Outlook inbox via IMAP (basic auth).', fields: ['username', 'password', 'mailbox', 'host', 'port', 'use_ssl'] },
  { id: 'zendesk', name: 'Zendesk', category: 'Support', desc: 'Tickets and comments.', fields: ['webhook_url', 'verify_token'] },
  { id: 'freshdesk', name: 'Freshdesk', category: 'Support', desc: 'Ticket updates and threads.', fields: ['webhook_url', 'verify_token'] },
  { id: 'intercom', name: 'Intercom', category: 'Support', desc: 'Conversations and leads.', fields: ['access_token', 'workspace_id'] },
  { id: 'help_scout', name: 'Help Scout', category: 'Support', desc: 'Mailbox conversations and tags.', fields: ['webhook_url', 'verify_token'] },
  { id: 'linear', name: 'Linear', category: 'Dev', desc: 'Issues, cycles, and updates.', fields: ['webhook_url', 'verify_token'] },
  { id: 'salesforce', name: 'Salesforce', category: 'CRM', desc: 'Case updates and leads.', fields: ['client_id', 'client_secret', 'refresh_token', 'instance_url'] },
  { id: 'hubspot', name: 'HubSpot', category: 'CRM', desc: 'Inbox and deal events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'pipedrive', name: 'Pipedrive', category: 'CRM', desc: 'Deals and activity tracking.', fields: ['webhook_url', 'verify_token'] },
  { id: 'zoho', name: 'Zoho CRM', category: 'CRM', desc: 'Leads, contacts, and notes.', fields: ['webhook_url', 'verify_token'] },
  { id: 'github', name: 'GitHub', category: 'Dev', desc: 'Issues, PRs, and webhooks.', fields: ['app_id', 'client_id', 'client_secret', 'webhook_secret'] },
  { id: 'gitlab', name: 'GitLab', category: 'Dev', desc: 'Issues, MR, and pipelines.', fields: ['base_url', 'access_token', 'webhook_secret'] },
  { id: 'bitbucket', name: 'Bitbucket', category: 'Dev', desc: 'Pull requests and builds.', fields: ['webhook_url', 'verify_token'] },
  { id: 'circleci', name: 'CircleCI', category: 'DevOps', desc: 'Builds and pipeline events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'jenkins', name: 'Jenkins', category: 'DevOps', desc: 'Job status and build events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'pagerduty', name: 'PagerDuty', category: 'Ops', desc: 'Alerts and incidents.', fields: ['api_token', 'service_id'] },
  { id: 'opsgenie', name: 'Opsgenie', category: 'Ops', desc: 'Alert routing and actions.', fields: ['webhook_url', 'verify_token'] },
  { id: 'servicenow', name: 'ServiceNow', category: 'Ops', desc: 'Incidents and tickets.', fields: ['webhook_url', 'verify_token'] },
  { id: 'datadog', name: 'Datadog', category: 'Ops', desc: 'Monitors, alerts, and events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'newrelic', name: 'New Relic', category: 'Ops', desc: 'APM alerts and incidents.', fields: ['webhook_url', 'verify_token'] },
  { id: 'splunk', name: 'Splunk', category: 'Ops', desc: 'Search alerts and dashboards.', fields: ['webhook_url', 'verify_token'] },
  { id: 'cloudwatch', name: 'AWS CloudWatch', category: 'Ops', desc: 'Alarms and metrics.', fields: ['webhook_url', 'verify_token'] },
  { id: 'prometheus_alertmanager', name: 'Prometheus Alertmanager', category: 'Ops', desc: 'Alert groups and receiver webhook events.', fields: ['webhook_url', 'receiver', 'route'] },
  { id: 'snmp', name: 'SNMP', category: 'Telemetry', desc: 'Passive SNMP traps and sensor notes.', fields: ['host', 'port', 'community'] },
  { id: 'arp', name: 'ARP Monitor', category: 'Telemetry', desc: 'Passive ARP observations and neighbor changes.', fields: ['listen_interface', 'sample_window_seconds'] },
  { id: 'syslog', name: 'Syslog', category: 'Telemetry', desc: 'Passive syslog UDP listener and sensor notes.', fields: ['host', 'port'] },
  { id: 'glimpser', name: 'Glimpser', category: 'Vision', desc: 'Camera detections and stream events.', fields: ['webhook_url'] },
  { id: 'hubitat', name: 'Hubitat', category: 'Home', desc: 'Maker API device events and automation signals.', fields: ['webhook_url'] },
  { id: 'activity_monitor', name: 'Activity Monitor', category: 'Home', desc: 'Desktop active/idle and screen state updates.', fields: ['webhook_url', 'site', 'zone', 'host'] },
  { id: 'home_assistant', name: 'Home Assistant', category: 'Home', desc: 'Automation and state-change events from Home Assistant.', fields: ['webhook_url', 'instance', 'event_filter'] },
  { id: 'unifi', name: 'UniFi', category: 'Network', desc: 'UniFi Network and Protect event webhooks.', fields: ['webhook_url', 'controller', 'site'] },
  { id: 'pfsense_opnsense', name: 'pfSense / OPNsense', category: 'Network', desc: 'Firewall and gateway event notifications.', fields: ['webhook_url', 'firewall', 'event_filter'] },
  { id: 'proxmox', name: 'Proxmox', category: 'Infra', desc: 'VM lifecycle and node state events.', fields: ['webhook_url', 'cluster', 'node'] },
  { id: 'docker_events', name: 'Docker Events', category: 'Infra', desc: 'Container lifecycle events from Docker hosts.', fields: ['webhook_url', 'host', 'event_filter'] },
  { id: 'ntfy', name: 'ntfy', category: 'Mobile', desc: 'Topic-based mobile push notifications.', fields: ['webhook_url', 'topic'] },
  { id: 'pushover', name: 'Pushover', category: 'Mobile', desc: 'Mobile push alerts and priority notifications.', fields: ['webhook_url', 'user_key'] },
  { id: 'frigate', name: 'Frigate', category: 'Vision', desc: 'Object detection events from Frigate NVR.', fields: ['webhook_url', 'camera', 'zone'] },
  { id: 's3', name: 'Amazon S3', category: 'Storage', desc: 'Object events and file changes.', fields: ['webhook_url', 'verify_token'] },
  { id: 'gdrive', name: 'Google Drive', category: 'Storage', desc: 'File changes and activity.', fields: ['webhook_url', 'verify_token'] },
  { id: 'dropbox', name: 'Dropbox', category: 'Storage', desc: 'File and folder events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'sftp', name: 'SFTP', category: 'Storage', desc: 'SFTP file ingestion.', fields: ['webhook_url', 'verify_token'] },
  { id: 'airtable', name: 'Airtable', category: 'Data', desc: 'Base record changes.', fields: ['webhook_url', 'verify_token'] },
  { id: 'postgres', name: 'PostgreSQL', category: 'Data', desc: 'Database change feeds.', fields: ['webhook_url', 'verify_token'] },
  { id: 'mysql', name: 'MySQL', category: 'Data', desc: 'Database changes and triggers.', fields: ['webhook_url', 'verify_token'] },
  { id: 'bigquery', name: 'BigQuery', category: 'Data', desc: 'Scheduled query exports.', fields: ['webhook_url', 'verify_token'] },
  { id: 'snowflake', name: 'Snowflake', category: 'Data', desc: 'Streams and task events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'kafka', name: 'Kafka', category: 'Data', desc: 'Streaming topics and offsets.', fields: ['brokers', 'topic', 'group_id', 'username', 'password'] },
  { id: 'rabbitmq', name: 'RabbitMQ', category: 'Data', desc: 'Queue messages and events.', fields: ['webhook_url', 'verify_token'] },
  { id: 'sample', name: 'Sample Connector', category: 'Dev', desc: 'Local test connector.', fields: ['endpoint', 'token'] },
];

const oauthProviderLabels = {
  google: 'Google SSO',
  microsoft: 'Microsoft SSO'
};
const ruleMatchesConnector = window.NormanConnectorRuleMatch?.ruleMatchesConnector
  || ((rule, connector) => {
    if (!rule || !connector) return false;
    const connectorId = Number.parseInt(connector.id, 10);
    const ruleConnectorId = Number.parseInt(rule.connector_id, 10);
    if (Number.isFinite(connectorId) && Number.isFinite(ruleConnectorId)) {
      return connectorId === ruleConnectorId;
    }
    return !!(rule.connector_type && rule.connector_type === connector.connector_type);
  });

document.addEventListener('DOMContentLoaded', () => {
  const preferredCatalogView = readCatalogViewPreference();
  if (preferredCatalogView) {
    catalogView = preferredCatalogView;
    catalogViewAuto = false;
  } else {
    catalogView = isNarrowViewport() ? 'list' : 'tiles';
    catalogViewAuto = true;
  }
  renderOauthStatusNotice();
  renderWebhookUrls();
  enableCopyButtons();
  setupIconObserver();
  loadConnectorTypes();
  fetchConnectorsAndRender();
  startStatusPolling();
  if (isPanelExpanded('approvals-panel')) {
    loadApprovals();
    startApprovalsPolling();
  }
  setupAutoCollapse();
  setupConnectorsMobileJumpNav();
  setupPanelPolling();
  setupCatalogControls();
  setupConnectorModal();
  setupCacheControls();
  setupRoutingSimulator();
  setupPassiveSensorsQuickstart();
  setupStarterPack();
  setupConnectorBundleControls();
  refreshApprovalsCount();
  routingRulesConnectorFilterId = readRoutingRulesFilterId();
  document.addEventListener('visibilitychange', onVisibilityChange);

  // Deep link support: /connectors.html?panel=approvals opens the approvals panel.
  try {
    const params = new URLSearchParams(window.location.search);
    const panel = (params.get('panel') || '').trim().toLowerCase();
    if (panel === 'approvals') {
      const el = document.getElementById('approvals-panel');
      if (el && window.bootstrap?.Collapse) {
        const instance = window.bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
        instance.show();
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  } catch (err) {
    // noop
  }

  const addForm = document.getElementById('add-connector-form');
  if (addForm) {
    addForm.addEventListener('submit', async (evt) => {
      evt.preventDefault();
      const nameInput = document.getElementById('connector-name');
      const typeInput = document.getElementById('connector-type');
      const configInput = document.getElementById('connector-config');
      clearError(nameInput);
      clearError(typeInput);
      clearError(configInput);

      const name = nameInput.value.trim();
      const type = typeInput.value.trim();
      let config = {};

      if (!name) {
        showError(nameInput, 'Name is required');
        return;
      }

      if (!type) {
        showError(typeInput, 'Type is required');
        return;
      }

      if (configInput.value.trim()) {
        try {
          config = JSON.parse(configInput.value);
        } catch (e) {
          showError(configInput, 'Config must be valid JSON');
          return;
        }
      }
      const connector = await createConnector({
        name,
        connector_type: type,
        config: config
      });
      document.querySelector('.connectors-container')
        .appendChild(createConnectorElement(connector));
      nameInput.value = '';
      typeInput.value = '';
      configInput.value = '';
    });
  }
});

function onVisibilityChange() {
  if (document.hidden) {
    stopStatusPolling();
    stopRoutingPolling();
    return;
  }
  startStatusPolling();
  if (isPanelExpanded('routing-events-panel') || isPanelExpanded('routing-jobs-panel')) {
    loadRoutingOpsPanels();
    startRoutingPolling();
  }
}

function readRoutingRulesFilterId() {
  try {
    const raw = localStorage.getItem(ROUTING_RULE_FILTER_KEY);
    if (!raw) return null;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) ? parsed : null;
  } catch (err) {
    return null;
  }
}

function writeRoutingRulesFilterId(connectorId) {
  try {
    if (Number.isFinite(connectorId)) {
      localStorage.setItem(ROUTING_RULE_FILTER_KEY, String(connectorId));
    } else {
      localStorage.removeItem(ROUTING_RULE_FILTER_KEY);
    }
  } catch (err) {
    // noop
  }
}

function setupAutoCollapse() {
  const panels = Array.from(document.querySelectorAll('.connectors-page .collapse'));
  if (!panels.length) return;
  panels.forEach(panel => {
    panel.addEventListener('show.bs.collapse', () => {
      panels.forEach(other => {
        if (other !== panel) {
          const instance = bootstrap.Collapse.getOrCreateInstance(other, { toggle: false });
          instance.hide();
        }
      });
    });
  });
}

function setupConnectorsMobileJumpNav() {
  const buttons = Array.from(document.querySelectorAll('[data-connectors-jump]'));
  if (!buttons.length) return;

  const targets = buttons
    .map((btn) => btn.getAttribute('data-target'))
    .filter(Boolean)
    .map((id) => document.getElementById(id))
    .filter(Boolean);

  const setActive = (targetId) => {
    buttons.forEach((btn) => {
      btn.classList.toggle('is-active', btn.getAttribute('data-target') === targetId);
    });
  };

  const showPanel = (panelId) => {
    if (!panelId) return;
    const panel = document.getElementById(panelId);
    if (!panel || !window.bootstrap?.Collapse) return;
    const instance = window.bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false });
    instance.show();
  };

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const panelId = btn.getAttribute('data-expand');
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target) return;
      showPanel(panelId);
      setActive(targetId);
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  if (!('IntersectionObserver' in window) || !targets.length) return;

  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible?.target?.id) return;
    setActive(visible.target.id);
  }, {
    root: null,
    threshold: [0.35, 0.6],
    rootMargin: '-20% 0px -45% 0px',
  });

  targets.forEach((target) => observer.observe(target));
}

function setupConnectorModal() {
  const modalEl = document.getElementById('connector-modal');
  if (!modalEl || !window.bootstrap) return;
  connectorModal = new window.bootstrap.Modal(modalEl, {
    backdrop: true,
    keyboard: true,
    focus: true
  });

  // Defensive close paths: if Bootstrap's backdrop click or ESC handling is
  // impeded by custom CSS, still allow dismissal.
  modalEl.addEventListener('mousedown', (evt) => {
    if (evt.target === modalEl) {
      connectorModal?.hide();
    }
  });
  document.addEventListener('keydown', (evt) => {
    if (evt.key === 'Escape') {
      connectorModal?.hide();
    }
  });

  const normalizeModalState = () => {
    // Ensure a stale backdrop/body lock never bricks the page.
    const openModals = document.querySelectorAll('.modal.show');
    if (openModals.length > 0) return;
    document.querySelectorAll('.modal-backdrop').forEach((node) => node.remove());
    document.body.classList.remove('modal-open');
    document.body.style.removeProperty('padding-right');
    activeCatalogItemId = null;
    lastModalDismissAt = Date.now();
    setModalValidation('');
    const testStatusEl = document.getElementById('connector-modal-test-status');
    testStatusEl?.classList.remove('connector-modal__test-status--ok', 'connector-modal__test-status--danger');
    if (testStatusEl) testStatusEl.textContent = '';
    const healthEl = document.getElementById('connector-modal-health');
    if (healthEl) healthEl.textContent = '';
  };

  modalEl.addEventListener('hidden.bs.modal', normalizeModalState);
  modalEl.addEventListener('shown.bs.modal', () => {
    // Keep only one backdrop in case rapid clicks generated duplicates.
    const backdrops = Array.from(document.querySelectorAll('.modal-backdrop'));
    backdrops.slice(0, -1).forEach((node) => node.remove());
  });

  const saveBtn = document.getElementById('connector-modal-save');
  const removeBtn = document.getElementById('connector-modal-remove');
  const testBtn = document.getElementById('connector-modal-test');
  const testStatusEl = document.getElementById('connector-modal-test-status');
  const validationEl = document.getElementById('connector-modal-validation');

  const setModalTestStatus = (message = '', level = 'info') => {
    if (!testStatusEl) return;
    testStatusEl.textContent = message;
    testStatusEl.classList.remove('connector-modal__test-status--ok', 'connector-modal__test-status--danger');
    if (level === 'ok') {
      testStatusEl.classList.add('connector-modal__test-status--ok');
    }
    if (level === 'danger') {
      testStatusEl.classList.add('connector-modal__test-status--danger');
    }
  };

  const findRequiredFieldInput = (fieldName) => {
    return Array.from(document.querySelectorAll('[data-required-field]'))
      .find((el) => el.getAttribute('data-required-field') === fieldName) || null;
  };

  const hasModalUnsavedChanges = () => {
    const nameInput = document.getElementById('connector-modal-name');
    const configInput = document.getElementById('connector-modal-config');
    if (!nameInput || !configInput || !activeModalConnector) return false;
    const currentName = nameInput.value.trim();
    if (currentName !== (activeModalConnector.name || '').trim()) return true;
    let parsedConfig = {};
    try {
      parsedConfig = parseModalConfigInput(configInput);
    } catch (err) {
      return true;
    }
    const existing = activeModalConnector.config || {};
    return JSON.stringify(parsedConfig) !== JSON.stringify(existing);
  };

  const runModalSave = async () => {
    if (!saveBtn || saveBtn.disabled) return;
    const nameInput = document.getElementById('connector-modal-name');
    const typeSelect = document.getElementById('connector-modal-type');
    const configInput = document.getElementById('connector-modal-config');
    if (!nameInput || !typeSelect || !configInput) return;
    clearError(nameInput);
    clearError(configInput);
    setModalValidation('', 'info', validationEl);
    const name = nameInput.value.trim();
    const type = typeSelect.value.trim();
    if (!name) {
      showError(nameInput, 'Name is required');
      setModalValidation('Name is required.', 'danger', validationEl);
      nameInput.focus();
      return;
    }
    if (!type) {
      setModalValidation('Connector type is missing.', 'danger', validationEl);
      return;
    }
    let config = {};
    if (configInput.value.trim()) {
      try {
        config = JSON.parse(configInput.value);
      } catch (e) {
        showError(configInput, 'Config must be valid JSON');
        setModalValidation('Config JSON is invalid. Fix the JSON and retry.', 'danger', validationEl);
        configInput.focus();
        return;
      }
    }
    clearRequiredFieldErrors();
    const missing = getMissingRequiredFields(type, config, activeModalRequiredFields, activeModalConnectionMode);
    if (missing.length) {
      markRequiredFieldErrors(missing);
      showError(configInput, `Missing required field(s): ${missing.slice(0, 3).join(', ')}`);
      setModalValidation(`Missing required fields: ${missing.join(', ')}.`, 'danger', validationEl);
      const firstMissingInput = findRequiredFieldInput(missing[0]);
      if (firstMissingInput instanceof HTMLElement) {
        firstMissingInput.focus();
      } else {
        configInput.focus();
      }
      return;
    }

    const semantic = validateConnectorConfigByType(type, config, activeModalRequiredFields, activeModalItem);
    if (!semantic.ok) {
      showError(configInput, semantic.errors[0] || 'Connector config is invalid');
      setModalValidation(semantic.errors.join(' '), 'danger', validationEl);
      configInput.focus();
      return;
    }
    if (semantic.warnings.length) {
      setModalValidation(semantic.warnings.join(' '), 'ok', validationEl);
    }

    saveBtn.disabled = true;
    if (activeModalMode === 'edit' && activeModalConnector) {
      try {
        await updateConnector(activeModalConnector.id, {
          name,
          connector_type: type,
          config
        });
      } catch (err) {
        setModalValidation(err?.message || 'Failed to update connector.', 'danger', validationEl);
        saveBtn.disabled = false;
        return;
      }
    } else {
      try {
        await createConnector({ name, connector_type: type, config });
      } catch (err) {
        setModalValidation(err?.message || 'Failed to create connector.', 'danger', validationEl);
        saveBtn.disabled = false;
        return;
      }
    }
    saveBtn.disabled = false;
    connectorModal.hide();
    await fetchConnectorsAndRender();
  };

  saveBtn?.addEventListener('click', async () => {
    await runModalSave();
  });

  testBtn?.addEventListener('click', async () => {
    if (!activeModalConnector) {
      setModalTestStatus('Save connector first, then test connection.', 'danger');
      return;
    }
    if (hasModalUnsavedChanges()) {
      setModalTestStatus('Unsaved changes detected. Save before test.', 'danger');
      return;
    }
    testBtn.disabled = true;
    setModalTestStatus('Testing...', 'info');
    try {
      const result = await testConnector(activeModalConnector.id);
      const statusText = typeof result === 'string'
        ? result
        : (result?.status || JSON.stringify(result));
      const ok = /ok|healthy|active|connected|success/i.test(statusText);
      setModalTestStatus(`Result: ${statusText}`, ok ? 'ok' : 'danger');
    } catch (err) {
      setModalTestStatus(`Test failed: ${err?.message || 'unknown error'}`, 'danger');
    } finally {
      testBtn.disabled = false;
    }
  });

  modalEl.addEventListener('keydown', (evt) => {
    if (!connectorModal || !modalEl.classList.contains('show')) return;
    const key = evt.key.toLowerCase();
    const target = evt.target;
    if ((evt.metaKey || evt.ctrlKey) && key === 's') {
      evt.preventDefault();
      runModalSave();
      return;
    }
    if (
      evt.key === 'Enter' &&
      !evt.shiftKey &&
      !evt.altKey &&
      !evt.ctrlKey &&
      !evt.metaKey
    ) {
      if (target instanceof HTMLTextAreaElement) return;
      if (target instanceof HTMLButtonElement || target instanceof HTMLAnchorElement) return;
      evt.preventDefault();
      runModalSave();
    }
  });

  removeBtn?.addEventListener('click', async () => {
    if (!activeModalConnector) return;
    if (!confirm(`Remove connector "${activeModalConnector.name}"?`)) return;
    await deleteConnector(activeModalConnector.id);
    connectorModal.hide();
    await fetchConnectorsAndRender();
  });
}

function renderOauthStatusNotice() {
  const params = new URLSearchParams(window.location.search);
  const oauth = params.get('oauth');
  if (!oauth) return;
  const detail = params.get('detail') || '';
  const connectorId = params.get('connector_id') || '';
  const host = document.querySelector('.connectors-page');
  if (!host) return;
  const alert = document.createElement('div');
  alert.className = `alert ${oauth === 'success' ? 'alert-success' : 'alert-danger'} mb-2`;
  const suffix = connectorId ? ` (connector ${connectorId})` : '';
  alert.textContent = oauth === 'success'
    ? `Connector SSO connected${suffix}.`
    : `Connector SSO failed${detail ? `: ${detail}` : ''}.`;
  host.prepend(alert);
  params.delete('oauth');
  params.delete('detail');
  params.delete('connector_id');
  const qs = params.toString();
  window.history.replaceState({}, '', `${window.location.pathname}${qs ? `?${qs}` : ''}`);
}

function renderConnectorModalSSO(item, installedConnector) {
  const ssoHost = document.getElementById('connector-modal-sso');
  if (!ssoHost) return;
  const oauth = item?.oauth;
  const providers = Array.isArray(oauth?.providers) ? oauth.providers : [];
  const snapshot = installedConnector ? getConnectorAuthSnapshot(installedConnector, oauth) : null;
  const activeProvider = snapshot?.provider || '';
  const connectedAt = snapshot?.connectedAt || '';
  const statusText = snapshot ? authStatusText(snapshot) : 'No SSO connection yet.';
  const scopes = snapshot?.scopes || [];
  if (!providers.length) {
    ssoHost.innerHTML = '<div class="small text-muted">Connector-level SSO is unavailable. Configure credentials manually in JSON.</div>';
    return;
  }

  const connectorId = installedConnector?.id || 0;
  const buttons = providers
    .map((provider) => `<button class="btn btn-sm btn-outline-secondary" type="button" data-oauth-provider="${provider}">${oauthProviderLabels[provider] || provider}</button>`)
    .join('');
  const providerText = activeProvider
    ? `via ${oauthProviderLabels[activeProvider] || activeProvider}`
    : 'not connected';
  const disconnectBtn = connectorId
    ? '<button class="btn btn-sm btn-outline-danger" type="button" data-oauth-disconnect="1">Disconnect</button>'
    : '';
  const scopeBadges = scopes.length
    ? scopes.slice(0, 4).map((scope) => `<span class="field-chip ok">${scope}</span>`).join('')
    : '<span class="small text-muted">No scopes discovered yet.</span>';
  const scopeOverflow = scopes.length > 4
    ? `<span class="small text-muted">+${scopes.length - 4} more</span>`
    : '';

  ssoHost.innerHTML = `
    <div class="connector-sso">
      <div class="d-flex align-items-center justify-content-between flex-wrap gap-2">
        <div class="small text-muted">${statusText}${activeProvider ? ` ${providerText}` : ''}${connectedAt ? ` • connected ${connectedAt}` : ''}</div>
        <div class="d-flex flex-wrap gap-2">${buttons}${disconnectBtn}</div>
      </div>
      <div class="connector-sso__scopes">
        ${scopeBadges}${scopeOverflow}
      </div>
    </div>
  `;
  ssoHost.querySelectorAll('[data-oauth-provider]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const provider = btn.getAttribute('data-oauth-provider');
      const query = new URLSearchParams({
        connector_type: item.id,
        provider: provider || ''
      });
      if (connectorId) {
        query.set('connector_id', String(connectorId));
      }
      window.location.href = `/api/v1/connectors/oauth/start?${query.toString()}`;
    });
  });
  const disconnect = ssoHost.querySelector('[data-oauth-disconnect="1"]');
  disconnect?.addEventListener('click', async () => {
    if (!connectorId) return;
    await disconnectConnectorOauth(connectorId);
    await fetchConnectorsAndRender();
    const refreshed = cachedConnectors.find(conn => conn.id === connectorId) || null;
    renderConnectorModalSSO(item, refreshed);
    const configInput = document.getElementById('connector-modal-config');
    if (configInput && refreshed) {
      configInput.value = JSON.stringify(refreshed.config || {}, null, 2);
    }
  });
}

function getCachedConnectorRuleCount(connectorId) {
  const entry = connectorRuleCountCache.get(connectorId);
  if (!entry) return null;
  if ((Date.now() - entry.savedAt) > CONNECTOR_RULE_COUNT_TTL_MS) return null;
  return entry.count;
}

function setCachedConnectorRuleCount(connectorId, count) {
  connectorRuleCountCache.set(connectorId, { savedAt: Date.now(), count });
}

async function fetchConnectorRuleCount(connector) {
  if (!connector?.id) return 0;
  const cached = getCachedConnectorRuleCount(connector.id);
  if (Number.isFinite(cached)) return cached;
  try {
    const rules = await fetchRoutingRules();
    const count = (rules || []).filter((rule) => ruleMatchesConnector(rule, connector)).length;
    setCachedConnectorRuleCount(connector.id, count);
    return count;
  } catch (err) {
    return null;
  }
}

async function renderModalHealthSnapshot(connector) {
  const healthEl = document.getElementById('connector-modal-health');
  if (!healthEl) return;
  if (!connector) {
    healthEl.innerHTML = '<span class="connector-modal__health-chip">No connector persisted yet</span>';
    return;
  }
  const lastSent = connector.last_message_sent || 'never';
  const lastReceived = connector.last_message_received || 'never';
  healthEl.innerHTML = `
    <span class="connector-modal__health-chip">Last sent: ${lastSent}</span>
    <span class="connector-modal__health-chip">Last received: ${lastReceived}</span>
    <button type="button" class="btn btn-link btn-sm p-0 connector-modal__health-chip connector-modal__health-chip--action" id="connector-modal-health-rules">Rules: loading...</button>
  `;

  const connectorId = connector.id;
  const count = await fetchConnectorRuleCount(connector);
  if (!activeModalConnector || activeModalConnector.id !== connectorId) return;
  const rulesEl = document.getElementById('connector-modal-health-rules');
  if (!rulesEl) return;
  if (!Number.isFinite(count)) {
    rulesEl.textContent = 'Rules: unavailable';
    return;
  }
  rulesEl.textContent = `Rules: ${count}`;
  rulesEl.addEventListener('click', async () => {
    await jumpToConnectorRules(connector);
  });
}

async function jumpToConnectorRules(connector) {
  if (!connector?.id) return;
  routingRulesConnectorFilterId = connector.id;
  writeRoutingRulesFilterId(connector.id);
  connectorModal?.hide();
  const panel = document.getElementById('routing-rules-panel');
  if (panel && window.bootstrap?.Collapse) {
    const instance = window.bootstrap.Collapse.getOrCreateInstance(panel, { toggle: false });
    instance.show();
  }
  const connectorSelect = document.getElementById('routing-rule-connector');
  if (connectorSelect) {
    connectorSelect.value = String(connector.id);
  }
  if (!routingLoaded) {
    routingLoaded = true;
    await loadRoutingUI();
    return;
  }
  await loadRoutingRules();
}

function parseModalConfigInput(configInput) {
  if (!configInput) return {};
  const raw = configInput.value.trim();
  if (!raw) return {};
  return JSON.parse(raw);
}

function syncRequiredEditorFromConfig(configInput, requiredFields) {
  if (!configInput || !Array.isArray(requiredFields) || !requiredFields.length) return;
  let config;
  try {
    config = parseModalConfigInput(configInput);
  } catch (err) {
    return;
  }
  requiredFields.forEach((field) => {
    const input = document.querySelector(`[data-required-field="${field}"]`);
    if (!input) return;
    const value = config[field];
    input.value = value === null || value === undefined ? '' : String(value);
  });
}

function syncConfigFromRequiredEditor(configInput, requiredFields, validationEl = null) {
  if (!configInput || !Array.isArray(requiredFields) || !requiredFields.length) return;
  let config = {};
  try {
    config = parseModalConfigInput(configInput);
  } catch (err) {
    setModalValidation('Config JSON is invalid. Fix it or use Sync from JSON.', 'danger', validationEl);
    return;
  }
  requiredFields.forEach((field) => {
    const input = document.querySelector(`[data-required-field="${field}"]`);
    if (!input) return;
    config[field] = input.value;
  });
  configInput.value = JSON.stringify(config, null, 2);
  clearError(configInput);
}

function renderRequiredFieldEditor(configInput, requiredFields, validationEl = null) {
  const host = document.getElementById('connector-modal-required-editor');
  if (!host) return;
  if (!Array.isArray(requiredFields) || !requiredFields.length) {
    host.classList.add('d-none');
    host.innerHTML = '';
    return;
  }
  host.classList.remove('d-none');
  host.innerHTML = `
    <div class="small text-muted">Quick setup fields</div>
    <div class="connector-modal__required-grid">
      ${requiredFields.map((field) => `
        <div class="connector-modal__required-item">
          <label class="form-label">${field}</label>
          <input type="text" class="form-control form-control-sm" data-required-field="${field}">
        </div>
      `).join('')}
    </div>
    <div class="connector-modal__required-actions">
      <button type="button" class="btn btn-link btn-sm p-0" id="connector-modal-sync-to-json">Apply to JSON</button>
      <button type="button" class="btn btn-link btn-sm p-0" id="connector-modal-sync-from-json">Sync from JSON</button>
    </div>
  `;
  syncRequiredEditorFromConfig(configInput, requiredFields);

  host.querySelectorAll('[data-required-field]').forEach((input) => {
    input.addEventListener('input', () => {
      input.classList.remove('is-invalid');
      syncConfigFromRequiredEditor(configInput, requiredFields, validationEl);
    });
  });
  host.querySelector('#connector-modal-sync-to-json')?.addEventListener('click', () => {
    syncConfigFromRequiredEditor(configInput, requiredFields, validationEl);
    setModalValidation('Structured fields applied to config JSON.', 'ok', validationEl);
  });
  host.querySelector('#connector-modal-sync-from-json')?.addEventListener('click', () => {
    syncRequiredEditorFromConfig(configInput, requiredFields);
    setModalValidation('Structured fields synced from config JSON.', 'ok', validationEl);
  });
}


function renderConnectorModeSelector(configInput, item, fieldsNote, validationEl = null) {
  const host = document.getElementById('connector-modal-mode');
  if (!host) return;
  const modes = getConnectorModeOptions(item?.id || '');
  if (!modes.length) {
    host.classList.add('d-none');
    host.innerHTML = '';
    activeModalConnectionMode = null;
    return;
  }

  let config = {};
  try {
    config = parseModalConfigInput(configInput);
  } catch (err) {
    config = {};
  }
  if (!activeModalConnectionMode) {
    activeModalConnectionMode = detectConnectorMode(item.id, config) || modes[0].id;
  }

  host.classList.remove('d-none');
  const recommendedMode = getPreferredConnectorMode(item.id);
  host.innerHTML = `
    <div class="small text-muted">Connection mode${recommendedMode ? ` (recommended: ${recommendedMode})` : ''}</div>
    <div class="connector-modal__mode-grid">
      ${modes.map((mode) => `
        <button type="button" class="btn btn-outline-secondary btn-sm connector-modal__mode-btn ${mode.id === activeModalConnectionMode ? 'is-active' : ''}" data-connector-mode="${mode.id}">
          ${mode.label}
        </button>
      `).join('')}
    </div>
  `;

  host.querySelectorAll('[data-connector-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mode = btn.getAttribute('data-connector-mode') || '';
      if (!mode) return;
      activeModalConnectionMode = mode;

      let current = {};
      try {
        current = parseModalConfigInput(configInput);
      } catch (err) {
        current = {};
      }

      if (item.id === 'discord') {
        if (mode === 'webhook' && !isPresentValue(current.webhook_url)) current.webhook_url = '';
        if (mode === 'bot') {
          if (!isPresentValue(current.token)) current.token = '';
          if (!isPresentValue(current.channel_id)) current.channel_id = '';
        }
      }
      if (item.id === 'teams') {
        if (mode === 'webhook' && !isPresentValue(current.webhook_url)) current.webhook_url = '';
        if (mode === 'bot') {
          ['app_id', 'app_password', 'tenant_id', 'bot_endpoint'].forEach((field) => {
            if (!isPresentValue(current[field])) current[field] = '';
          });
        }
      }

      configInput.value = JSON.stringify(current, null, 2);
      clearError(configInput);
      clearRequiredFieldErrors();
      updateModalRequiredFields(configInput, item, fieldsNote, validationEl);
      renderConnectorModeSelector(configInput, item, fieldsNote, validationEl);
      setModalValidation(`Mode set: ${mode}.`, 'ok', validationEl);
    });
  });
}

async function fetchTmuxPanes(socketPath = '') {
  const url = new URL('/api/v1/tmux/panes', window.location.origin);
  if (socketPath) url.searchParams.set('socket_path', socketPath);
  const resp = await fetch(url.toString(), { headers: { 'Accept': 'application/json' } });
  if (!resp.ok) {
    const msg = resp.status === 503 ? 'tmux is unavailable (no server / permission issue).' : `Failed to load tmux panes (HTTP ${resp.status}).`;
    throw new Error(msg);
  }
  const data = await resp.json();
  return Array.isArray(data?.items) ? data.items : [];
}

async function fetchTmuxFavorites() {
  const url = new URL('/api/v1/console_targets/', window.location.origin);
  url.searchParams.set('kind', 'tmux');
  const resp = await fetch(url.toString(), { headers: { 'Accept': 'application/json' } });
  if (!resp.ok) {
    throw new Error(`Failed to load favorites (HTTP ${resp.status}).`);
  }
  const data = await resp.json();
  return Array.isArray(data) ? data : [];
}

function formatTmuxPaneLabel(pane) {
  const target = pane?.target || '';
  const title = pane?.pane_title || '';
  const cmd = pane?.pane_current_command || '';
  const path = pane?.pane_current_path || '';
  const bits = [target];
  if (title && title !== 'tmux') bits.push(title);
  if (cmd) bits.push(cmd);
  if (path) bits.push(path);
  return bits.filter(Boolean).join(' • ');
}

function renderConnectorModalTmuxPicker(configInput, item, validationEl = null) {
  const host = document.getElementById('connector-modal-tmux');
  if (!host) return;
  if (!item || item.id !== 'tmux') {
    host.classList.add('d-none');
    host.innerHTML = '';
    return;
  }

  host.classList.remove('d-none');
  host.innerHTML = `
    <div class="d-flex align-items-center justify-content-between gap-2">
      <div class="small text-muted">Pick a running tmux pane (optional)</div>
      <button type="button" class="btn btn-outline-secondary btn-sm" id="connector-modal-tmux-refresh">Refresh</button>
    </div>
    <div class="d-flex gap-2 align-items-center mt-2 flex-wrap">
      <select class="form-select form-select-sm" id="connector-modal-tmux-favorite" style="min-width: 280px;">
        <option value="" selected disabled>Loading favorites…</option>
      </select>
      <select class="form-select form-select-sm" id="connector-modal-tmux-target" style="min-width: 280px;">
        <option value="" selected disabled>Loading panes…</option>
      </select>
      <div class="small text-muted" id="connector-modal-tmux-status"></div>
    </div>
  `;

  const favSelect = host.querySelector('#connector-modal-tmux-favorite');
  const select = host.querySelector('#connector-modal-tmux-target');
  const refreshBtn = host.querySelector('#connector-modal-tmux-refresh');
  const statusEl = host.querySelector('#connector-modal-tmux-status');
  if (!favSelect || !select || !refreshBtn || !statusEl) return;

  const loadFavorites = async () => {
    favSelect.innerHTML = '<option value="" selected disabled>Loading favorites…</option>';
    try {
      const favorites = await fetchTmuxFavorites();
      if (!favorites.length) {
        favSelect.innerHTML = '<option value="" selected disabled>No favorites yet</option>';
        return;
      }
      favSelect.innerHTML = `
        <option value="" selected disabled>Use favorite…</option>
        ${favorites.map((fav) => `
          <option value="${escapeHtml(String(fav.id))}"
            data-target="${escapeHtml(fav.target || '')}"
            data-session="${escapeHtml(fav.session_name || '')}"
            data-socket="${escapeHtml(fav.socket_path || '')}">
            ${escapeHtml(fav.name || fav.target || 'favorite')}
          </option>
        `).join('')}
      `;
    } catch (err) {
      favSelect.innerHTML = '<option value="" selected disabled>Favorites unavailable</option>';
    }
  };

  const load = async () => {
    let cfg = {};
    try {
      cfg = parseModalConfigInput(configInput);
    } catch (err) {
      cfg = {};
    }

    const socketPath = typeof cfg.socket_path === 'string' ? cfg.socket_path.trim() : '';
    statusEl.textContent = 'Loading…';
    select.innerHTML = '<option value="" selected disabled>Loading panes…</option>';

    try {
      const panes = await fetchTmuxPanes(socketPath);
      if (!panes.length) {
        select.innerHTML = '<option value="" selected disabled>No panes found</option>';
        statusEl.textContent = socketPath
          ? 'No panes found on that socket.'
          : 'No panes found. Start tmux (or set socket_path).';
        return;
      }

      select.innerHTML = `
        <option value="" selected disabled>Select a pane…</option>
        ${panes.map((pane) => `
          <option
            value="${escapeHtml(pane.target || '')}"
            data-session="${escapeHtml(pane.session_name || '')}"
            data-pane-tty="${escapeHtml(pane.pane_tty || '')}">
            ${escapeHtml(formatTmuxPaneLabel(pane))}
          </option>
        `).join('')}
      `;
      statusEl.textContent = `${panes.length} pane${panes.length === 1 ? '' : 's'} found.`;
    } catch (err) {
      const msg = err?.message ? String(err.message) : 'Failed to load tmux panes.';
      select.innerHTML = '<option value="" selected disabled>Load failed</option>';
      statusEl.textContent = msg;
      setModalValidation(msg, 'danger', validationEl);
    }
  };

  refreshBtn.addEventListener('click', () => {
    loadFavorites();
    load();
  });
  favSelect.addEventListener('change', () => {
    const opt = favSelect.selectedOptions?.[0];
    const target = opt?.getAttribute('data-target') || '';
    const session = opt?.getAttribute('data-session') || '';
    const socket = opt?.getAttribute('data-socket') || '';
    if (!target) return;

    let current = {};
    try {
      current = parseModalConfigInput(configInput);
    } catch (err) {
      current = {};
    }

    if (socket) current.socket_path = socket;
    if (session) current.session = session;
    if (!current.session && typeof target === 'string' && target.includes(':')) {
      current.session = target.split(':')[0];
    }
    current.target = target;
    delete current.pane_tty;

    configInput.value = JSON.stringify(current, null, 2);
    configInput.dispatchEvent(new Event('input', { bubbles: true }));
    setModalValidation(`tmux favorite loaded: ${target}`, 'ok', validationEl);
  });
  select.addEventListener('change', () => {
    const opt = select.selectedOptions?.[0];
    const target = opt?.value || '';
    const session = opt?.getAttribute('data-session') || '';
    const paneTty = opt?.getAttribute('data-pane-tty') || '';
    if (!target) return;

    let current = {};
    try {
      current = parseModalConfigInput(configInput);
    } catch (err) {
      current = {};
    }
    if (session) current.session = session;
    current.target = target;
    if (paneTty) {
      current.pane_tty = paneTty;
    } else {
      delete current.pane_tty;
    }

    configInput.value = JSON.stringify(current, null, 2);
    configInput.dispatchEvent(new Event('input', { bubbles: true }));
    setModalValidation(`tmux target set: ${target}`, 'ok', validationEl);
  });

  loadFavorites();
  load();
}

function renderConnectorModalWebhookHelper(configInput, item, installedConnector, validationEl = null) {
  const host = document.getElementById('connector-modal-webhook');
  if (!host) return;
  const helper = MODAL_WEBHOOK_HELPERS[item?.id || ''];
  if (!helper) {
    host.classList.add('d-none');
    host.innerHTML = '';
    return;
  }

  const connectorId = installedConnector?.id ? String(installedConnector.id) : '{connector_id}';
  const webhookUrl = buildConnectorWebhookUrl(item.id, connectorId);
  const samplePayload = PASSIVE_SENSOR_PRESETS[item.id]?.payload || null;
  const samplePayloadJson = samplePayload ? JSON.stringify(samplePayload, null, 2) : '';
  const hasConcreteId = connectorId !== '{connector_id}';

  host.classList.remove('d-none');
  host.innerHTML = `
    <div class="connector-modal__webhook-head">
      <div class="small text-muted">${helper.title}</div>
      <div class="small text-muted">${helper.hint}</div>
    </div>
    <div class="input-group input-group-sm">
      <input type="text" class="form-control" value="${escapeHtml(webhookUrl)}" readonly id="connector-modal-webhook-url">
      <button type="button" class="btn btn-outline-secondary" id="connector-modal-webhook-copy">Copy URL</button>
      <button type="button" class="btn btn-outline-secondary" id="connector-modal-webhook-bind">Add to JSON</button>
    </div>
    <div class="d-flex flex-wrap gap-2 align-items-center">
      ${samplePayload ? '<button type="button" class="btn btn-outline-secondary btn-sm" id="connector-modal-webhook-copy-payload">Copy Sample Payload</button>' : ''}
      <span class="small text-muted">${hasConcreteId ? 'Live URL ready.' : 'Save connector to replace {connector_id} with a live id.'}</span>
    </div>
  `;

  const copyBtn = host.querySelector('#connector-modal-webhook-copy');
  const bindBtn = host.querySelector('#connector-modal-webhook-bind');
  const copyPayloadBtn = host.querySelector('#connector-modal-webhook-copy-payload');

  copyBtn?.addEventListener('click', async () => {
    const ok = await copyTextToClipboard(webhookUrl);
    setModalValidation(ok ? 'Webhook URL copied.' : 'Clipboard copy failed.', ok ? 'ok' : 'danger', validationEl);
  });

  bindBtn?.addEventListener('click', () => {
    let config = {};
    try {
      config = parseModalConfigInput(configInput);
    } catch (err) {
      setModalValidation('Config JSON is invalid. Fix it before binding webhook URL.', 'danger', validationEl);
      return;
    }
    config.inbound_webhook_url = webhookUrl;
    configInput.value = JSON.stringify(config, null, 2);
    configInput.dispatchEvent(new Event('input', { bubbles: true }));
    setModalValidation('Added inbound_webhook_url to config JSON.', 'ok', validationEl);
  });

  copyPayloadBtn?.addEventListener('click', async () => {
    const ok = await copyTextToClipboard(samplePayloadJson);
    setModalValidation(ok ? 'Sample payload copied.' : 'Clipboard copy failed.', ok ? 'ok' : 'danger', validationEl);
  });
}

function updateModalRequiredFields(configInput, item, fieldsNote, validationEl = null) {
  let config = {};
  try {
    config = parseModalConfigInput(configInput);
  } catch (err) {
    config = {};
  }
  const allFields = connectorFieldMap[item.id] || item.fields || [];
  activeModalRequiredFields = getRequiredFieldsForMode(item.id, config, allFields, activeModalConnectionMode);
  renderRequiredFieldEditor(configInput, activeModalRequiredFields, validationEl);
  syncRequiredEditorFromConfig(configInput, activeModalRequiredFields);
  if (fieldsNote) {
    if (activeModalRequiredFields.length) {
      const modeLabel = activeModalConnectionMode ? ` (${activeModalConnectionMode})` : '';
      fieldsNote.innerHTML = `Required fields${modeLabel}: ${activeModalRequiredFields.join(', ')} <button type="button" class="btn btn-link btn-sm p-0 ms-1" id="connector-modal-fill-required">Fill Missing Keys</button>`;
      const fillBtn = document.getElementById('connector-modal-fill-required');
      fillBtn?.addEventListener('click', () => {
        fillMissingRequiredKeys(configInput, activeModalRequiredFields, validationEl);
        syncRequiredEditorFromConfig(configInput, activeModalRequiredFields);
      });
    } else {
      fieldsNote.textContent = 'No required fields.';
    }
  }
}

function openConnectorModal({ item, installedConnector, mode, supported }) {
  const modalEl = document.getElementById('connector-modal');
  if (!modalEl || !connectorModal) return;
  activeModalItem = item;
  activeModalConnector = installedConnector || null;
  activeModalMode = mode;
  const title = document.getElementById('connector-modal-title');
  const subtitle = document.getElementById('connector-modal-subtitle');
  const nameInput = document.getElementById('connector-modal-name');
  const typeSelect = document.getElementById('connector-modal-type');
  const configInput = document.getElementById('connector-modal-config');
  const fieldsNote = document.getElementById('connector-modal-fields');
  const validationEl = document.getElementById('connector-modal-validation');
  const removeBtn = document.getElementById('connector-modal-remove');
  const testBtn = document.getElementById('connector-modal-test');
  const testStatusEl = document.getElementById('connector-modal-test-status');
  const saveBtn = document.getElementById('connector-modal-save');

  if (!nameInput || !typeSelect || !configInput || !fieldsNote) return;
  const fields = connectorFieldMap[item.id] || item.fields || [];
  activeModalConnectionMode = null;
  const template = fields.reduce((acc, field) => {
    acc[field] = '';
    return acc;
  }, {});

  title.textContent = installedConnector ? `Edit ${installedConnector.name}` : `Add ${item.name}`;
  subtitle.textContent = supported ? item.desc : `${item.desc} (coming soon)`;
  nameInput.value = installedConnector ? installedConnector.name : `${item.name} Connector`;
  typeSelect.innerHTML = '';
  const opt = document.createElement('option');
  opt.value = item.id;
  opt.textContent = item.name;
  typeSelect.appendChild(opt);
  typeSelect.disabled = true;
  configInput.value = JSON.stringify(installedConnector?.config || template, null, 2);
  renderModalHealthSnapshot(installedConnector);
  clearError(nameInput);
  clearError(configInput);
  setModalValidation('', 'info', validationEl);
  updateModalRequiredFields(configInput, item, fieldsNote, validationEl);
  renderConnectorModalPresets(configInput, item, activeModalRequiredFields, validationEl);
  renderConnectorModeSelector(configInput, item, fieldsNote, validationEl);
  renderConnectorModalTmuxPicker(configInput, item, validationEl);
  renderConnectorModalWebhookHelper(configInput, item, installedConnector, validationEl);
  configInput.oninput = () => {
    clearError(configInput);
    clearRequiredFieldErrors();
    updateModalRequiredFields(configInput, item, fieldsNote, validationEl);
    renderConnectorModeSelector(configInput, item, fieldsNote, validationEl);
  };
  renderConnectorModalSSO(item, installedConnector);
  if (removeBtn) {
    removeBtn.disabled = !installedConnector;
  }
  if (testBtn) {
    testBtn.disabled = !supported || !installedConnector;
  }
  if (testStatusEl) {
    testStatusEl.textContent = installedConnector
      ? 'Ready to test saved connector state.'
      : 'Save connector first, then test connection.';
    testStatusEl.classList.remove('connector-modal__test-status--ok', 'connector-modal__test-status--danger');
  }
  if (saveBtn) {
    saveBtn.disabled = !supported;
  }
  connectorModal.show();
}

function setModalValidation(message, level = 'info', validationEl = null) {
  const el = validationEl || document.getElementById('connector-modal-validation');
  if (!el) return;
  if (!message) {
    el.classList.add('d-none');
    el.textContent = '';
    el.classList.remove('connector-modal__validation--danger', 'connector-modal__validation--ok');
    return;
  }
  el.classList.remove('d-none');
  el.textContent = message;
  el.classList.toggle('connector-modal__validation--danger', level === 'danger');
  el.classList.toggle('connector-modal__validation--ok', level === 'ok');
}

function fillMissingRequiredKeys(configInput, requiredFields, validationEl = null) {
  if (!configInput || !Array.isArray(requiredFields) || requiredFields.length === 0) return;
  let config = {};
  if (configInput.value.trim()) {
    try {
      config = JSON.parse(configInput.value);
    } catch (err) {
      showError(configInput, 'Config must be valid JSON');
      setModalValidation('Cannot auto-fill while config JSON is invalid.', 'danger', validationEl);
      return;
    }
  }
  let added = 0;
  requiredFields.forEach((field) => {
    if (!(field in config)) {
      config[field] = '';
      added += 1;
    }
  });
  configInput.value = JSON.stringify(config, null, 2);
  clearError(configInput);
  if (added > 0) {
    setModalValidation(`Added ${added} missing key${added === 1 ? '' : 's'} to config.`, 'ok', validationEl);
    return;
  }
  setModalValidation('All required keys are already present.', 'ok', validationEl);
}

function setupCatalogControls() {
  const catalog = document.getElementById('connector-catalog');
  const viewButtons = document.querySelectorAll('[data-view]');
  const filterButtons = document.querySelectorAll('[data-filter]');
  const groupSelect = document.getElementById('connector-catalog-group');
  if (!catalog) return;

  const applyView = (view, { persist = false, markManual = false } = {}) => {
    const nextView = view === 'list' ? 'list' : 'tiles';
    const changed = catalogView !== nextView;
    catalogView = nextView;
    if (markManual) {
      catalogViewAuto = false;
    }
    if (persist) {
      writeCatalogViewPreference(nextView);
    }
    syncCatalogViewButtons();
    if (changed) {
      resetCatalogRenderLimit();
      renderConnectorCatalog(document.getElementById('connector-catalog-search')?.value?.trim() || '');
    }
  };

  filterButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      filterButtons.forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      catalogFilter = btn.dataset.filter || 'all';
      resetCatalogRenderLimit();
      renderConnectorCatalog(document.getElementById('connector-catalog-search')?.value?.trim() || '');
    });
  });

  viewButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      applyView(btn.dataset.view || 'tiles', { persist: true, markManual: true });
    });
  });

  if (groupSelect) {
    groupSelect.addEventListener('change', () => {
      catalogGroup = groupSelect.value || 'none';
      resetCatalogRenderLimit();
      renderConnectorCatalog(document.getElementById('connector-catalog-search')?.value?.trim() || '');
    });
  }

  if (!catalog.dataset.mobileViewAutoBound) {
    const onResize = debounce(() => {
      if (!catalogViewAuto) return;
      const nextView = isNarrowViewport() ? 'list' : 'tiles';
      applyView(nextView);
    }, 180);
    window.addEventListener('resize', onResize);
    catalog.dataset.mobileViewAutoBound = '1';
  }

  syncCatalogViewButtons();
}

function initCatalogTooltips() {
  if (!window.bootstrap || !window.bootstrap.Tooltip) return;
  catalogTooltips.forEach(tip => tip.dispose());
  catalogTooltips = [];
  const nodes = document.querySelectorAll('.connector-tile[data-bs-toggle="tooltip"]');
  nodes.forEach((node) => {
    catalogTooltips.push(new window.bootstrap.Tooltip(node, {
      container: 'body',
      placement: 'auto',
      // `focus`-triggered tooltips can get "stuck" on click/touch, which makes it
      // feel like a tile can't be "clicked off". Hover-only keeps tooltips helpful
      // on desktop without interfering with taps/clicks.
      trigger: 'hover',
      boundary: 'window',
      delay: { show: 150, hide: 50 }
    }));
  });
}

function setupIconObserver() {
  if (!('IntersectionObserver' in window)) return;
  iconObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const img = entry.target;
      enqueueIcon(img);
      iconObserver.unobserve(img);
    });
  }, { rootMargin: '24px' });
}

function renderConnectorTypeSelect(available, select) {
  select.innerHTML = '<option value="" disabled selected>Select a type</option>';
  available.forEach((item) => {
    const opt = document.createElement('option');
    opt.value = item.id;
    const override = connectorCatalog.find((entry) => entry.id === item.id);
    opt.textContent = override?.name || item.name || item.id;
    opt.dataset.fields = JSON.stringify(connectorFieldMap[item.id] || []);
    select.appendChild(opt);
  });
}

function readCachedJson(key, ttlMs) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    if (typeof parsed.saved_at !== 'number') return null;
    if (Date.now() - parsed.saved_at > ttlMs) return null;
    return parsed.data;
  } catch (e) {
    return null;
  }
}

function writeCachedJson(key, data) {
  try {
    localStorage.setItem(key, JSON.stringify({
      saved_at: Date.now(),
      data
    }));
    updateConnectorCacheAgeLabel();
  } catch (e) {
    // Ignore storage failures (private mode/quota).
  }
}

function clearConnectorCaches(includeTypes = false) {
  try {
    localStorage.removeItem(CONNECTORS_CACHE_KEY);
    if (includeTypes) {
      localStorage.removeItem(CONNECTOR_TYPES_CACHE_KEY);
    }
    updateConnectorCacheAgeLabel();
  } catch (e) {
    // noop
  }
}

function getCacheSavedAt(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed.saved_at === 'number' ? parsed.saved_at : null;
  } catch (e) {
    return null;
  }
}

function formatAge(ms) {
  if (ms < 2000) return 'just now';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hrs = Math.floor(min / 60);
  return `${hrs}h ago`;
}

function formatRelativeSeconds(seconds) {
  if (!Number.isFinite(seconds)) return '';
  if (seconds <= 0) return 'expired';
  if (seconds < 3600) return `${Math.ceil(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.ceil(seconds / 3600)}h`;
  return `${Math.ceil(seconds / 86400)}d`;
}

function parseOauthScopes(raw) {
  if (Array.isArray(raw)) return raw.filter((scope) => typeof scope === 'string' && scope.trim());
  if (typeof raw === 'string' && raw.trim()) return raw.split(/\s+/).filter(Boolean);
  return [];
}

function getConnectorTypeMeta(connectorType) {
  return availableConnectorTypes.find((item) => item.id === connectorType) || null;
}

function getConnectorAuthSnapshot(connector, explicitOauth = null) {
  const typeMeta = getConnectorTypeMeta(connector.connector_type);
  const oauth = explicitOauth || typeMeta?.oauth || null;
  if (!oauth) return null;

  const config = connector.config || {};
  const provider = config.oauth_provider || oauth.default_provider || '';
  const expiresAt = Number.parseInt(config.oauth_expires_at || 0, 10);
  const remainingSeconds = Number.isFinite(expiresAt) && expiresAt > 0
    ? Math.floor(expiresAt - (Date.now() / 1000))
    : null;
  const tokenField = oauth.token_field || 'oauth_access_token';
  const tokenValue = config[tokenField];
  const connected = Boolean(config.oauth_provider) && Boolean(tokenValue);
  const isExpired = Number.isFinite(remainingSeconds) ? remainingSeconds <= 0 : false;
  const isExpiring = Number.isFinite(remainingSeconds) ? remainingSeconds > 0 && remainingSeconds <= 24 * 3600 : false;
  const scopes = parseOauthScopes(config.oauth_scopes);
  const fallbackScopes = Array.isArray(oauth.scopes_by_provider?.[provider]) ? oauth.scopes_by_provider[provider] : [];
  const effectiveScopes = scopes.length ? scopes : fallbackScopes;

  return {
    provider,
    connected,
    isExpired,
    isExpiring,
    expiresAt,
    remainingSeconds,
    connectedAt: config.oauth_connected_at || '',
    scopes: effectiveScopes,
  };
}

function authStatusText(snapshot) {
  if (!snapshot) return '';
  if (!snapshot.connected) return 'SSO not connected';
  if (snapshot.isExpired) return 'SSO expired';
  if (snapshot.isExpiring) return `SSO expires in ${formatRelativeSeconds(snapshot.remainingSeconds)}`;
  if (Number.isFinite(snapshot.expiresAt) && snapshot.expiresAt > 0) {
    return `SSO healthy (${formatRelativeSeconds(snapshot.remainingSeconds)} left)`;
  }
  return 'SSO connected';
}

function updateConnectorCacheAgeLabel() {
  const label = document.getElementById('connector-cache-age');
  if (!label) return;
  const connectorsAt = getCacheSavedAt(CONNECTORS_CACHE_KEY);
  const typesAt = getCacheSavedAt(CONNECTOR_TYPES_CACHE_KEY);
  if (!connectorsAt && !typesAt) {
    label.textContent = 'Cache: empty';
    return;
  }
  const newest = Math.max(connectorsAt || 0, typesAt || 0);
  label.textContent = `Cache: ${formatAge(Date.now() - newest)}`;
}

function setupCacheControls() {
  updateConnectorCacheAgeLabel();
  if (connectorCacheTimer) {
    clearInterval(connectorCacheTimer);
  }
  connectorCacheTimer = setInterval(updateConnectorCacheAgeLabel, 1000);
  const refreshBtn = document.getElementById('connector-cache-refresh');
  refreshBtn?.addEventListener('click', async () => {
    refreshBtn.disabled = true;
    const prev = refreshBtn.textContent;
    refreshBtn.textContent = 'Refreshing...';
    connectorTypesFetchInFlight = null;
    connectorsFetchInFlight = null;
    clearConnectorCaches(true);
    try {
      await loadConnectorTypes({ force: true });
      await fetchConnectorsAndRender({ force: true });
    } finally {
      refreshBtn.textContent = prev || 'Refresh now';
      refreshBtn.disabled = false;
      updateConnectorCacheAgeLabel();
    }
  });
}

function queueLazyIcons(scope = document) {
  const imgs = scope.querySelectorAll('img[data-src]');
  imgs.forEach((img) => {
    if (iconObserver) {
      iconObserver.observe(img);
    } else {
      enqueueIcon(img);
    }
  });
}

function enqueueIcon(img) {
  if (!img || !img.dataset?.src) return;
  iconQueue.push(img);
  processIconQueue();
}

function processIconQueue() {
  while (iconInFlight < ICON_MAX_INFLIGHT && iconQueue.length) {
    const img = iconQueue.shift();
    if (!img || !img.dataset?.src) continue;
    const src = img.dataset.src;
    img.removeAttribute('data-src');

    iconInFlight += 1;
    const finalize = () => {
      iconInFlight = Math.max(0, iconInFlight - 1);
      processIconQueue();
    };

    img.decoding = 'async';
    try { img.fetchPriority = 'low'; } catch (e) {}

    img.addEventListener('load', finalize, { once: true });
    img.addEventListener('error', finalize, { once: true });

    getIconObjectUrl(src)
      .then((objectUrl) => {
        if (!img.isConnected) return;
        img.src = objectUrl || src;
      })
      .catch(() => {
        if (!img.isConnected) return;
        img.src = src;
      });
  }
}

function updateApprovalsCount(count) {
  const el = document.getElementById('approvals-count');
  if (el) el.textContent = String(count || 0);
}

function connectorNameForApproval(approval) {
  const connectorId = approval?.connector_id;
  if (!Number.isFinite(connectorId)) return '';
  const match = cachedConnectors.find((c) => Number.parseInt(c.id, 10) === connectorId);
  if (match && match.name) return match.name;
  return `connector ${connectorId}`;
}

async function fetchPendingApprovals({ force = false } = {}) {
  const now = Date.now();
  if (!force && approvalsLastFetchAt && (now - approvalsLastFetchAt) < APPROVALS_MIN_FETCH_INTERVAL_MS) {
    return null;
  }
  if (approvalsInFlight) return null;
  approvalsInFlight = true;
  try {
    const resp = await fetch('/api/v1/approvals?status=pending&limit=200', { cache: 'no-store' });
    if (!resp.ok) {
      return { error: `HTTP ${resp.status}` };
    }
    const approvals = await resp.json();
    approvalsLastFetchAt = Date.now();
    return { approvals };
  } catch (err) {
    return { error: err?.message || 'request failed' };
  } finally {
    approvalsInFlight = false;
  }
}

function renderApprovals(approvals) {
  const tbody = document.getElementById('approvals-tbody');
  if (!tbody) return;
  const items = Array.isArray(approvals) ? approvals : [];
  updateApprovalsCount(items.length);

  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-muted">No pending approvals.</td></tr>';
    return;
  }

  tbody.innerHTML = items.map((approval) => {
    const id = approval.id;
    const connectorLabel = escapeHtml(connectorNameForApproval(approval));
    const cls = escapeHtml(approval.command_class || 'change');
    const cmd = escapeHtml(approval.command_text || '');
    const reason = escapeHtml(approval.reason || '');
    const token = escapeHtml(approval.confirm_token || '');
    const destructive = (approval.command_class || '') === 'destructive';
    const tokenCell = destructive
      ? `<div class="approvals-token">Token: <code>${token}</code></div><input class="form-control form-control-sm approvals-confirm" placeholder="Type token" id="approval-confirm-${id}">`
      : '';

    return `
      <tr data-approval-id="${id}">
        <td data-label="ID"><code>#${id}</code></td>
        <td data-label="Connector">${connectorLabel}</td>
        <td data-label="Class"><span class="badge bg-secondary">${cls}</span></td>
        <td data-label="Command"><code class="approvals-command">${cmd}</code>${tokenCell}</td>
        <td data-label="Reason" class="text-muted">${reason}</td>
        <td data-label="Actions" class="approvals-actions">
          <button type="button" class="btn btn-sm btn-outline-success" data-approval-approve="${id}">Approve</button>
          <button type="button" class="btn btn-sm btn-outline-danger" data-approval-reject="${id}">Reject</button>
        </td>
      </tr>
    `;
  }).join('');

  tbody.querySelectorAll('[data-approval-approve]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = Number.parseInt(btn.getAttribute('data-approval-approve') || '0', 10);
      if (!id) return;
      btn.disabled = true;
      try {
        const tokenInput = document.getElementById(`approval-confirm-${id}`);
        const confirmToken = tokenInput ? String(tokenInput.value || '').trim() : '';
        const resp = await fetch(`/api/v1/approvals/${id}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm_token: confirmToken, reason: 'approved from UI' })
        });
        const statusEl = document.getElementById('approvals-status');
        if (!resp.ok) {
          const detail = await resp.text();
          if (statusEl) statusEl.textContent = `Approve failed for #${id}: ${detail}`;
          return;
        }
        if (statusEl) statusEl.textContent = `Approved #${id}.`;
        await loadApprovals({ force: true });
      } finally {
        btn.disabled = false;
      }
    });
  });

  tbody.querySelectorAll('[data-approval-reject]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = Number.parseInt(btn.getAttribute('data-approval-reject') || '0', 10);
      if (!id) return;
      btn.disabled = true;
      try {
        const resp = await fetch(`/api/v1/approvals/${id}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: 'rejected from UI' })
        });
        const statusEl = document.getElementById('approvals-status');
        if (!resp.ok) {
          const detail = await resp.text();
          if (statusEl) statusEl.textContent = `Reject failed for #${id}: ${detail}`;
          return;
        }
        if (statusEl) statusEl.textContent = `Rejected #${id}.`;
        await loadApprovals({ force: true });
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function loadApprovals({ force = false } = {}) {
  const statusEl = document.getElementById('approvals-status');
  const result = await fetchPendingApprovals({ force });
  if (!result) return;
  if (result.error) {
    if (statusEl) statusEl.textContent = `Approvals: ${result.error}`;
    return;
  }
  const approvals = result.approvals || [];
  renderApprovals(approvals);
  if (statusEl) statusEl.textContent = `Loaded ${approvals.length} pending.`;
}

async function refreshApprovalsCount() {
  const result = await fetchPendingApprovals({ force: true });
  if (!result || result.error) return;
  const approvals = result.approvals || [];
  updateApprovalsCount(Array.isArray(approvals) ? approvals.length : 0);
}

function startApprovalsPolling() {
  if (approvalsPollTimer) return;
  approvalsPollTimer = setInterval(() => {
    if (document.hidden) return;
    if (!isPanelExpanded('approvals-panel')) return;
    loadApprovals();
  }, APPROVALS_POLL_INTERVAL_MS);
}

function stopApprovalsPolling() {
  if (!approvalsPollTimer) return;
  clearInterval(approvalsPollTimer);
  approvalsPollTimer = null;
}

function isPanelExpanded(id) {
  const panel = document.getElementById(id);
  return !!panel && panel.classList.contains('show');
}

function setupPanelPolling() {
  const statusPanel = document.getElementById('connector-status-panel');
  if (statusPanel) {
    statusPanel.addEventListener('shown.bs.collapse', () => {
      fetchStatuses();
      startStatusPolling();
    });
    const refreshBtn = document.getElementById('connector-status-refresh');
    refreshBtn?.addEventListener('click', async (evt) => {
      evt.preventDefault();
      refreshBtn.disabled = true;
      try {
        await fetchStatuses({ refresh: true });
      } finally {
        refreshBtn.disabled = false;
      }
    });
    statusPanel.addEventListener('hidden.bs.collapse', () => {
      stopStatusPolling();
    });
  }

  const routingRulesPanel = document.getElementById('routing-rules-panel');
  if (routingRulesPanel) {
    routingRulesPanel.addEventListener('shown.bs.collapse', async () => {
      if (!routingLoaded) {
        routingLoaded = true;
        await loadRoutingUI();
      } else {
        await loadRoutingRules();
      }
    });
  }

  const routingPanel = document.getElementById('routing-events-panel');
  if (routingPanel) {
    routingPanel.addEventListener('shown.bs.collapse', () => {
      if (!routingLoaded) {
        routingLoaded = true;
        loadRoutingUI().then(() => {
          loadRoutingOpsPanels();
          startRoutingPolling();
        });
      } else {
        loadRoutingOpsPanels();
        startRoutingPolling();
      }
    });
    routingPanel.addEventListener('hidden.bs.collapse', () => {
      if (isPanelExpanded('routing-jobs-panel')) {
        startRoutingPolling();
      } else {
        stopRoutingPolling();
      }
    });
  }

  const routingJobsPanel = document.getElementById('routing-jobs-panel');
  if (routingJobsPanel) {
    routingJobsPanel.addEventListener('shown.bs.collapse', () => {
      if (!routingLoaded) {
        routingLoaded = true;
        loadRoutingUI().then(() => {
          loadRoutingOpsPanels();
          startRoutingPolling();
        });
      } else {
        loadRoutingOpsPanels();
        startRoutingPolling();
      }
    });
    routingJobsPanel.addEventListener('hidden.bs.collapse', () => {
      if (isPanelExpanded('routing-events-panel')) {
        startRoutingPolling();
      } else {
        stopRoutingPolling();
      }
    });
    const refreshBtn = document.getElementById('routing-jobs-refresh');
    refreshBtn?.addEventListener('click', async () => {
      refreshBtn.disabled = true;
      try {
        await loadRoutingOpsPanels();
      } finally {
        refreshBtn.disabled = false;
      }
    });
  }

  const approvalsPanel = document.getElementById('approvals-panel');
  if (approvalsPanel) {
    approvalsPanel.addEventListener('shown.bs.collapse', () => {
      loadApprovals();
      startApprovalsPolling();
    });
    approvalsPanel.addEventListener('hidden.bs.collapse', () => {
      stopApprovalsPolling();
    });
    const refreshBtn = document.getElementById('approvals-refresh');
    refreshBtn?.addEventListener('click', async () => {
      refreshBtn.disabled = true;
      try {
        await loadApprovals({ force: true });
      } finally {
        refreshBtn.disabled = false;
      }
    });
  }

  const simulatorPanel = document.getElementById('routing-simulator-panel');
  if (simulatorPanel) {
    simulatorPanel.addEventListener('shown.bs.collapse', () => {
      renderRoutingSimulatorConnectorOptions();
    });
  }
}

function computeMissingFields(connector) {
  const fields = connectorFieldMap[connector.connector_type] || [];
  if (!fields.length) return [];
  return getMissingRequiredFields(connector.connector_type, connector.config || {}, fields);
}

async function fetchConnectorsAndRender(options = {}) {
  const connectors = await getConnectors(options);
  cachedConnectors = connectors;
  installedConnectorTypes = new Set(connectors.map(connector => connector.connector_type));
  connectorStatusByType = new Map();
  connectorBrokenTypes = new Set();
  renderRoutingConnectorOptions();
  const readyContainer = document.getElementById('connectors-ready');
  const missingContainer = document.getElementById('connectors-missing');
  const downContainer = document.getElementById('connectors-down');
  if (readyContainer) readyContainer.innerHTML = '';
  if (missingContainer) missingContainer.innerHTML = '';
  if (downContainer) downContainer.innerHTML = '';

  let readyCount = 0;
  let missingCount = 0;

  for (const connector of connectors) {
    const missingFields = computeMissingFields(connector);
    const status = missingFields.length ? 'missing_config' : 'unknown';
    connector._status = status;
    connectorStatusByType.set(connector.connector_type, status);
    if (status === 'missing_config') {
      connectorBrokenTypes.add(connector.connector_type);
    }
    const el = createConnectorElement(connector);
    const badge = el.querySelector('.connector-status');
    if (badge) badge.textContent = status;
    if (status === 'missing_config') {
      missingCount += 1;
      missingContainer?.appendChild(el);
    } else {
      readyCount += 1;
      readyContainer?.appendChild(el);
    }
  }
  const readyCountEl = document.getElementById('connectors-ready-count');
  const missingCountEl = document.getElementById('connectors-missing-count');
  if (readyCountEl) readyCountEl.textContent = `${readyCount} ready`;
  if (missingCountEl) missingCountEl.textContent = `${missingCount} needs setup`;

  if (readyContainer) queueLazyIcons(readyContainer);
  if (missingContainer) queueLazyIcons(missingContainer);
  if (downContainer) queueLazyIcons(downContainer);
  renderStatusTable(connectors);
  renderRoutingSimulatorConnectorOptions();
  renderConnectorCatalog(document.getElementById('connector-catalog-search')?.value?.trim() || '');
}

async function loadConnectorTypes(options = {}) {
  const force = options.force === true;
  const select = document.getElementById('connector-type');
  if (!select) return;
  const cached = force
    ? null
    : (readCachedJson(CONNECTOR_TYPES_CACHE_KEY, CONNECTOR_TYPES_CACHE_TTL_MS) || []);
  const now = Date.now();
  if (!force && availableConnectorTypes.length && (now - connectorTypesLastFetchAt) < CONNECTOR_TYPES_MIN_FETCH_INTERVAL_MS) {
    renderConnectorTypeSelect(availableConnectorTypes, select);
    return;
  }
  let available = cached || [];
  if (!connectorTypesFetchInFlight) {
    connectorTypesFetchInFlight = (async () => {
      if (!force && Date.now() < connectorTypesBackoffUntil && available.length) {
        return available;
      }
      try {
        const url = force
          ? `/api/v1/connectors/available?ts=${Date.now()}`
          : '/api/v1/connectors/available';
        const resp = await fetch(url, { cache: force ? 'no-store' : 'default' });
        if (resp.status === 429) {
          connectorTypesBackoffUntil = Date.now() + CONNECTORS_BACKOFF_MS;
          return available;
        }
        if (resp.ok) {
          const fresh = await resp.json();
          writeCachedJson(CONNECTOR_TYPES_CACHE_KEY, fresh);
          connectorTypesBackoffUntil = 0;
          connectorTypesLastFetchAt = Date.now();
          return fresh;
        }
        return available;
      } catch (err) {
        connectorTypesBackoffUntil = Date.now() + CONNECTORS_BACKOFF_MS;
        return available;
      } finally {
        connectorTypesFetchInFlight = null;
      }
    })();
  }
  available = await connectorTypesFetchInFlight;

  availableConnectorTypes = available.length ? available : connectorCatalog.map(item => ({
    id: item.id,
    name: item.name,
    fields: item.fields || [],
    defaults: {},
    capabilities: {},
    oauth: null,
  }));
  backendAvailableIds = new Set(availableConnectorTypes.map(item => item.id));

  const catalogById = new Map(connectorCatalog.map(item => [item.id, item]));
  connectorFieldMap = {};
  connectorDefaultsMap = {};
  connectorCatalog.forEach((item) => {
    connectorFieldMap[item.id] = item.fields || [];
  });
  availableConnectorTypes.forEach((item) => {
    connectorFieldMap[item.id] = item.fields && item.fields.length
      ? item.fields
      : (connectorFieldMap[item.id] || []);
    connectorDefaultsMap[item.id] = item.defaults && typeof item.defaults === "object"
      ? item.defaults
      : {};
  });

  renderConnectorTypeSelect(availableConnectorTypes, select);

  if (!select.dataset.templateBound) {
    select.addEventListener('change', () => {
      const selected = select.options[select.selectedIndex];
      const connectorType = selected?.value || '';
      const fields = JSON.parse(selected?.dataset.fields || '[]');
      if (!fields.length) return;
      const template = buildConnectorConfigTemplate(connectorType, fields);
      const configInput = document.getElementById('connector-config');
      if (!configInput) return;

      const raw = configInput.value.trim();
      let existing = {};
      if (raw) {
        try {
          const parsed = JSON.parse(raw);
          existing = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
            ? parsed
            : {};
        } catch (err) {
          // Leave user-provided invalid JSON untouched.
          return;
        }
      }

      const merged = {
        ...template,
        ...existing,
      };
      configInput.value = JSON.stringify(merged, null, 2);
    });
    select.dataset.templateBound = '1';
  }

  resetCatalogRenderLimit();
  renderConnectorCatalog();
  const search = document.getElementById('connector-catalog-search');
  if (search && !search.dataset.bound) {
    const rerender = debounce(() => {
      resetCatalogRenderLimit();
      renderConnectorCatalog(search.value.trim());
    }, 180);
    search.addEventListener('input', rerender);
    search.dataset.bound = '1';
  }
}

function resetCatalogRenderLimit() {
  const step = isNarrowViewport() ? MOBILE_CATALOG_RENDER_STEP : CATALOG_RENDER_STEP;
  catalogRenderLimit = step;
}

function updateCatalogFooter({ shown = 0, total = 0, canShowMore = false } = {}) {
  const footer = document.getElementById('connector-catalog-footer');
  if (!footer) return;
  if (!total) {
    footer.innerHTML = '';
    footer.classList.add('d-none');
    return;
  }
  footer.classList.remove('d-none');
  const remaining = Math.max(0, total - shown);
  footer.innerHTML = `
    <div class="connector-catalog-footer__meta">Showing <strong>${shown}</strong> of <strong>${total}</strong>${remaining ? ` ( ${remaining} more )` : ''}</div>
    <div class="connector-catalog-footer__actions">
      ${canShowMore ? '<button type="button" class="btn btn-sm btn-outline-secondary" id="connector-catalog-show-more">Show more</button>' : ''}
    </div>
  `;
  const moreBtn = footer.querySelector('#connector-catalog-show-more');
  if (moreBtn) {
    moreBtn.addEventListener('click', () => {
      const step = isNarrowViewport() ? MOBILE_CATALOG_RENDER_STEP : CATALOG_RENDER_STEP;
      catalogRenderLimit = Math.min(total, catalogRenderLimit + step);
      renderConnectorCatalog(document.getElementById('connector-catalog-search')?.value?.trim() || '');
    }, { once: true });
  }
}

function renderConnectorCatalog(query = '') {
  const container = document.getElementById('connector-catalog');
  if (!container) return;
  container.dataset.view = catalogView;
  const availableIds = backendAvailableIds;
  const catalogById = new Map(connectorCatalog.map(item => [item.id, item]));
  const normalized = query.toLowerCase();
  container.innerHTML = '';
  const allItems = availableConnectorTypes.map((item) => {
    const override = catalogById.get(item.id);
    const name = override?.name || item.name || titleFromId(item.id);
    const category = override?.category || 'Other';
    const desc = override?.desc || 'Connector integration available.';
    return {
      id: item.id,
      name,
      category,
      desc,
      fields: connectorFieldMap[item.id] || item.fields || [],
      capabilities: item.capabilities || {},
      oauth: item.oauth || null,
    };
  }).filter(item =>
    !normalized ||
    item.name.toLowerCase().includes(normalized) ||
    item.category.toLowerCase().includes(normalized)
  ).filter(item => {
    if (catalogFilter === 'installed') {
      return installedConnectorTypes.has(item.id);
    }
    if (catalogFilter === 'broken') {
      return connectorBrokenTypes.has(item.id);
    }
    if (catalogFilter === 'online') {
      const status = connectorStatusByType.get(item.id);
      return status === 'ok' || status === 'healthy' || status === 'active';
    }
    return true;
  }).sort((a, b) => {
    const aRank = popularityOrder.indexOf(a.id);
    const bRank = popularityOrder.indexOf(b.id);
    if (aRank !== -1 || bRank !== -1) {
      return (aRank === -1 ? 999 : aRank) - (bRank === -1 ? 999 : bRank);
    }
    return a.name.localeCompare(b.name);
  });

  const totalCount = allItems.length;
  const visibleItems = allItems.slice(0, Math.max(1, catalogRenderLimit));



  const renderCard = (item) => {
    const supported = availableIds.has(item.id);
    const webhookOnly = webhookOnlyIds.has(item.id);
    const installed = installedConnectorTypes.has(item.id);
    const status = connectorStatusByType.get(item.id) || 'unknown';
    const isBroken = connectorBrokenTypes.has(item.id);
    const card = document.createElement('div');
    card.className = `connector-tile ${supported ? 'supported' : 'disabled'}`;
    const fieldsText = item.fields?.length ? `Fields: ${item.fields.join(', ')}` : 'No required fields.';
    const statusText = isBroken ? 'Broken' : (installed ? 'Installed' : (status === 'ok' || status === 'healthy' || status === 'active' ? 'Online' : 'Not configured'));
    const capabilityText = webhookOnly ? 'Inbound: webhook-only' : 'Inbound: native';
    const outboundText = supported ? 'Outbound: supported' : 'Outbound: coming soon';
    const caps = item.capabilities || {};
    const capRow = [
      caps.supports_inbound ? 'inbound' : null,
      caps.supports_outbound ? 'outbound' : null,
      caps.supports_webhook_setup ? 'webhook-setup' : null,
      item.oauth ? 'sso' : null,
    ].filter(Boolean).join(', ') || 'basic';
    const capIcons = [
      renderCapabilityIcon('inbound', {
        title: webhookOnly ? 'Inbound (webhook-only)' : 'Inbound',
        on: Boolean(caps.supports_inbound),
      }),
      renderCapabilityIcon('outbound', { title: 'Outbound', on: Boolean(caps.supports_outbound) }),
      caps.supports_webhook_setup
        ? renderCapabilityIcon('webhook', { title: 'Webhook setup', on: true })
        : '',
      item.oauth ? renderCapabilityIcon('sso', { title: 'SSO (OAuth)', on: true }) : '',
    ].filter(Boolean).join('');
    card.setAttribute('data-bs-toggle', 'tooltip');
    card.setAttribute('data-bs-title', `${item.name} • ${item.category}\n${item.desc}\n${capabilityText} • ${outboundText}\nCapabilities: ${capRow}\n${fieldsText}\nStatus: ${statusText}`);
    const icon = item.icon || item.name.split(' ').map(word => word[0]).join('').slice(0, 2).toUpperCase();
    const iconSrc = `/static/icons/connectors/${item.id}.svg`;
    card.innerHTML = `
      <div class="connector-tile__header">
        <div class="connector-tile__left">
          <div class="connector-tile__icon">
            <img src="${ICON_PLACEHOLDER_SRC}" data-src="${iconSrc}" alt="" loading="lazy" onerror="this.style.display='none'; this.parentElement.classList.add('is-fallback');" />
            <span class="connector-tile__fallback">${icon}</span>
          </div>
          <div class="connector-tile__main">
            <div class="connector-tile__name">${item.name}</div>
            <div class="connector-tile__meta-row">
              <span class="connector-tile__indicators">
                ${installed ? '<span class="connector-dot installed" title="Installed"></span>' : ''}
                ${isBroken ? '<span class="connector-dot broken" title="Broken"></span>' : ''}
                ${!installed && !isBroken && (status === 'ok' || status === 'healthy' || status === 'active')
                  ? '<span class="connector-dot online" title="Online"></span>'
                  : ''}
                <span class="connector-dot ${supported ? 'available' : 'coming'}" title="${supported ? 'Available' : 'Coming soon'}"></span>
              </span>
            </div>
          </div>
        </div>
        <div class="connector-tile__cta">
          <button class="btn btn-sm ${supported ? 'btn-primary' : 'btn-outline-secondary'}" type="button" ${supported ? '' : 'disabled'}>Add</button>
        </div>
      </div>
      <div class="connector-tile__desc">${webhookOnly ? `${item.desc} (webhook-only)` : item.desc}</div>
      <div class="connector-tile__meta-row connector-tile__caps" aria-label="Capabilities">${capIcons}</div>
      <div class="connector-tile__meta-row"><small class="connector-tile__hint">${getPreferredConnectorMode(item.id) ? `Recommended mode: ${getPreferredConnectorMode(item.id)}` : ''}</small></div>
    `;
    card.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const now = Date.now();
      if (now - lastModalDismissAt < 180) {
        return;
      }

      // Ensure any tooltip on this tile doesn't linger when the modal opens.
      if (window.bootstrap?.Tooltip) {
        const tip = window.bootstrap.Tooltip.getInstance(card);
        tip?.hide();
      }

      if (activeCatalogItemId === item.id) {
        connectorModal?.hide();
        return;
      }

      activeCatalogItemId = item.id;

      const installedConnector = cachedConnectors.find(conn => conn.connector_type === item.id) || null;
      openConnectorModal({
        item,
        installedConnector,
        mode: installedConnector ? 'edit' : 'add',
        supported
      });
    });
    return card;
  };

  if (catalogGroup === 'category' || catalogGroup === 'status') {
    const groupMap = new Map();
    visibleItems.forEach((item) => {
      const supported = availableIds.has(item.id);
      const key = catalogGroup === 'category' ? item.category : (supported ? 'Available' : 'Coming soon');
      if (!groupMap.has(key)) groupMap.set(key, []);
      groupMap.get(key).push(item);
    });
    Array.from(groupMap.entries()).sort((a, b) => a[0].localeCompare(b[0])).forEach(([group, items]) => {
      const groupWrap = document.createElement('div');
      groupWrap.className = 'connector-group';
      groupWrap.innerHTML = `
        <div class="connector-group__header">
          <div class="connector-group__title">${group}</div>
          <div class="connector-group__count">${items.length} connectors</div>
        </div>
        <div class="connector-group__grid"></div>
      `;
      const grid = groupWrap.querySelector('.connector-group__grid');
      items.forEach(item => grid.appendChild(renderCard(item)));
      container.appendChild(groupWrap);
    });
  } else {
    visibleItems.forEach(item => container.appendChild(renderCard(item)));
  }
  updateCatalogFooter({ shown: visibleItems.length, total: totalCount, canShowMore: visibleItems.length < totalCount });
  queueLazyIcons(container);
  initCatalogTooltips();
}

function titleFromId(id) {
  return id
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

async function fetchBots() {
  const resp = await fetch('/api/bots');
  return await resp.json();
}

function togglePanelByData(panelId, hasData) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  if (hasData) {
    panel.classList.add('show');
  } else {
    panel.classList.remove('show');
  }
}

function renderRoutingConnectorOptions() {
  const select = document.getElementById('routing-rule-connector');
  if (!select) return;
  select.innerHTML = '';
  const anyOption = document.createElement('option');
  anyOption.value = '';
  anyOption.textContent = 'Any connector';
  select.appendChild(anyOption);
  cachedConnectors.forEach((connector) => {
    const opt = document.createElement('option');
    opt.value = connector.id;
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    opt.dataset.connectorType = connector.connector_type;
    select.appendChild(opt);
  });
  if (Number.isFinite(routingRulesConnectorFilterId)) {
    select.value = String(routingRulesConnectorFilterId);
  }
}

function renderRoutingSimulatorConnectorOptions() {
  const select = document.getElementById('routing-simulator-connector');
  if (!select) return;
  const previous = select.value;
  select.innerHTML = '<option value="">Any connector</option>';
  cachedConnectors.forEach((connector) => {
    const opt = document.createElement('option');
    opt.value = String(connector.id);
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    select.appendChild(opt);
  });
  if (previous) {
    select.value = previous;
  }
}

function renderRoutingDestinationOptions() {
  const select = document.getElementById('routing-rule-destination');
  if (!select) return;
  const previous = select.value;
  select.innerHTML = '';

  const same = document.createElement('option');
  same.value = '';
  same.textContent = 'Same as source';
  select.appendChild(same);

  cachedConnectors.forEach((connector) => {
    const opt = document.createElement('option');
    opt.value = String(connector.id);
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    select.appendChild(opt);
  });

  if (previous) {
    select.value = previous;
  }
}

function renderRoutingBotOptions() {
  const select = document.getElementById('routing-rule-bot');
  if (!select) return;
  select.innerHTML = '';
  cachedBots.forEach((bot) => {
    const opt = document.createElement('option');
    opt.value = bot.id;
    opt.textContent = bot.name;
    select.appendChild(opt);
  });
}

async function loadRoutingUI() {
  const form = document.getElementById('routing-rule-form');
  if (!form) return;
  cachedBots = await fetchBots();
  renderRoutingBotOptions();
  renderRoutingConnectorOptions();
  renderRoutingDestinationOptions();
  await loadRoutingRules();

  const applyFilterBtn = document.getElementById("routing-rules-apply-form-filter");
  const clearFilterInlineBtn = document.getElementById("routing-rules-clear-filter-inline");
  applyFilterBtn?.addEventListener("click", async () => {
    const connectorSelect = document.getElementById("routing-rule-connector");
    const selected = Number.parseInt(connectorSelect?.value || "", 10);
    routingRulesConnectorFilterId = Number.isFinite(selected) ? selected : null;
    writeRoutingRulesFilterId(routingRulesConnectorFilterId);
    await loadRoutingRules();
  });
  clearFilterInlineBtn?.addEventListener("click", async () => {
    routingRulesConnectorFilterId = null;
    writeRoutingRulesFilterId(null);
    const connectorSelect = document.getElementById("routing-rule-connector");
    if (connectorSelect) connectorSelect.value = "";
    await loadRoutingRules();
  });
  if (isPanelExpanded('routing-events-panel') || isPanelExpanded('routing-jobs-panel')) {
    await loadRoutingOpsPanels();
    startRoutingPolling();
  }

  form.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const name = document.getElementById('routing-rule-name').value.trim();
    const connectorValue = document.getElementById('routing-rule-connector').value;
    const botValue = document.getElementById('routing-rule-bot').value;
    const matchType = document.getElementById('routing-rule-type').value;
    const matchValue = document.getElementById('routing-rule-value').value.trim();
    const priority = Number.parseInt(
      document.getElementById('routing-rule-priority').value,
      10
    );
    const isActive = document.getElementById('routing-rule-active').checked;

    if (!name || !botValue) return;

    const payload = {
      name,
      bot_id: Number.parseInt(botValue, 10),
      match_type: matchType,
      match_value: matchValue || null,
      priority: Number.isNaN(priority) ? 0 : priority,
      is_active: isActive
    };

    if (connectorValue) {
      const connector = cachedConnectors.find(c => c.id === Number.parseInt(connectorValue, 10));
      payload.connector_id = Number.parseInt(connectorValue, 10);
      payload.connector_type = connector ? connector.connector_type : null;
    }

    const destinationValue = document.getElementById('routing-rule-destination')?.value || '';
    if (destinationValue) {
      payload.destination_connector_id = Number.parseInt(destinationValue, 10);
    }

    await createRoutingRule(payload);
    form.reset();
    document.getElementById('routing-rule-active').checked = true;
    await loadRoutingRules();
    await loadRoutingEvents();
  });
}


function setupStarterPack() {
  const panel = document.getElementById('starter-pack-panel');
  const installBtn = document.getElementById('starter-pack-install');
  const statusEl = document.getElementById('starter-pack-status');
  const logEl = document.getElementById('starter-pack-log');
  const selectAll = document.getElementById('starter-pack-select-all');
  const selectNone = document.getElementById('starter-pack-select-none');
  if (!panel || !installBtn || !statusEl || !logEl) return;

  const checkboxes = Array.from(panel.querySelectorAll('input[data-starter-pack]'));
  const setAll = (value) => {
    checkboxes.forEach((cb) => {
      cb.checked = value;
    });
  };
  selectAll?.addEventListener('click', () => setAll(true));
  selectNone?.addEventListener('click', () => setAll(false));

  const appendLog = (line) => {
    logEl.textContent = (logEl.textContent ? `${logEl.textContent}
` : '') + line;
    logEl.scrollTop = logEl.scrollHeight;
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  installBtn.addEventListener('click', async () => {
    const wanted = checkboxes
      .filter((cb) => cb.checked)
      .map((cb) => cb.getAttribute('data-starter-pack') || '')
      .filter(Boolean);

    if (!wanted.length) {
      statusEl.textContent = 'Select at least one connector.';
      return;
    }

    installBtn.disabled = true;
    logEl.textContent = '';
    statusEl.textContent = 'Installing...';

    // Refresh local view of connectors to skip duplicates by type.
    let existing = [];
    try {
      existing = await getConnectors();
    } catch (err) {
      existing = cachedConnectors || [];
    }
    const existingTypes = new Set((existing || []).map((c) => c.connector_type));

    let created = 0;
    let skipped = 0;
    let failed = 0;

    for (const key of wanted) {
      const preset = STARTER_PACK_PRESETS[key];
      if (!preset) {
        appendLog(`skip ${key}: unknown preset`);
        skipped += 1;
        continue;
      }
      if (existingTypes.has(preset.connector_type)) {
        appendLog(`skip ${preset.connector_type}: already installed`);
        skipped += 1;
        continue;
      }
      try {
        const payload = {
          name: preset.name,
          connector_type: preset.connector_type,
          config: {
            ...(CONNECTOR_CONFIG_DEFAULTS[preset.connector_type] || {}),
            ...(preset.config || {}),
          },
        };
        const createdConnector = await createConnector(payload);
        existingTypes.add(createdConnector.connector_type);
        appendLog(`ok ${createdConnector.connector_type}: created id ${createdConnector.id}`);
        created += 1;
      } catch (err) {
        appendLog(`fail ${preset.connector_type}: ${err?.message || err}`);
        failed += 1;
      }
      // Keep installs gentle on the API.
      await sleep(350);
    }

    try {
      await loadConnectorTypes({ force: true });
      await fetchConnectorsAndRender({ force: true });
    } catch (err) {
      // ignore
    }

    statusEl.textContent = `Done. Created ${created}, skipped ${skipped}, failed ${failed}.`;
    installBtn.disabled = false;
  });
}

function setupPassiveSensorsQuickstart() {
  const panel = document.getElementById('passive-sensors-panel');
  if (!panel) return;

  const webhookInput = document.getElementById('passive-sensor-webhook-url');
  const payloadInput = document.getElementById('passive-sensor-payload');
  const lastCreated = document.getElementById('passive-sensors-last-created');
  const createButtons = panel.querySelectorAll('[data-passive-create]');
  const copyButtons = panel.querySelectorAll('[data-passive-copy-target]');

  const setPreview = (sensorType, connectorId = null) => {
    const preset = PASSIVE_SENSOR_PRESETS[sensorType];
    if (!preset) return;
    const id = connectorId ? String(connectorId) : '{connector_id}';
    if (webhookInput) {
      webhookInput.value = `${window.location.origin}/api/v1/connectors/webhooks/${sensorType}/${id}`;
    }
    if (payloadInput) {
      payloadInput.value = JSON.stringify(preset.payload, null, 2);
    }
  };

  const buildName = (base) => {
    const stamp = new Date().toISOString().slice(11, 19).replace(/:/g, '-');
    return `${base} ${stamp}`;
  };

  createButtons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      const sensorType = btn.getAttribute('data-passive-create') || '';
      const preset = PASSIVE_SENSOR_PRESETS[sensorType];
      if (!preset) return;
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Creating...';
      try {
        const created = await createConnector({
          name: buildName(preset.name),
          connector_type: preset.connector_type,
          config: preset.config,
        });
        await fetchConnectorsAndRender();
        setPreview(sensorType, created?.id || null);
        if (lastCreated) {
          lastCreated.textContent = `Created ${created.name} (id ${created.id}). Route with match type Passive Sensor and value ${sensorType}.`;
        }
      } catch (err) {
        if (lastCreated) {
          lastCreated.textContent = `Failed to create ${sensorType} sensor: ${err?.message || err}`;
        }
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  });

  copyButtons.forEach((btn) => {
    btn.addEventListener('click', async () => {
      const targetId = btn.getAttribute('data-passive-copy-target');
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target) return;
      const value = 'value' in target ? target.value : target.textContent || '';
      if (!value) return;
      await navigator.clipboard.writeText(value);
    });
  });

  setPreview('snmp');
}

function setupRoutingSimulator() {
  const form = document.getElementById('routing-simulator-form');
  if (!form) return;

  const presetButtons = document.querySelectorAll("[data-sim-preset]");
  presetButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = btn.getAttribute("data-sim-preset");
      const input = document.getElementById("routing-simulator-message");
      if (!input) return;
      const presetMap = {
        proxy_to_signal: "proxy route this to signal group",
        support_ticket: "customer issue: login broken, open support ticket",
        incident_alert: "sev2 incident alert: api latency spike",
        passive_snmp: "snmp trap: link down on edge-switch-2",
        passive_glimpser: "glimpser camera front_door motion.detected confidence 93%",
        passive_hubitat: "hubitat kitchen motion active"
      };
      input.value = presetMap[preset] || "";
      input.focus();
    });
  });
  form.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const connectorSelect = document.getElementById('routing-simulator-connector');
    const messageInput = document.getElementById('routing-simulator-message');
    const result = document.getElementById('routing-simulator-result');
    if (!messageInput || !result) return;
    const messageText = messageInput.value.trim();
    if (!messageText) {
      result.textContent = 'Enter a sample message first.';
      return;
    }

    const payload = {
      message_text: messageText
    };
    const connectorId = connectorSelect?.value ? Number.parseInt(connectorSelect.value, 10) : null;
    if (connectorId) {
      payload.connector_id = connectorId;
    }

    result.textContent = 'Running simulation...';
    try {
      const resp = await fetch('/api/v1/routing/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        result.textContent = `Simulation failed: ${err.detail || resp.status}`;
        return;
      }
      const data = await resp.json();
      const lines = [];
      if (data.decision === 'matched_rule') {
        const destId = Number.parseInt(data.selected_destination_connector_id || 0, 10);
        const dest = Number.isFinite(destId) && destId > 0
          ? (cachedConnectors.find((c) => c.id == destId)?.name || `connector ${destId}`)
          : null;
        lines.push(`Decision: matched rule ${data.selected_rule_id} -> bot ${data.selected_bot_name || data.selected_bot_id}${dest ? ` -> deliver to ${dest}` : ''}`);
      } else if (data.decision === 'fallback_bot') {
        lines.push(`Decision: no rule match, fallback bot ${data.selected_bot_name || data.selected_bot_id}`);
      } else {
        lines.push('Decision: no bot available.');
      }
      if (Array.isArray(data.matches) && data.matches.length) {
        lines.push(`Matches (${data.matches.length}):`);
        data.matches.forEach((match) => {
          lines.push(`- [P${match.priority}] ${match.rule_name} (${match.match_type}${match.match_value ? `: ${match.match_value}` : ''}) -> ${match.bot_name || match.bot_id}`);
        });
      }
      result.textContent = lines.join('\n');
    } catch (err) {
      result.textContent = `Simulation error: ${err.message || err}`;
    }
  });
}

async function fetchRoutingRules() {
  const resp = await fetch('/api/v1/routing/rules');
  return await resp.json();
}

async function createRoutingRule(data) {
  const resp = await fetch('/api/v1/routing/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return await resp.json();
}

async function deleteRoutingRule(id) {
  await fetch(`/api/v1/routing/rules/${id}`, { method: 'DELETE' });
}

async function fetchRoutingEvents() {
  const resp = await fetch('/api/v1/routing/events?limit=50');
  return await resp.json();
}

async function fetchConnectorStatusHistory(connectorId, options = {}) {
  const params = new URLSearchParams();
  params.set('connector_id', String(connectorId));
  params.set('limit', String(options.limit || 20));
  params.set('error_limit', String(options.errorLimit || 5));
  const resp = await fetch(`/api/v1/connectors/statuses/history?${params.toString()}`, {
    cache: 'no-store'
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `Unable to load history for connector ${connectorId}.`);
  }
  return await resp.json();
}

async function fetchRoutingTrace(eventId) {
  const resp = await fetch(`/api/v1/routing/events/${eventId}/trace`, {
    cache: 'no-store'
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `Unable to load trace for event ${eventId}.`);
  }
  return await resp.json();
}

async function fetchRoutingJobs(options = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(options.limit || 50));
  if (options.includeDone === true) {
    params.set('include_done', 'true');
  }
  if (options.status) {
    params.set('status', options.status);
  }
  const resp = await fetch(`/api/v1/routing/jobs?${params.toString()}`, {
    cache: 'no-store'
  });
  if (!resp.ok) {
    throw new Error(`Failed to fetch routing jobs (${resp.status})`);
  }
  return await resp.json();
}

async function fetchConnectorBundleExport() {
  const resp = await fetch('/api/v1/connectors/export', {
    cache: 'no-store'
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to export connector bundle.');
  }
  return await resp.json();
}

async function importConnectorBundle(bundle) {
  const resp = await fetch('/api/v1/connectors/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bundle)
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to import connector bundle.');
  }
  return await resp.json();
}

async function retryRoutingJob(id) {
  const resp = await fetch(`/api/v1/routing/jobs/${id}/retry`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `Unable to retry routing job ${id}.`);
  }
  return await resp.json();
}

function formatRoutingTimestamp(value) {
  if (!value) return '';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function formatHealthTimestamp(epochSeconds) {
  const value = Number(epochSeconds);
  if (!Number.isFinite(value) || value <= 0) return '';
  return new Date(value * 1000).toLocaleString();
}

function formatRoutingRelativeAge(value) {
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  const deltaSeconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000));
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`;
  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) return `${deltaMinutes}m ago`;
  const deltaHours = Math.floor(deltaMinutes / 60);
  return `${deltaHours}h ago`;
}

function buildConnectorBundleFilename(bundle) {
  const rawStamp = bundle?.exported_at ? new Date(bundle.exported_at) : new Date();
  const stamp = Number.isNaN(rawStamp.getTime())
    ? new Date().toISOString()
    : rawStamp.toISOString();
  return `norman-connectors-routing-${stamp.replace(/[:.]/g, '-')}.json`;
}

function downloadJsonFile(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json'
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 1000);
}

function routingFlowLabel(job) {
  const srcLabel = job.event_connector_type || job.event_connector_id || '';
  const destLabel = job.destination_connector_type
    || (job.destination_connector_id ? `connector ${job.destination_connector_id}` : '');
  return destLabel ? `${srcLabel} -> ${destLabel}` : (srcLabel || '--');
}

function routingJobError(job) {
  const detail = job.event_delivery_error || job.last_error || '';
  const text = String(detail || '').trim();
  if (!text) return 'No error recorded.';
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

function renderConnectorStatusHistoryDetails(payload) {
  const historyItems = Array.isArray(payload.history) ? payload.history : [];
  const recentErrors = Array.isArray(payload.recent_errors) ? payload.recent_errors : [];
  const historyMarkup = historyItems.length
    ? historyItems.map((entry) => `
      <tr>
        <td>${escapeHtml(formatHealthTimestamp(entry.checked_at))}</td>
        <td>${escapeHtml(entry.status || 'unknown')}</td>
        <td>${escapeHtml(String(entry.failures ?? ''))}</td>
        <td>${escapeHtml(entry.error || '')}</td>
      </tr>
    `).join('')
    : '<tr><td colspan="4" class="text-muted">No health samples recorded yet.</td></tr>';
  const errorMarkup = recentErrors.length
    ? recentErrors.map((entry) => `
      <li>
        <strong>${escapeHtml(formatHealthTimestamp(entry.checked_at))}</strong>
        <span class="ms-2">${escapeHtml(entry.error || entry.status || 'error')}</span>
      </li>
    `).join('')
    : '<li class="text-muted">No recent connector errors.</li>';

  return `
    <div class="small">
      <div class="d-flex flex-wrap gap-3 mb-2">
        <span><strong>Connector:</strong> ${escapeHtml(payload.connector_name || `Connector ${payload.connector_id}`)}</span>
        <span><strong>Type:</strong> ${escapeHtml(payload.connector_type || '--')}</span>
      </div>
      <div class="row g-3">
        <div class="col-lg-5">
          <div class="fw-semibold mb-1">Recent Errors</div>
          <ul class="mb-0 ps-3">${errorMarkup}</ul>
        </div>
        <div class="col-lg-7">
          <div class="fw-semibold mb-1">Status Timeline</div>
          <div class="table-responsive">
            <table class="table table-sm mb-0">
              <thead>
                <tr>
                  <th>Checked</th>
                  <th>Status</th>
                  <th>Failures</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>${historyMarkup}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderRoutingTraceDetails(trace) {
  const source = trace.source_connector;
  const destination = trace.destination_connector;
  const bot = trace.bot;
  const rule = trace.rule;
  const latestJob = trace.latest_job;
  const explanation = Array.isArray(trace.explanation)
    ? trace.explanation.map((line) => `<li>${escapeHtml(line)}</li>`).join('')
    : '';

  const sourceLabel = source
    ? `${source.name || 'Unnamed'}${source.connector_type ? ` (${source.connector_type})` : ''}`
    : '--';
  const destinationLabel = destination
    ? `${destination.name || 'Unnamed'}${destination.connector_type ? ` (${destination.connector_type})` : ''}`
    : '--';
  const botLabel = bot
    ? `${bot.name || bot.id}${bot.gpt_model ? ` • ${bot.gpt_model}` : ''}${bot.session_id ? ` • session ${bot.session_id}` : ''}`
    : '--';
  const ruleLabel = rule
    ? `${rule.name} • ${rule.match_type}${rule.match_value ? `:${rule.match_value}` : ''} • P${rule.priority}${rule.is_active ? '' : ' • shadow'}`
    : 'No explicit rule';
  const latestJobLabel = latestJob
    ? `${latestJob.status} • ${latestJob.attempts}/${latestJob.max_attempts} attempts${latestJob.next_attempt_at ? ` • next ${escapeHtml(formatRoutingTimestamp(latestJob.next_attempt_at))}` : ''}`
    : 'No delivery job recorded';

  return `
    <div class="small">
      <div class="d-flex flex-wrap gap-3 mb-2">
        <span><strong>Decision:</strong> ${escapeHtml(trace.decision || '--')}</span>
        <span><strong>Event:</strong> #${escapeHtml(trace.event?.id || '--')}</span>
        <span><strong>When:</strong> ${escapeHtml(formatRoutingTimestamp(trace.event?.created_at))}</span>
      </div>
      <div class="mb-1"><strong>Source:</strong> ${escapeHtml(sourceLabel)}</div>
      <div class="mb-1"><strong>Destination:</strong> ${escapeHtml(destinationLabel)}</div>
      <div class="mb-1"><strong>Bot:</strong> ${escapeHtml(botLabel)}</div>
      <div class="mb-1"><strong>Rule:</strong> ${escapeHtml(ruleLabel)}</div>
      <div class="mb-1"><strong>Delivery:</strong> ${escapeHtml(trace.event?.delivery_status || '--')} ${trace.event?.delivery_error ? `• ${escapeHtml(trace.event.delivery_error)}` : ''}</div>
      <div class="mb-1"><strong>Latest Job:</strong> ${escapeHtml(latestJobLabel)}</div>
      <div class="mb-1"><strong>Message:</strong> ${escapeHtml(trace.event?.message_text || '')}</div>
      <div class="mt-2">
        <strong>Why It Routed</strong>
        <ul class="mb-0 mt-1">${explanation || '<li>No trace explanation available.</li>'}</ul>
      </div>
    </div>
  `;
}

async function loadRoutingRules() {
  const list = document.getElementById('routing-rules-list');
  const filterMeta = document.getElementById('routing-rules-filter-meta');
  if (!list) return;
  const allRules = await fetchRoutingRules();
  let filteredConnector = Number.isFinite(routingRulesConnectorFilterId)
    ? cachedConnectors.find((c) => c.id === routingRulesConnectorFilterId)
    : null;
  if (
    Number.isFinite(routingRulesConnectorFilterId)
    && !filteredConnector
    && !allRules.some(
      (rule) => Number.parseInt(rule.connector_id, 10) === Number.parseInt(routingRulesConnectorFilterId, 10)
    )
  ) {
    routingRulesConnectorFilterId = null;
    writeRoutingRulesFilterId(null);
    filteredConnector = null;
  }
  const rules = Number.isFinite(routingRulesConnectorFilterId)
    ? allRules.filter((rule) => (
      filteredConnector
        ? ruleMatchesConnector(rule, filteredConnector)
        : Number.parseInt(rule.connector_id, 10) === Number.parseInt(routingRulesConnectorFilterId, 10)
    ))
    : allRules;
  list.innerHTML = '';
  if (filterMeta) {
    const connectorSelect = document.getElementById("routing-rule-connector");
    if (Number.isFinite(routingRulesConnectorFilterId)) {
      if (connectorSelect) connectorSelect.value = String(routingRulesConnectorFilterId);
      const connector = cachedConnectors.find((c) => c.id === routingRulesConnectorFilterId);
      filterMeta.classList.remove('d-none');
      filterMeta.innerHTML = `Filtered to ${connector?.name || `connector ${routingRulesConnectorFilterId}`}. <button type="button" class="btn btn-link btn-sm p-0" id="routing-rules-clear-filter">Show all</button>`;
      const clearBtn = document.getElementById('routing-rules-clear-filter');
      clearBtn?.addEventListener('click', async () => {
        routingRulesConnectorFilterId = null;
        writeRoutingRulesFilterId(null);
        if (connectorSelect) connectorSelect.value = "";
        await loadRoutingRules();
      });
    } else {
      if (connectorSelect) connectorSelect.value = "";
      filterMeta.classList.add('d-none');
      filterMeta.textContent = '';
    }
  }
  rules.sort((a, b) => b.priority - a.priority);
  rules.forEach((rule) => {
    const item = document.createElement('div');
    item.className = 'list-group-item d-flex justify-content-between align-items-center';
    const connectorLabel = rule.connector_id
      ? (cachedConnectors.find(c => c.id === rule.connector_id)?.name || `Connector ${rule.connector_id}`)
      : (rule.connector_type || 'Any connector');
    const destinationLabel = rule.destination_connector_id
      ? (cachedConnectors.find(c => c.id === rule.destination_connector_id)?.name || `Connector ${rule.destination_connector_id}`)
      : null;
    const botLabel = cachedBots.find(b => b.id === rule.bot_id)?.name || `Bot ${rule.bot_id}`;
    item.innerHTML = `
      <div>
        <div class="fw-semibold">${rule.name}</div>
        <div class="text-muted">
${connectorLabel}${destinationLabel ? ` -> ${destinationLabel}` : ''} • ${botLabel} • ${rule.match_type}${rule.match_value ? `:${rule.match_value}` : ''} • P${rule.priority}
        </div>
      </div>
      <button class="btn btn-sm btn-outline-danger">Delete</button>
    `;
    item.querySelector('button').addEventListener('click', async () => {
      await deleteRoutingRule(rule.id);
      await loadRoutingRules();
    });
    list.appendChild(item);
  });
  togglePanelByData('routing-rules-panel', rules.length > 0);
}

async function loadRoutingJobs() {
  const tableBody = document.querySelector('#routing-jobs-table tbody');
  const meta = document.getElementById('routing-jobs-meta');
  if (!tableBody || routingJobsInFlight) return;
  routingJobsInFlight = true;
  try {
    const jobs = await fetchRoutingJobs({ includeDone: true, limit: 50 });
    const pending = jobs.filter((job) => job.status === 'pending').length;
    const processing = jobs.filter((job) => job.status === 'processing').length;
    const dead = jobs.filter((job) => job.status === 'dead').length;

    if (meta) {
      meta.textContent = `${pending} queued • ${processing} processing • ${dead} dead`;
    }

    tableBody.innerHTML = '';
    if (!jobs.length) {
      const row = document.createElement('tr');
      row.innerHTML = '<td colspan="7" class="text-muted">No routing jobs right now.</td>';
      tableBody.appendChild(row);
      togglePanelByData('routing-jobs-panel', false);
      return;
    }

    jobs.forEach((job) => {
      const row = document.createElement('tr');
      const canRetry = job.status !== 'processing';
      const eventLabel = job.event_id
        ? `#${job.event_id} • ${escapeHtml(job.message_text || 'No preview')}`
        : 'No event';
      row.innerHTML = `
        <td data-label="State">${escapeHtml(job.status)}</td>
        <td data-label="Event">${eventLabel}</td>
        <td data-label="Flow">${escapeHtml(routingFlowLabel(job))}</td>
        <td data-label="Attempts">${job.attempts}/${job.max_attempts}</td>
        <td data-label="Next">${escapeHtml(formatRoutingTimestamp(job.next_attempt_at))}</td>
        <td data-label="Error">${escapeHtml(routingJobError(job))}</td>
        <td data-label="Action">
          <button type="button" class="btn btn-sm btn-outline-secondary" ${canRetry ? '' : 'disabled'}>Retry Now</button>
        </td>
      `;
      const button = row.querySelector('button');
      if (button && canRetry) {
        button.addEventListener('click', async () => {
          button.disabled = true;
          const previousMeta = meta?.textContent || '';
          if (meta) {
            meta.textContent = `Retrying job ${job.id}...`;
          }
          try {
            await retryRoutingJob(job.id);
            await Promise.all([loadRoutingJobs(), loadRoutingEvents()]);
          } catch (err) {
            if (meta) {
              meta.textContent = err.message || `Retry failed for job ${job.id}.`;
            }
          } finally {
            if (meta && meta.textContent === `Retrying job ${job.id}...`) {
              meta.textContent = previousMeta;
            }
            button.disabled = false;
          }
        });
      }
      tableBody.appendChild(row);
    });
    togglePanelByData('routing-jobs-panel', jobs.length > 0);
  } finally {
    routingJobsInFlight = false;
  }
}

async function loadRoutingEvents() {
  const tableBody = document.querySelector('#routing-events-table tbody');
  if (!tableBody) return;
  const events = await fetchRoutingEvents();
  tableBody.innerHTML = '';
  events.forEach((event) => {
    const row = document.createElement('tr');
    const srcLabel = event.connector_type || event.connector_id || '';
    const destLabel = event.destination_connector_type || (event.destination_connector_id ? `connector ${event.destination_connector_id}` : '');
    const flowLabel = destLabel ? `${srcLabel} -> ${destLabel}` : srcLabel;
    row.innerHTML = `
      <td data-label="Time">${event.created_at || ''}</td>
      <td data-label="Connector">${flowLabel}</td>
      <td data-label="Bot">${event.bot_id || ''}</td>
      <td data-label="Status">${event.status}</td>
      <td data-label="Delivery">${event.delivery_status}</td>
      <td data-label="Trace">
        <button type="button" class="btn btn-sm btn-outline-secondary">Trace</button>
      </td>
    `;
    const traceBtn = row.querySelector('button');
    traceBtn?.addEventListener('click', async () => {
      const nextRow = row.nextElementSibling;
      if (nextRow && nextRow.classList.contains('routing-trace-row')) {
        nextRow.remove();
        traceBtn.textContent = 'Trace';
        return;
      }

      traceBtn.disabled = true;
      traceBtn.textContent = 'Loading...';
      const traceRow = document.createElement('tr');
      traceRow.className = 'routing-trace-row';
      const traceCell = document.createElement('td');
      traceCell.colSpan = 6;
      traceCell.className = 'bg-body-tertiary';
      traceCell.textContent = 'Loading route trace...';
      traceRow.appendChild(traceCell);
      row.insertAdjacentElement('afterend', traceRow);
      try {
        const trace = await fetchRoutingTrace(event.id);
        traceCell.innerHTML = renderRoutingTraceDetails(trace);
        traceBtn.textContent = 'Hide';
      } catch (err) {
        traceCell.textContent = err.message || `Unable to load trace for event ${event.id}.`;
        traceBtn.textContent = 'Trace';
      } finally {
        traceBtn.disabled = false;
      }
    });
    tableBody.appendChild(row);
  });
  togglePanelByData('routing-events-panel', events.length > 0);
}

async function loadRoutingOpsPanels() {
  await Promise.all([loadRoutingJobs(), loadRoutingEvents()]);
}

async function refreshConnectorsAfterBundleImport() {
  clearConnectorCaches();
  await fetchConnectorsAndRender({ force: true });
  cachedBots = await fetchBots();
  renderRoutingBotOptions();
  renderRoutingConnectorOptions();
  renderRoutingDestinationOptions();
  renderRoutingSimulatorConnectorOptions();
  if (routingLoaded) {
    await loadRoutingRules();
  }
  if (isPanelExpanded('routing-events-panel') || isPanelExpanded('routing-jobs-panel')) {
    await loadRoutingOpsPanels();
  }
}

async function getConnectors(options = {}) {
  const force = options.force === true;
  const cached = force ? null : readCachedJson(CONNECTORS_CACHE_KEY, CONNECTORS_CACHE_TTL_MS);
  const now = Date.now();
  if (!force && cached) {
    if ((now - connectorsLastFetchAt) < CONNECTORS_MIN_FETCH_INTERVAL_MS) {
      return cached;
    }
    if (now < connectorsBackoffUntil) {
      return cached;
    }
  }
  if (!connectorsFetchInFlight) {
    connectorsFetchInFlight = (async () => {
      const url = force ? `/api/connectors?ts=${Date.now()}` : '/api/connectors';
      const resp = await fetch(url, { cache: force ? 'no-store' : 'default' });
      if (!resp.ok) {
        if (resp.status === 429) {
          connectorsBackoffUntil = Date.now() + CONNECTORS_BACKOFF_MS;
          if (cached) {
            return cached;
          }
          return [];
        }
        if (cached) {
          return cached;
        }
        throw new Error(`Failed to fetch connectors (${resp.status})`);
      }
      const data = await resp.json();
      writeCachedJson(CONNECTORS_CACHE_KEY, data);
      connectorsBackoffUntil = 0;
      connectorsLastFetchAt = Date.now();
      return data;
    })().finally(() => {
      connectorsFetchInFlight = null;
    });
  }
  try {
    return await connectorsFetchInFlight;
  } catch (err) {
    return cached || [];
  }
}

async function createConnector(data) {
  const resp = await fetch('/api/connectors/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const created = await resp.json();
  clearConnectorCaches();
  cachedConnectors = [...cachedConnectors, created];
  renderRoutingConnectorOptions();
  return created;
}

async function updateConnector(id, data) {
  const resp = await fetch(`/api/connectors/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const updated = await resp.json();
  clearConnectorCaches();
  cachedConnectors = cachedConnectors.map(connector =>
    connector.id === id ? updated : connector
  );
  renderRoutingConnectorOptions();
  return updated;
}

async function deleteConnector(id) {
  const resp = await fetch(`/api/connectors/${id}`, { method: 'DELETE' });
  if (!resp.ok) {
    const error = await resp.json();
    throw new Error(error.detail || 'Failed to delete connector');
  }
  cachedConnectors = cachedConnectors.filter(connector => connector.id !== id);
  clearConnectorCaches();
  renderRoutingConnectorOptions();
}

async function testConnector(id) {
  const resp = await fetch(`/api/connectors/${id}/test`, { method: 'POST' });
  return await resp.json();
}

async function getConnectorStatus(id) {
  const resp = await fetch(`/api/connectors/${id}/status`);
  return await resp.json();
}

async function getConnectorDiagnosis(id) {
  const resp = await fetch(`/api/connectors/${id}/diagnose`);
  return await resp.json();
}

async function setConnectorWebhook(id, url) {
  const resp = await fetch(`/api/connectors/${id}/webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url })
  });
  return await resp.json();
}

async function disconnectConnectorOauth(id) {
  const resp = await fetch(`/api/v1/connectors/${id}/oauth`, { method: 'DELETE' });
  if (!resp.ok) {
    let detail = 'Failed to disconnect OAuth';
    try {
      const payload = await resp.json();
      detail = payload.detail || detail;
    } catch (e) {
      // ignore json parse error
    }
    throw new Error(detail);
  }
  clearConnectorCaches();
  return await resp.json();
}

function createConnectorElement(connector) {
  const card = document.createElement('div');
  card.className = 'card mb-2 connector-card';
  const body = document.createElement('div');
  body.className = 'card-body';
  const headerWrap = document.createElement('div');
  headerWrap.className = 'connector-card__header';

  const title = document.createElement('h5');
  title.className = 'mb-1';
  const iconSrc = `/static/icons/connectors/${connector.connector_type}.svg`;
  title.innerHTML = `
    <span class="connector-card__icon">
      <img src="${ICON_PLACEHOLDER_SRC}" data-src="${iconSrc}" alt="" loading="lazy" onerror="this.style.display='none'; this.parentElement.classList.add('is-fallback');" />
      <span class="connector-card__fallback">${connector.connector_type.slice(0, 2).toUpperCase()}</span>
    </span>
    <span class="connector-card__title">${connector.name}</span>
    <span class="connector-card__type">${connector.connector_type}</span>
  `;

  const badges = document.createElement('div');
  badges.className = 'connector-card__badges';

  const statusSpan = document.createElement('span');
  statusSpan.className = 'badge bg-secondary connector-status';
  statusSpan.textContent = connector._status || '...';

  const idBadge = document.createElement('span');
  idBadge.className = 'badge bg-light text-dark';
  idBadge.textContent = `id ${connector.id}`;

  badges.appendChild(statusSpan);
  badges.appendChild(idBadge);

  headerWrap.appendChild(title);
  headerWrap.appendChild(badges);
  body.appendChild(headerWrap);

  const meta = document.createElement('div');
  meta.className = 'connector-meta';
  meta.innerHTML = `
    <span>Last sent: ${connector.last_message_sent || '—'}</span>
    <span>Last received: ${connector.last_message_received || '—'}</span>
  `;
  body.appendChild(meta);

  const fields = connectorFieldMap[connector.connector_type] || [];
  const missingFields = getMissingRequiredFields(connector.connector_type, connector.config || {}, fields);
  if (fields.length) {
    const fieldRow = document.createElement('div');
    fieldRow.className = 'connector-fields';
    fieldRow.innerHTML = `
      <div class="small text-muted">Required fields:</div>
      <div class="connector-fields__list">
        ${fields
          .map((field) => {
            const missing = missingFields.includes(field);
            return `<span class="field-chip ${missing ? 'missing' : 'ok'}">${field}</span>`;
          })
          .join('')}
      </div>
    `;
    body.appendChild(fieldRow);
  }

  const oauth = getConnectorTypeMeta(connector.connector_type)?.oauth || null;
  const snapshot = getConnectorAuthSnapshot(connector, oauth);
  if (oauth) {
    const authRow = document.createElement('div');
    authRow.className = 'connector-auth';
    const providerLabel = snapshot?.provider ? (oauthProviderLabels[snapshot.provider] || snapshot.provider) : '';
    const summary = snapshot ? authStatusText(snapshot) : 'SSO not connected';
    const scopes = snapshot?.scopes || [];
    const scopeText = scopes.length
      ? `Scopes: ${scopes.slice(0, 2).join(', ')}${scopes.length > 2 ? ` +${scopes.length - 2}` : ''}`
      : 'Scopes: unknown';
    const reconnectBtn = snapshot?.provider
      ? `<button class="btn btn-sm btn-outline-secondary" type="button" data-connector-oauth-start="${connector.id}" data-connector-oauth-provider="${snapshot.provider}">Reconnect</button>`
      : '';
    authRow.innerHTML = `
      <div class="connector-auth__summary">
        <span class="connector-auth__state ${snapshot?.isExpired ? 'danger' : snapshot?.isExpiring ? 'warn' : 'ok'}">${summary}</span>
        ${providerLabel ? `<span class="connector-auth__provider">${providerLabel}</span>` : ''}
      </div>
      <div class="connector-auth__meta">${scopeText}</div>
      ${reconnectBtn}
    `;
    body.appendChild(authRow);
    const reconnect = authRow.querySelector('[data-connector-oauth-start]');
    reconnect?.addEventListener('click', () => {
      const query = new URLSearchParams({
        connector_type: connector.connector_type,
      });
      if (snapshot?.provider) {
        query.set('provider', snapshot.provider);
      }
      query.set('connector_id', String(connector.id));
      window.location.href = `/api/v1/connectors/oauth/start?${query.toString()}`;
    });
  }

  const editForm = document.createElement('div');
  editForm.className = 'connector-edit d-none';
  const typeOptions = availableConnectorTypes
    .map((t) => `<option value="${t.id}" ${t.id === connector.connector_type ? 'selected' : ''}>${t.name}</option>`)
    .join('');
  editForm.innerHTML = `
    <div class="row g-2">
      <div class="col-12 col-md-4">
        <label class="form-label">Name</label>
        <input class="form-control form-control-sm" data-field="name" value="${connector.name}">
      </div>
      <div class="col-12 col-md-4">
        <label class="form-label">Type</label>
        <select class="form-select form-select-sm" data-field="type">${typeOptions}</select>
      </div>
      <div class="col-12">
        <label class="form-label">Config (JSON)</label>
        <textarea class="form-control form-control-sm" rows="3" data-field="config">${JSON.stringify(connector.config || {}, null, 2)}</textarea>
      </div>
      <div class="col-12 d-flex gap-2">
        <button class="btn btn-sm btn-primary" type="button" data-action="save">Save</button>
        <button class="btn btn-sm btn-outline-secondary" type="button" data-action="cancel">Cancel</button>
      </div>
    </div>
  `;
  body.appendChild(editForm);

  const editBtn = document.createElement('button');
  editBtn.className = 'btn btn-sm btn-outline-secondary me-2';
  editBtn.textContent = 'Edit';
  editBtn.addEventListener('click', () => {
    editForm.classList.toggle('d-none');
  });

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn btn-sm btn-danger me-2';
  deleteBtn.textContent = 'Delete';
  deleteBtn.addEventListener('click', async () => {
    if (!confirm(`Delete connector "${connector.name}"?`)) return;
    try {
      await deleteConnector(connector.id);
      card.remove();
      renderStatusTable(cachedConnectors);
    } catch (err) {
      alert(err.message);
    }
  });

  const diagnosisEl = document.createElement('div');
  diagnosisEl.className = 'small text-muted mt-2 d-none';

  const testBtn = document.createElement('button');
  testBtn.className = 'btn btn-sm btn-outline-primary me-2';
  testBtn.textContent = 'Test';
  testBtn.addEventListener('click', async () => {
    const result = await testConnector(connector.id);
    statusSpan.textContent = result.status;
  });

  const diagnoseBtn = document.createElement('button');
  diagnoseBtn.className = 'btn btn-sm btn-outline-info';
  diagnoseBtn.textContent = 'Diagnose';
  diagnoseBtn.addEventListener('click', async () => {
    diagnosisEl.classList.remove('d-none');
    diagnosisEl.textContent = 'Diagnosing...';
    try {
      const diagnosis = await getConnectorDiagnosis(connector.id);
      statusSpan.textContent = diagnosis.status || statusSpan.textContent;
      const missing = (diagnosis.missing_required_fields || []).length
        ? diagnosis.missing_required_fields.join(', ')
        : 'none';
      const authState = diagnosis.auth
        ? (diagnosis.auth.connected ? `connected (${diagnosis.auth.provider || 'SSO'})` : `not connected (${diagnosis.auth.provider || 'SSO'})`)
        : 'n/a';
      const actions = (diagnosis.recommended_actions || []).map((action) => `- ${action}`).join('\n');
      diagnosisEl.textContent = [
        `Status: ${diagnosis.status || 'unknown'}`,
        `Missing required: ${missing}`,
        `Auth: ${authState}`,
        diagnosis.error ? `Error: ${diagnosis.error}` : null,
        actions ? `Actions:\n${actions}` : null,
      ].filter(Boolean).join('\n');
    } catch (err) {
      diagnosisEl.textContent = `Diagnosis failed: ${err?.message || err}`;
    }
  });

  editForm.querySelector('[data-action="save"]').addEventListener('click', async () => {
    const nameValue = editForm.querySelector('[data-field="name"]').value.trim();
    const typeValue = editForm.querySelector('[data-field="type"]').value.trim();
    const configText = editForm.querySelector('[data-field="config"]').value.trim();
    if (!nameValue || !typeValue) {
      alert('Name and type are required');
      return;
    }
    let configValue = {};
    if (configText) {
      try {
        configValue = JSON.parse(configText);
      } catch (err) {
        alert('Config must be valid JSON');
        return;
      }
    }
    const updated = await updateConnector(connector.id, {
      name: nameValue,
      connector_type: typeValue,
      config: configValue
    });
    connector.name = updated.name;
    connector.connector_type = updated.connector_type;
    connector.config = updated.config;
    header.childNodes[0].nodeValue = `${updated.name} (${updated.connector_type})`;
    editForm.classList.add('d-none');
    fetchConnectorsAndRender();
  });
  editForm.querySelector('[data-action="cancel"]').addEventListener('click', () => {
    editForm.classList.add('d-none');
  });

  const actions = document.createElement('div');
  actions.className = 'connector-card__actions';
  actions.appendChild(editBtn);
  actions.appendChild(deleteBtn);
  actions.appendChild(testBtn);
  actions.appendChild(diagnoseBtn);
  body.appendChild(actions);
  body.appendChild(diagnosisEl);
  card.appendChild(body);
  return card;
}

function startStatusPolling() {
  if (!isPanelExpanded('connector-status-panel')) return;
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
  }
  fetchStatuses();
  statusPollTimer = setInterval(fetchStatuses, 120000);
}

function stopStatusPolling() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }
}

async function fetchStatuses(options = {}) {
  if (!isPanelExpanded('connector-status-panel')) return;
  if (statusPollInFlight) return;
  statusPollInFlight = true;
  try {
    const connectors = await getConnectors();
    cachedConnectors = connectors;

    const refresh = options.refresh === true;
    const url = refresh ? `/api/v1/connectors/statuses?refresh=1` : '/api/v1/connectors/statuses';
    const resp = await fetch(url, { cache: 'no-store' });
    const payload = resp.ok ? await resp.json() : { items: [] };
    const byId = new Map((payload.items || []).map((row) => [row.connector_id, row]));
    connectorHealthById = byId;

    const cards = document.querySelectorAll('.connector-card');
    for (const connector of connectors) {
      const row = byId.get(connector.id);
      if (!row) continue;
      connector._status = { status: row.status };

      const card = Array.from(cards).find((c) => c.querySelector('.connector-card__badges')?.textContent?.includes(`id ${connector.id}`));
      const badge = card?.querySelector('.connector-status');
      if (badge) {
        badge.textContent = row.status;
      }
    }

    renderStatusTable(connectors);
  } finally {
    statusPollInFlight = false;
  }
}

function renderStatusTable(connectors) {
  const tbody = document.querySelector('#connector-status-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  connectors.forEach((c) => {
    const status = c._status || { status: 'unknown' };
    const tr = document.createElement('tr');
    const health = connectorHealthById.get(c.id) || {};
    const checked = health.checked_at ? new Date(health.checked_at * 1000).toLocaleString() : '';
    tr.innerHTML = `
      <td data-label="Connector">${c.name} (${c.connector_type})</td>
      <td data-label="Status">${status.status || 'unknown'}</td>
      <td data-label="Last sent">${status.last_message_sent || ''}</td>
      <td data-label="Last received">${status.last_message_received || ''}</td>
      <td data-label="Checked">${checked}</td>
      <td data-label="Failures">${health.failures ?? ''}</td>
      <td data-label="History">
        <button type="button" class="btn btn-sm btn-outline-secondary">History</button>
      </td>
    `;
    const historyBtn = tr.querySelector('button');
    historyBtn?.addEventListener('click', async () => {
      const nextRow = tr.nextElementSibling;
      if (nextRow && nextRow.classList.contains('connector-status-history-row')) {
        nextRow.remove();
        historyBtn.textContent = 'History';
        return;
      }

      historyBtn.disabled = true;
      historyBtn.textContent = 'Loading...';
      const detailsRow = document.createElement('tr');
      detailsRow.className = 'connector-status-history-row';
      const detailsCell = document.createElement('td');
      detailsCell.colSpan = 7;
      detailsCell.className = 'bg-body-tertiary';
      detailsCell.textContent = 'Loading connector history...';
      detailsRow.appendChild(detailsCell);
      tr.insertAdjacentElement('afterend', detailsRow);
      try {
        const payload = await fetchConnectorStatusHistory(c.id);
        detailsCell.innerHTML = renderConnectorStatusHistoryDetails(payload);
        historyBtn.textContent = 'Hide';
      } catch (err) {
        detailsCell.textContent = err.message || `Unable to load history for connector ${c.id}.`;
        historyBtn.textContent = 'History';
      } finally {
        historyBtn.disabled = false;
      }
    });
    tbody.appendChild(tr);
  });
  togglePanelByData('connector-status-panel', connectors.length > 0);
}

function startRoutingPolling() {
  if (!isPanelExpanded('routing-events-panel') && !isPanelExpanded('routing-jobs-panel')) {
    return;
  }
  if (routingPollTimer) {
    clearInterval(routingPollTimer);
  }
  routingPollTimer = setInterval(loadRoutingOpsPanels, 30000);
}

function stopRoutingPolling() {
  if (routingPollTimer) {
    clearInterval(routingPollTimer);
    routingPollTimer = null;
  }
}

function renderWebhookUrls() {
  const origin = window.location.origin;
  const slackInput = document.getElementById('slack-webhook-url');
  const googleInput = document.getElementById('google-chat-webhook-url');
  const webhookInput = document.getElementById('generic-webhook-url');
  if (slackInput) {
    slackInput.value = `${origin}/api/v1/connectors/webhooks/slack/{connector_id}`;
  }
  const genericTypedInput = document.getElementById('generic-typed-webhook-url');
  if (genericTypedInput) {
    genericTypedInput.value = `${origin}/api/v1/connectors/webhooks/{connector_type}/{connector_id}`;
  }
  if (googleInput) {
    googleInput.value = `${origin}/api/v1/connectors/webhooks/google_chat/{connector_id}`;
  }
  if (webhookInput) {
    webhookInput.value = `${origin}/api/v1/connectors/webhooks/webhook/{connector_id}`;
  }
  const discordInput = document.getElementById('discord-webhook-url');
  const teamsInput = document.getElementById('teams-webhook-url');
  const telegramInput = document.getElementById('telegram-webhook-url');
  if (discordInput) {
    discordInput.value = `${origin}/api/v1/connectors/webhooks/discord/{connector_id}`;
  }
  if (teamsInput) {
    teamsInput.value = `${origin}/api/v1/connectors/webhooks/teams/{connector_id}`;
  }
  if (telegramInput) {
    telegramInput.value = `${origin}/api/v1/connectors/webhooks/telegram/{connector_id}`;
  }
  const whatsappInput = document.getElementById('whatsapp-webhook-url');
  if (whatsappInput) {
    whatsappInput.value = `${origin}/api/v1/connectors/webhooks/whatsapp/{connector_id}`;
  }
  const jiraInput = document.getElementById('jira-webhook-url');
  if (jiraInput) {
    jiraInput.value = `${origin}/api/v1/connectors/webhooks/jira/{connector_id}`;
  }
  const facebookInput = document.getElementById('facebook-webhook-url');
  if (facebookInput) {
    facebookInput.value = `${origin}/api/v1/connectors/webhooks/facebook/{connector_id}`;
  }
  const pinterestInput = document.getElementById('pinterest-webhook-url');
  if (pinterestInput) {
    pinterestInput.value = `${origin}/api/v1/connectors/webhooks/pinterest/{connector_id}`;
  }
  const linkedinInput = document.getElementById('linkedin-webhook-url');
  if (linkedinInput) {
    linkedinInput.value = `${origin}/api/v1/connectors/webhooks/linkedin/{connector_id}`;
  }
  const redditInput = document.getElementById('reddit-webhook-url');
  if (redditInput) {
    redditInput.value = `${origin}/api/v1/connectors/webhooks/reddit/{connector_id}`;
  }
  const twitterInput = document.getElementById('twitter-webhook-url');
  if (twitterInput) {
    twitterInput.value = `${origin}/api/v1/connectors/webhooks/twitter/{connector_id}`;
  }
  const instagramInput = document.getElementById('instagram-webhook-url');
  if (instagramInput) {
    instagramInput.value = `${origin}/api/v1/connectors/webhooks/instagram/{connector_id}`;
  }
  const glimpserInput = document.getElementById('glimpser-webhook-url');
  if (glimpserInput) {
    glimpserInput.value = `${origin}/api/v1/connectors/webhooks/glimpser/{connector_id}`;
  }
  const hubitatInput = document.getElementById('hubitat-webhook-url');
  if (hubitatInput) {
    hubitatInput.value = `${origin}/api/v1/connectors/webhooks/hubitat/{connector_id}`;
  }
  const activityMonitorInput = document.getElementById('activity-monitor-webhook-url');
  if (activityMonitorInput) {
    activityMonitorInput.value = `${origin}/api/v1/connectors/webhooks/activity_monitor/{connector_id}`;
  }
}

function enableCopyButtons() {
  document.querySelectorAll('[data-copy-target]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-copy-target');
      const input = document.getElementById(targetId);
      if (!input) return;
      input.select();
      input.setSelectionRange(0, 99999);
      navigator.clipboard.writeText(input.value);
    });
  });
}

function setupConnectorBundleControls() {
  const exportBtn = document.getElementById('connector-bundle-export');
  const importBtn = document.getElementById('connector-bundle-import');
  const fileInput = document.getElementById('connector-bundle-file');
  const payloadInput = document.getElementById('connector-bundle-payload');
  const statusEl = document.getElementById('connector-bundle-status');
  if (!exportBtn || !importBtn || !payloadInput || !statusEl) return;

  exportBtn.addEventListener('click', async () => {
    exportBtn.disabled = true;
    statusEl.textContent = 'Exporting bundle...';
    try {
      const bundle = await fetchConnectorBundleExport();
      payloadInput.value = JSON.stringify(bundle, null, 2);
      downloadJsonFile(buildConnectorBundleFilename(bundle), bundle);
      statusEl.textContent = `Exported ${bundle.connectors?.length || 0} connectors and ${bundle.routing_rules?.length || 0} routing rules. OAuth tokens were omitted.`;
    } catch (err) {
      statusEl.textContent = err?.message || 'Export failed.';
    } finally {
      exportBtn.disabled = false;
    }
  });

  fileInput?.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    try {
      payloadInput.value = await file.text();
      statusEl.textContent = `Loaded ${file.name}. Review the bundle JSON, then import it.`;
    } catch (err) {
      statusEl.textContent = err?.message || `Unable to read ${file.name}.`;
    }
  });

  importBtn.addEventListener('click', async () => {
    const raw = payloadInput.value.trim();
    if (!raw) {
      statusEl.textContent = 'Paste bundle JSON or choose a file first.';
      return;
    }
    let bundle;
    try {
      bundle = JSON.parse(raw);
    } catch (err) {
      statusEl.textContent = 'Bundle JSON is invalid.';
      return;
    }

    importBtn.disabled = true;
    statusEl.textContent = 'Importing bundle...';
    try {
      const result = await importConnectorBundle(bundle);
      await refreshConnectorsAfterBundleImport();
      const warnings = Array.isArray(result.warnings) && result.warnings.length
        ? ` Warning: ${result.warnings.join(' ')}`
        : '';
      statusEl.textContent = `Imported bundle. Connectors: +${result.connectors_created} created, ${result.connectors_updated} updated. Rules: +${result.routing_rules_created} created, ${result.routing_rules_updated} updated.${warnings}`;
    } catch (err) {
      statusEl.textContent = err?.message || 'Import failed.';
    } finally {
      importBtn.disabled = false;
    }
  });
}
