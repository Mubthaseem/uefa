addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  const url = new URL(request.url);
  const pathname = url.pathname;

  // CORS headers
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Range',
    'Access-Control-Expose-Headers': 'Content-Length, Content-Range',
    'Access-Control-Allow-Credentials': 'true'
  };

  if (request.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  // 3. Route: /player
  if (pathname === '/player' || pathname === '/player.html') {
    const searchParams = url.search || '?key=itshelosportsniga';
    const targetUrl = `https://admin.hellospz.cfd/player.html${searchParams}`;
    try {
      const response = await fetch(targetUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Referer': 'https://admin.hellospz.cfd/'
        }
      });
      let html = await response.text();

      // Bypass domain lock
      html = html.replace('if (!isAllowed) {', 'if (false) {');

      // Rewrite relative URLs to absolute
      html = html.replace(/(href|src)="\/([^"]+)"/g, '$1="https://admin.hellospz.cfd/$2"');
      html = html.replace(/(href|src)='\/([^']+)'/g, '$1="https://admin.hellospz.cfd/$2"');

      return new Response(html, {
        headers: {
          'Content-Type': 'text/html; charset=UTF-8',
          'Access-Control-Allow-Origin': '*'
        }
      });
    } catch (e) {
      return new Response('Error loading player: ' + e.message, { status: 500 });
    }
  }

  // 4. Route: /get-m3u8
  if (pathname === '/get-m3u8') {
    const key = url.searchParams.get('key') || 'itshelosportsniga';
    const tokenUrl = `https://admin.hellospz.cfd/api/token/${key}`;
    try {
      const response = await fetch(tokenUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Referer': 'https://admin.hellospz.cfd/'
        }
      });
      if (!response.ok) {
        return new Response('Error fetching token: HTTP ' + response.status, { status: 500, headers: corsHeaders });
      }
      const data = await response.json();
      if (data && data.m3u8) {
        const absoluteM3u8 = `https://admin.hellospz.cfd${data.m3u8}`;
        return new Response(absoluteM3u8, {
          headers: {
            ...corsHeaders,
            'Content-Type': 'text/plain'
          }
        });
      } else {
        return new Response('No m3u8 URL found in token response: ' + JSON.stringify(data), { status: 404, headers: corsHeaders });
      }
    } catch (e) {
      return new Response('Error: ' + e.message, { status: 500, headers: corsHeaders });
    }
  }

  // 5. Route: /play-stream
  if (pathname === '/play-stream') {
    const key = url.searchParams.get('key') || 'itshelosportsniga';
    const tokenUrl = `https://admin.hellospz.cfd/api/token/${key}`;
    try {
      const response = await fetch(tokenUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Referer': 'https://admin.hellospz.cfd/'
        }
      });
      if (!response.ok) {
        return new Response('Error fetching token: HTTP ' + response.status, { status: 500, headers: corsHeaders });
      }
      const data = await response.json();
      if (data && data.m3u8) {
        const absoluteM3u8 = `https://admin.hellospz.cfd${data.m3u8}`;
        return Response.redirect(absoluteM3u8, 302);
      } else {
        return new Response('No m3u8 URL found in token response', { status: 404, headers: corsHeaders });
      }
    } catch (e) {
      return new Response('Error: ' + e.message, { status: 500, headers: corsHeaders });
    }
  }

  // 1. Route: /stream/:id
  const streamMatch = pathname.match(/^\/stream\/(\d+)(?:\/index\.m3u8)?$/);
  if (streamMatch) {
    const videoId = streamMatch[1];
    const okEmbedUrl = `https://ok.ru/videoembed/${videoId}`;

    try {
      console.log(`[Worker] Fetching OK embed: ${okEmbedUrl}`);
      const okRes = await fetch(okEmbedUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Referer': 'https://hellosports.rtps4bihar.com/'
        }
      });

      console.log(`[Worker] OK embed status: ${okRes.status}`);
      const body = await okRes.text();
      const targetMarker = 'hlsMasterPlaylistUrl';
      if (!body.includes(targetMarker)) {
        console.error(`[Worker] Marker "${targetMarker}" not found in embed HTML!`);
        return new Response(JSON.stringify({ error: "Could not find hlsMasterPlaylistUrl in page. Embed might be restricted or deleted." }), {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      const dataOptionsRegex = /data-options="([^"]+)"/;
      const match = body.match(dataOptionsRegex);
      if (!match) {
        console.error(`[Worker] data-options not found in HTML!`);
        return new Response(JSON.stringify({ error: "Could not extract data-options" }), {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
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
        console.error(`[Worker] masterPlaylistUrl not found in metadata!`);
        return new Response(JSON.stringify({ error: "Master playlist URL not found in metadata" }), {
          status: 500,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      console.log(`[Worker] Found Master Playlist URL: ${masterPlaylistUrl}`);

      // Fetch the master playlist
      const playlistRes = await fetch(masterPlaylistUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Referer': 'https://ok.ru/'
        }
      });
      console.log(`[Worker] Playlist fetch status: ${playlistRes.status}`);
      const playlistBody = await playlistRes.text();
      console.log(`[Worker] Playlist body length: ${playlistBody.length}`);

      const baseUrl = `${url.protocol}//${url.host}/proxy`;
      const lines = playlistBody.split(/\r?\n/);
      const rewrittenLines = lines.map(line => {
        const trimmed = line.trim();
        if (trimmed === '' || trimmed.startsWith('#')) {
          return line;
        }

        // Construct absolute URL
        const absoluteUrl = new URL(trimmed, masterPlaylistUrl).href;
        const parsed = new URL(absoluteUrl);
        const cleanProto = parsed.protocol.replace(':', '');
        const rest = absoluteUrl.substring(parsed.protocol.length + 2);
        return `${baseUrl}/${cleanProto}/${rest}`;
      });

      const rewritten = rewrittenLines.join('\n');
      return new Response(rewritten, {
        headers: {
          ...corsHeaders,
          'Content-Type': 'application/vnd.apple.mpegurl'
        }
      });

    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }

  // 2. Route: /proxy/:protocol/:domain/:path...
  const proxyMatch = pathname.match(/^\/proxy\/(https?)\/([^\/]+)\/(.+)$/);
  if (proxyMatch) {
    const protocol = proxyMatch[1];
    const domain = proxyMatch[2];
    const pathAndQuery = proxyMatch[3] + url.search;
    const targetUrl = `${protocol}://${domain}/${pathAndQuery}`;

    const requestHeaders = new Headers();
    if (request.headers.get('Range')) {
      requestHeaders.set('Range', request.headers.get('Range'));
    }
    requestHeaders.set('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    requestHeaders.set('Referer', 'https://ok.ru/');

    try {
      const proxyRes = await fetch(targetUrl, {
        headers: requestHeaders
      });

      const contentType = proxyRes.headers.get('content-type') || '';
      const isPlaylist = targetUrl.split('?')[0].endsWith('.m3u8') || contentType.includes('mpegurl');

      const responseHeaders = new Headers(corsHeaders);
      responseHeaders.set('Content-Type', contentType || (isPlaylist ? 'application/vnd.apple.mpegurl' : 'application/octet-stream'));

      if (proxyRes.headers.get('content-range')) {
        responseHeaders.set('Content-Range', proxyRes.headers.get('content-range'));
      }
      if (proxyRes.headers.get('content-length')) {
        responseHeaders.set('Content-Length', proxyRes.headers.get('content-length'));
      }
      if (proxyRes.headers.get('accept-ranges')) {
        responseHeaders.set('Accept-Ranges', proxyRes.headers.get('accept-ranges'));
      }

      if (isPlaylist) {
        const playlistBody = await proxyRes.text();
        const baseUrl = `${url.protocol}//${url.host}/proxy`;

        const rewritten = playlistBody.replace(/(https?:\/\/)([^\s\r\n]+)/g, (m, proto, rest) => {
          const cleanProto = proto.replace('://', '');
          return `${baseUrl}/${cleanProto}/${rest}`;
        });

        return new Response(rewritten, {
          status: proxyRes.status,
          headers: responseHeaders
        });
      } else {
        // Stream binary content directly
        return new Response(proxyRes.body, {
          status: proxyRes.status,
          headers: responseHeaders
        });
      }

    } catch (e) {
      return new Response('Proxy Error: ' + e.message, {
        status: 500,
        headers: corsHeaders
      });
    }
  }

  // Homepage fallback
  return new Response(`
    <h1>OK.ru Cloudflare Stream Proxy</h1>
    <p>Usage: <code>/stream/[videoId]</code></p>
  `, {
    headers: { 'Content-Type': 'text/html' }
  });
}
