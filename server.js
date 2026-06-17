const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const url = require('url');
const { exec } = require('child_process');

const PORT = 3000;
const INDEX_PATH = path.join(__dirname, 'index.html');

function readStreams() {
  const html = fs.readFileSync(INDEX_PATH, 'utf8');
  const startMarker = '// === STREAM_DATA_START ===';
  const endMarker = '// === STREAM_DATA_END ===';
  
  const startIndex = html.indexOf(startMarker);
  const endIndex = html.indexOf(endMarker);
  
  if (startIndex === -1 || endIndex === -1) {
    throw new Error('Markers not found in index.html!');
  }
  
  const block = html.substring(startIndex + startMarker.length, endIndex).trim();
  const jsonText = block.replace('const streams =', '').replace(/;$/, '').trim();
  // Safely evaluate using Function constructor
  return Function(`return ${jsonText}`)();
}

function writeStreams(streams) {
  const html = fs.readFileSync(INDEX_PATH, 'utf8');
  const startMarker = '// === STREAM_DATA_START ===';
  const endMarker = '// === STREAM_DATA_END ===';
  
  const startIndex = html.indexOf(startMarker);
  const endIndex = html.indexOf(endMarker);
  
  if (startIndex === -1 || endIndex === -1) {
    throw new Error('Markers not found in index.html!');
  }
  
  const newBlock = `const streams = ${JSON.stringify(streams, null, 2)};`;
  const updatedHtml = html.substring(0, startIndex + startMarker.length) + '\n    ' + newBlock + '\n    ' + html.substring(endIndex);
  fs.writeFileSync(INDEX_PATH, updatedHtml, 'utf8');
}

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  
  // CORS Headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }
  
  if (parsedUrl.pathname === '/' || parsedUrl.pathname === '/admin') {
    // Serve admin.html
    const adminPath = path.join(__dirname, 'admin.html');
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(fs.readFileSync(adminPath, 'utf8'));
    return;
  }
  
  if (parsedUrl.pathname === '/api/streams' && req.method === 'GET') {
    try {
      const streams = readStreams();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(streams));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }
  
  if (parsedUrl.pathname === '/api/streams' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try {
        const streams = JSON.parse(body);
        writeStreams(streams);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true }));
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }
  
  if (parsedUrl.pathname === '/api/check-status' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try {
        const { url: testUrl } = JSON.parse(body);
        const parsed = url.parse(testUrl);
        const client = parsed.protocol === 'https:' ? https : http;
        
        const reqTest = client.request({
          method: 'GET',
          host: parsed.host,
          path: parsed.path,
          headers: { 'User-Agent': 'Mozilla/5.0' },
          timeout: 3000
        }, (resTest) => {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: resTest.statusCode, working: resTest.statusCode >= 200 && resTest.statusCode < 400 }));
        });
        
        reqTest.on('error', (err) => {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: 'ERROR', working: false, message: err.message }));
        });
        
        reqTest.on('timeout', () => {
          reqTest.destroy();
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: 'TIMEOUT', working: false }));
        });
        
        reqTest.end();
      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    });
    return;
  }
  
  if (parsedUrl.pathname === '/api/push' && req.method === 'POST') {
    console.log("Git push triggered...");
    exec('git add index.html && git commit -m "Update streams via Offline Admin Panel" && git push origin main', { cwd: __dirname }, (err, stdout, stderr) => {
      if (err) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message, details: stderr }));
      } else {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: true, log: stdout }));
      }
    });
    return;
  }
  
  res.writeHead(404);
  res.end('Not Found');
});

server.listen(PORT, () => {
  console.log(`===================================================`);
  console.log(` UEFA OFFLINE ADMIN SERVER RUNNING`);
  console.log(` Access Admin Panel: http://localhost:${PORT}`);
  console.log(`===================================================`);
});
