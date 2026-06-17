const http = require('http');
const https = require('https');
const url = require('url');

const PORT = process.env.PORT || 8080;

// Helper to make HTTP/HTTPS requests
function requestUrl(targetUrl, headers = {}, callback) {
  const parsed = url.parse(targetUrl);
  const client = parsed.protocol === 'https:' ? https : http;
  
  const options = {
    method: 'GET',
    host: parsed.host,
    path: parsed.path,
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      ...headers
    }
  };

  return client.request(options, callback);
}

const server = http.createServer((req, res) => {
  // CORS headers
  const origin = req.headers.origin || '*';
  res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Access-Control-Allow-Credentials', 'true');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Range');
  res.setHeader('Access-Control-Expose-Headers', 'Content-Length, Content-Range');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  // ── Domain Protection ─────────────────────────────────────────────────────
  const ALLOWED_DOMAINS = [
    'zetasports.online',
    'localhost',
    '127.0.0.1',
    'lordatomic.github.io'
  ];

  const RESTRICTION_IMAGE_URL = 'https://lordatomic.github.io/uefa/restriction.png';

  // Returns false if the URL string contains an unauthorized host
  function isDomainAllowed(urlStr) {
    if (!urlStr) return true; // no header = direct/server access → allow
    try {
      const host = urlStr.replace(/^https?:\/\//i, '').split('/')[0].split(':')[0].toLowerCase();
      if (host === 'null' || host === '') return true;
      return ALLOWED_DOMAINS.includes(host) || host.endsWith('.zetasports.online');
    } catch (_) {
      return false;
    }
  }

  // Serves a fake HLS M3U8 that shows the restriction image inside any player
  function serveRestrictionStream(res) {
    const restrictionM3U8 = [
      '#EXTM3U',
      '#EXT-X-VERSION:3',
      '#EXT-X-TARGETDURATION:10',
      '#EXT-X-MEDIA-SEQUENCE:0',
      '#EXTINF:10.0,',
      RESTRICTION_IMAGE_URL,
      '#EXT-X-ENDLIST'
    ].join('\n');

    res.writeHead(200, { 'Content-Type': 'application/vnd.apple.mpegurl' });
    res.end(restrictionM3U8);
  }

  // Check Referer and Origin headers
  const referer = req.headers.referer || '';
  const originHeader = req.headers.origin || '';

  const isAuthorized = isDomainAllowed(referer) && isDomainAllowed(originHeader);

  const parsedUrl = url.parse(req.url);
  const pathname = parsedUrl.pathname;

  // 1. Route: /stream/:id
  // Retrieves the OK.ru stream, rewrites the master playlist, and returns it.
  const streamMatch = pathname.match(/^\/stream\/(\d+)(?:\/index\.m3u8)?$/);
  if (streamMatch) {
    // If unauthorized domain → serve restriction image as HLS
    if (!isAuthorized) {
      console.warn(`[Stream Blocked] Unauthorized request. Serving restriction stream. Origin: ${originHeader}, Referer: ${referer}`);
      return serveRestrictionStream(res);
    }

    const videoId = streamMatch[1];
    const okEmbedUrl = `https://ok.ru/videoembed/${videoId}`;
    
    console.log(`[Stream] Fetching OK.ru embed for ID: ${videoId}`);
    
    const handleEmbedPageHtml = (body) => {
      try {
        // Extract metadata JSON from flashvars
        const targetMarker = 'hlsMasterPlaylistUrl';
        if (!body.includes(targetMarker)) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: "Could not find hlsMasterPlaylistUrl in page. Embed might be restricted or deleted." }));
          return;
        }

        // Regex to find data-options JSON block
        const dataOptionsRegex = /data-options="([^"]+)"/;
        const match = body.match(dataOptionsRegex);
        if (!match) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: "Could not extract data-options" }));
          return;
        }

        // Unescape HTML entities
        const unescaped = match[1]
          .replace(/&amp;/g, '&')
          .replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>')
          .replace(/&quot;/g, '"')
          .replace(/&#039;/g, "'");

        const options = JSON.parse(unescaped);
        const metadata = JSON.parse(options.flashvars.metadata);
        
        const masterPlaylistUrl = metadata.hlsMasterPlaylistUrl;
        if (!masterPlaylistUrl) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: "Master playlist URL not found in metadata" }));
          return;
        }

        console.log(`[Stream] Extracted Master Playlist: ${masterPlaylistUrl}`);

        // Fetch the master playlist content
        const playlistReq = requestUrl(masterPlaylistUrl, {}, (playlistRes) => {
          let playlistBody = '';
          playlistRes.on('data', chunk => playlistBody += chunk);
          playlistRes.on('end', () => {
            const host = req.headers.host;
            const protocol = req.headers['x-forwarded-proto'] || 'http';
            const baseUrl = `${protocol}://${host}/proxy`;
            
            const lines = playlistBody.split(/\r?\n/);
            const rewrittenLines = lines.map(line => {
              const trimmed = line.trim();
              if (trimmed === '' || trimmed.startsWith('#')) {
                return line;
              }
              
              const absoluteUrl = new URL(trimmed, masterPlaylistUrl).href;
              const parsed = url.parse(absoluteUrl);
              const cleanProto = parsed.protocol.replace(':', '');
              const rest = absoluteUrl.substring(parsed.protocol.length + 2);
              return `${baseUrl}/${cleanProto}/${rest}`;
            });

            const rewritten = rewrittenLines.join('\n');

            res.writeHead(200, { 'Content-Type': 'application/vnd.apple.mpegurl' });
            res.end(rewritten);
          });
        });
        playlistReq.on('error', (e) => {
          res.writeHead(500);
          res.end("Master Playlist Fetch Error: " + e.message);
        });
        playlistReq.end();

      } catch (e) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: e.message }));
      }
    };

    // Fetch the embed page spoofing the referrer
    const okReq = requestUrl(okEmbedUrl, { 'Referer': 'https://hellosports.live/' }, (okRes) => {
      let body = '';
      okRes.on('data', chunk => body += chunk);
      okRes.on('end', () => {
        handleEmbedPageHtml(body);
      });
    });
    okReq.on('error', (e) => {
      console.log(`[Stream] Node fetch failed (${e.message}). Retrying with curl...`);
      const { exec } = require('child_process');
      const curlCmd = `curl -s -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" -e "https://hellosports.live/" "${okEmbedUrl}"`;
      
      exec(curlCmd, { maxBuffer: 1024 * 1024 * 5 }, (curlErr, stdout, stderr) => {
        if (curlErr) {
          console.error(`[Stream] Curl fallback failed:`, curlErr.message);
          res.writeHead(500);
          res.end("OK.ru Embed Fetch Error (Node & Curl failed): " + curlErr.message);
          return;
        }
        handleEmbedPageHtml(stdout);
      });
    });
    okReq.end();
    return;
  }

  // 2. Route: /proxy/:protocol/:domain/:path...
  // Proxies sub-playlists and stream segments.
  const proxyMatch = pathname.match(/^\/proxy\/(https?)\/([^\/]+)\/(.+)$/);
  if (proxyMatch) {
    // If unauthorized domain → serve restriction image as HLS
    if (!isAuthorized) {
      console.warn(`[Proxy Blocked] Unauthorized segment request. Serving restriction stream.`);
      return serveRestrictionStream(res);
    }

    const protocol = proxyMatch[1];
    const domain = proxyMatch[2];
    const pathAndQuery = proxyMatch[3] + (parsedUrl.search || '');
    const targetUrl = `${protocol}://${domain}/${pathAndQuery}`;

    console.log(`[Proxy] Fetching: ${targetUrl}`);

    const isPlaylist = targetUrl.split('?')[0].endsWith('.m3u8');

    // Extract client Range header
    const headers = {};
    if (req.headers.range) {
      headers['Range'] = req.headers.range;
    }

    const proxyReq = requestUrl(targetUrl, headers, (proxyRes) => {
      // Clean Content-Type
      let contentType = proxyRes.headers['content-type'] || '';
      contentType = contentType.split(';')[0].trim();
      if (!contentType) {
        contentType = isPlaylist ? 'application/vnd.apple.mpegurl' : 'application/octet-stream';
      }

      // Prepare response headers
      const responseHeaders = {
        'Content-Type': contentType
      };

      // Expose and write range and length headers if they exist in the target response
      if (proxyRes.headers['content-range']) {
        responseHeaders['Content-Range'] = proxyRes.headers['content-range'];
      }
      if (proxyRes.headers['content-length']) {
        responseHeaders['Content-Length'] = proxyRes.headers['content-length'];
      }
      if (proxyRes.headers['accept-ranges']) {
        responseHeaders['Accept-Ranges'] = proxyRes.headers['accept-ranges'];
      }

      // Write head with correct status code
      res.writeHead(proxyRes.statusCode, responseHeaders);

      if (isPlaylist) {
        // Rewrite sub-playlist absolute URLs
        let playlistBody = '';
        proxyRes.on('data', chunk => playlistBody += chunk);
        proxyRes.on('end', () => {
          const host = req.headers.host;
          const protocolHeader = req.headers['x-forwarded-proto'] || 'http';
          const baseUrl = `${protocolHeader}://${host}/proxy`;

          const rewritten = playlistBody.replace(/(https?:\/\/)([^\s]+)/g, (m, proto, rest) => {
            const cleanProto = proto.replace('://', '');
            return `${baseUrl}/${cleanProto}/${rest}`;
          });

          res.end(rewritten);
        });
      } else {
        // Pipe binary segments directly
        proxyRes.pipe(res);
      }
    });

    proxyReq.on('error', (err) => {
      console.log(`[Proxy Error] ${targetUrl}:`, err.message);
      res.writeHead(500);
      res.end('Proxy Error: ' + err.message);
    });

    proxyReq.end();
    return;
  }

  // Default homepage
  res.writeHead(200, { 'Content-Type': 'text/html' });
  res.end(`
    <h1>OK.ru Stream Proxy Service</h1>
    <p>Usage: <code>/stream/[videoId]</code></p>
    <p>Example: <a href="/stream/15177422544410">/stream/15177422544410</a></p>
  `);
});

server.listen(PORT, () => {
  console.log(`Proxy server listening on port ${PORT}`);
});
