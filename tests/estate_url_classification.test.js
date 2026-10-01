const fs = require('fs');

function readFunction(source, name) {
  const match = source.match(new RegExp(`^( *)function ${name}\\(`, 'm'));
  if (!match) throw new Error(`Missing ${name}`);
  const start = match.index;
  const end = source.indexOf(`\n${match[1]}}`, start);
  return source.slice(start, end + match[1].length + 2);
}

for (const file of ['home.js', 'systems.js', 'messages_log.js']) {
  describe(file, () => {
    const source = fs.readFileSync(`app/static/js/${file}`, 'utf8');
    const functions = ['networkHostname', 'isTailnetHostLike'];
    if (file !== 'messages_log.js') functions.push('isLanHostLike', 'laneNameForService');
    const api = new Function(
      'URL', 'PRIVATE_SERVICE_SLUGS', 'PERSONAL_SERVICE_SLUGS', 'WORK_SERVICE_SLUGS', 'SHARED_SERVICE_SLUGS',
      functions.map(name => readFunction(source, name)).join('\n') + `\nreturn {${functions.join(',')}};`,
    )(URL, new Set(), new Set(), new Set(), new Set());

    test.each([
      'https://networking.tail94915.ts.net/path',
      'NETWORKING.TAIL94915.TS.NET:443',
      'https://networking.tail94915.ts.net./',
      '100.64.0.1', 'https://100.127.255.254:8443/path',
    ])('recognizes a real tailnet host: %s', value => {
      expect(api.isTailnetHostLike(value)).toBe(true);
    });

    test.each([
      'https://example.com/path/networking.tail94915.ts.net',
      'https://example.com/?host=networking.tail94915.ts.net',
      'https://networking.tail94915.ts.net.example.com/',
      'https://networking.tail94915.ts.net@example.com/',
      'https://tailscale.example.com/', 'https://example.com/path/100.64.0.1',
      '100.63.0.1', '100.128.0.1', '100.64.999.1',
      'javascript://networking.tail94915.ts.net/',
      'https://networking.tail94915.ts.net\\@example.com',
      'https://networking.tail94915.ts.net\n.example.com',
      '/networking.tail94915.ts.net', '', null,
    ])('rejects a misleading tailnet marker: %s', value => {
      expect(api.isTailnetHostLike(value)).toBe(false);
    });

    if (file !== 'messages_log.js') {
      test.each(['https://norman.home.arpa/path', 'norman.local:8000', 'localhost:8080', '192.168.2.1', '10.1.2.3', '172.31.255.1'])('recognizes LAN hosts: %s', value => {
        expect(api.isLanHostLike(value)).toBe(true);
      });
      test.each(['https://example.com/localhost', 'https://example.com/192.168.2.1', 'https://norman.local.example.com/', '172.32.0.1', '10.999.2.3'])('does not label a public host as LAN: %s', value => {
        expect(api.isLanHostLike(value)).toBe(false);
      });
      test('only the exact Networking host overrides the work lane', () => {
        const principal = { slug: 'openbrand' };
        expect(api.laneNameForService({ web_url: 'https://networking.tail94915.ts.net/' }, principal)).toBe('Shared');
        expect(api.laneNameForService({ web_url: 'https://example.com/networking.tail94915.ts.net' }, principal)).toBe('Work');
      });
    }
  });
}
