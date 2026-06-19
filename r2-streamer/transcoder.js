const NodeMediaServer = require('node-media-server');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const WATCH_DIR = path.join(__dirname, 'hls_out');
const FFMPEG_PATH = path.join(__dirname, 'bin', 'ffmpeg.exe');

// Ensure watch directories exist
const folders = ['', '0', '1', '2']; // 0=1080p, 1=720p, 2=360p
for (const folder of folders) {
  const dir = path.join(WATCH_DIR, folder);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

// RTMP Server Configuration
const config = {
  rtmp: {
    port: 1935,
    chunk_size: 60000,
    gop_cache: true,
    ping: 30,
    ping_timeout: 60
  }
};

const nms = new NodeMediaServer(config);
nms.run();

let ffmpegProcess = null;

function handlePublish(id, streamPath) {
  if (!streamPath) {
    console.log(`[Transcoder] Ignoring publish with empty streamPath`);
    return;
  }

  const cleanPath = streamPath.replace(/^\//, ''); // Remove leading slash
  console.log(`[Transcoder] Checking stream path: "${cleanPath}"`);
  
  if (cleanPath !== 'live/mystream') {
    console.log(`[Transcoder] Path "${cleanPath}" does not match "live/mystream". Ignoring.`);
    return;
  }

  if (ffmpegProcess) {
    console.log(`[Transcoder] Stream updated, but FFmpeg is already transcoding.`);
    return;
  }

  console.log(`===================================================`);
  console.log(` SUCCESS: RTMP Stream Detected!`);
  console.log(` Starting NVENC Transcoder for: ${streamPath}`);
  console.log(`===================================================`);

  cleanHlsFolder();

  const ffmpegArgs = [
    '-y',
    '-i', 'rtmp://127.0.0.1/live/mystream',
    '-filter_complex', '[0:v]split=3[v1][v2][v3]; [v1]scale=1920:1080[v1out]; [v2]scale=1280:720[v2out]; [v3]scale=640:360[v3out]',
    
    // 1080p stream
    '-map', '[v1out]', '-c:v:0', 'h264_nvenc', '-b:v:0', '3500k', '-preset', 'p1', '-tune', 'ull', '-g', '150', '-keyint_min', '150', '-sc_threshold', '0',
    '-map', '0:a', '-c:a:0', 'aac', '-b:a:0', '128k',
    
    // 720p stream
    '-map', '[v2out]', '-c:v:1', 'h264_nvenc', '-b:v:1', '1800k', '-preset', 'p1', '-tune', 'ull', '-g', '150', '-keyint_min', '150', '-sc_threshold', '0',
    '-map', '0:a', '-c:a:1', 'aac', '-b:a:1', '128k',
    
    // 360p stream
    '-map', '[v3out]', '-c:v:2', 'h264_nvenc', '-b:v:2', '800k', '-preset', 'p1', '-tune', 'ull', '-g', '150', '-keyint_min', '150', '-sc_threshold', '0',
    '-map', '0:a', '-c:a:2', 'aac', '-b:a:2', '128k',
    
    // HLS output configuration
    '-f', 'hls',
    '-hls_time', '5',
    '-hls_list_size', '3',
    '-hls_flags', 'delete_segments',
    '-var_stream_map', 'v:0,a:0 v:1,a:1 v:2,a:2',
    '-master_pl_name', 'live.m3u8',
    '-hls_segment_filename', path.join(WATCH_DIR, '%v', 'index%d.ts'),
    path.join(WATCH_DIR, '%v', 'index.m3u8')
  ];

  ffmpegProcess = spawn(FFMPEG_PATH, ffmpegArgs);

  ffmpegProcess.stdout.on('data', (data) => console.log(`[FFmpeg] ${data}`));
  ffmpegProcess.stderr.on('data', (data) => {
    const msg = data.toString();
    if (msg.includes('frame=') || msg.includes('speed=')) {
      process.stdout.write(`\r[Transcoding] ${msg.trim().substring(0, 80)}`);
    } else {
      console.log(`[FFmpeg Log] ${msg.trim()}`);
    }
  });

  ffmpegProcess.on('close', (code) => {
    console.log(`\nFFmpeg process exited with code ${code}`);
    ffmpegProcess = null;
  });
}

// Hook into prePublish and postPublish using session parameters
nms.on('prePublish', (id, StreamPath, args) => {
  const session = StreamPath;
  console.log(`[Event Log] prePublish triggered for ID: ${id}`);
  if (session && session.streamApp && session.streamName) {
    const constructedPath = `/${session.streamApp}/${session.streamName}`;
    console.log(`[Event Log] Detected streamPath: "${constructedPath}"`);
    handlePublish(id, constructedPath);
  } else {
    console.log(`[Event Log] session parameters missing or undefined`);
  }
});

nms.on('postPublish', (id, StreamPath, args) => {
  const session = StreamPath;
  console.log(`[Event Log] postPublish triggered for ID: ${id}`);
  if (session && session.streamApp && session.streamName) {
    const constructedPath = `/${session.streamApp}/${session.streamName}`;
    console.log(`[Event Log] Detected streamPath: "${constructedPath}"`);
    handlePublish(id, constructedPath);
  } else {
    console.log(`[Event Log] session parameters missing or undefined`);
  }
});

// Listen to stream disconnect
nms.on('donePublish', (id, StreamPath, args) => {
  const session = StreamPath;
  if (!session || !session.streamApp || !session.streamName) return;
  
  const constructedPath = `/${session.streamApp}/${session.streamName}`;
  const cleanPath = constructedPath.replace(/^\//, '');
  if (cleanPath !== 'live/mystream') return;
  
  console.log(`Stream disconnected. Stopping transcoder...`);
  if (ffmpegProcess) {
    ffmpegProcess.kill('SIGINT');
    ffmpegProcess = null;
  }
});

function cleanHlsFolder() {
  console.log("Cleaning old temporary streaming files...");
  for (const folder of folders) {
    const dir = path.join(WATCH_DIR, folder);
    if (fs.existsSync(dir)) {
      const files = fs.readdirSync(dir);
      for (const file of files) {
        if (file.endsWith('.ts') || file.endsWith('.m3u8')) {
          try {
            fs.unlinkSync(path.join(dir, file));
          } catch (_) {}
        }
      }
    }
  }
}
