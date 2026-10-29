const http = require('http');

http.createServer((req, res) => {
  const send = (status, body) => {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  };
  if (req.method !== 'POST' || req.url.split('?')[0] !== '/mcp') {
    return send(501, { error: 'Endpoint not modeled' });
  }
  const body = req.body;
  if (req.headers.authorization !== 'Bearer dummy-client-key' || req.headers.origin !== 'http://source.test') {
    return send(403, { error: 'Invalid scoped caller' });
  }
  if (!body || body.jsonrpc !== '2.0' || body.method !== 'tools/list' || !body.params?._meta) {
    return send(400, { error: 'Invalid protocol request' });
  }
  return send(200, { jsonrpc: '2.0', id: body.id, result: { tools: [] } });
}).listen(process.env.PORT);
