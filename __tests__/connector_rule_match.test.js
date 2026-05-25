const { ruleMatchesConnector } = require('../app/static/js/connector_rule_match.js');

describe('ruleMatchesConnector', () => {
  const connector = { id: 7, connector_type: 'slack' };

  test('matches by connector_id when present', () => {
    expect(ruleMatchesConnector({ connector_id: 7, connector_type: 'discord' }, connector)).toBe(true);
    expect(ruleMatchesConnector({ connector_id: 8, connector_type: 'slack' }, connector)).toBe(false);
  });

  test('falls back to connector_type when connector_id is absent', () => {
    expect(ruleMatchesConnector({ connector_type: 'slack' }, connector)).toBe(true);
    expect(ruleMatchesConnector({ connector_type: 'discord' }, connector)).toBe(false);
  });

  test('handles string numeric connector_id values', () => {
    expect(ruleMatchesConnector({ connector_id: '7' }, connector)).toBe(true);
    expect(ruleMatchesConnector({ connector_id: '8' }, connector)).toBe(false);
  });
});
