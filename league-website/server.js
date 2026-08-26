const http = require('http');
const fs = require('fs');
const path = require('path');
const PORT = Number(process.env.PORT || 3000);
const BOT_API_BASE = (process.env.BOT_API_BASE || 'https://xpc-10-production-95bb.up.railway.app').replace(/\/$/, '');
const GUILD_ID = process.env.GUILD_ID || '1542189200571371530';
const index = fs.readFileSync(path.join(__dirname, 'public', 'index.html'));
http.createServer(async (req, res) => {
  if (req.url.startsWith('/api/league')) {
    try {
      const upstream = await fetch(`${BOT_API_BASE}/api/public/league?guild_id=${encodeURIComponent(GUILD_ID)}`);
      const body = await upstream.text();
      const type = upstream.headers.get('content-type') || '';
      if (!upstream.ok || !type.includes('application/json')) {
        res.writeHead(502, {'content-type':'application/json'});
        return res.end(JSON.stringify({error:'The league website is online, but the bot data service is not connected. Check BOT_API_BASE and the bot service domain.'}));
      }
      res.writeHead(200, {'content-type':'application/json','cache-control':'public,max-age=20'}); return res.end(body);
    } catch (error) { res.writeHead(502, {'content-type':'application/json'}); return res.end(JSON.stringify({error:'The live league feed is temporarily unavailable.'})); }
  }
  res.writeHead(200, {'content-type':'text/html; charset=utf-8','cache-control':'no-cache'}); res.end(index);
}).listen(PORT, '0.0.0.0', () => console.log(`XPC league website listening on ${PORT}`));

