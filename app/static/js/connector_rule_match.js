(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.NormanConnectorRuleMatch = factory();
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function normalizeInt(value) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function ruleMatchesConnector(rule, connector) {
    if (!rule || !connector) return false;
    const connectorId = normalizeInt(connector.id);
    const ruleConnectorId = normalizeInt(rule.connector_id);

    if (connectorId !== null && ruleConnectorId !== null) {
      return connectorId === ruleConnectorId;
    }
    if (typeof rule.connector_type === 'string' && rule.connector_type.trim()) {
      return rule.connector_type === connector.connector_type;
    }
    return false;
  }

  return { ruleMatchesConnector: ruleMatchesConnector };
}));
