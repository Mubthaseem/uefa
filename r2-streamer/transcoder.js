const NodeMediaServer = require('node-media-server');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const WATCH_DIR = path.join(__dirname, 'hls_out');
const FFMPEG_PATH = path.join(__dirname, 'bin', 'ffmpeg.exe');

// Load config.json from root directory (one level up)
let useNvidiaGpu = false;
let qualities = ['1080p', '720p', '360p'];
let maxFps = 0;
try {
  const configPath = path.join(__dirname, '..', 'config.json');
  if (fs.existsSync(configPath)) {
    const appConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    useNvidiaGpu = appConfig.USE_NVIDIA_GPU === true;
    if (Array.isArray(appConfig.QUALITIES) && appConfig.QUALITIES.length > 0) {
      qualities = appConfig.QUALITIES;
    }
    if (appConfig.MAX_FPS) {
      maxFps = parseInt(appConfig.MAX_FPS, 10);
    }
  }
} catch (e) {
  console.log('[Transcoder] Warning: Could not read config.json, defaulting to CPU encoding.');
}

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
  if (!streamPath) return;

  const cleanPath = streamPath.replace(/^\//, ''); // Remove leading slash
  if (cleanPath !== 'live/mystream') {
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
  const streamId = Math.floor(Date.now() / 1000);

  const videoEncoder = useNvidiaGpu ? 'h264_nvenc' : 'libx264';
  const encoderFlags = useNvidiaGpu 
    ? ['-preset', 'p1', '-tune', 'ull'] 
    : ['-preset', 'veryfast', '-tune', 'zerolatency'];

  // Dynamically compile qualities
  let activeQualities = qualities;
  if (!activeQualities || activeQualities.length === 0) {
    activeQualities = ['360p']; // fallback to safe default
  }

  const needs1080 = activeQualities.includes('1080p');
  const needs720 = activeQualities.includes('720p');
  const needs360 = activeQualities.includes('360p');

  // Dynamic filter complex configuration
  let filterComplex = '';
  if (needs720 && needs360) {
    filterComplex = '[0:v]split=2[v2][v3]; [v2]scale=1280:720[v2out]; [v3]scale=640:360[v3out]';
  } else if (needs720 && needs1080) {
    filterComplex = '[0:v]scale=1280:720[v2out]';
  } else if (needs360 && needs1080) {
    filterComplex = '[0:v]scale=640:360[v3out]';
  } else if (needs720) {
    filterComplex = '[0:v]scale=1280:720[v2out]';
  } else if (needs360) {
    filterComplex = '[0:v]scale=640:360[v3out]';
  }

  const ffmpegArgs = [
    '-y',
    '-i', 'rtmp://127.0.0.1/live/mystream'
  ];

  if (filterComplex) {
    ffmpegArgs.push('-filter_complex', filterComplex);
  }

  let streamIndex = 0;
  const varStreamMap = [];

  const fpsArgs = maxFps ? ['-r', maxFps.toString()] : [];
  const gopSize = maxFps ? (maxFps * 2).toString() : '60';

  if (needs1080) {
    ffmpegArgs.push(
      '-map', '0:v', `-c:v:${streamIndex}`, videoEncoder, ...encoderFlags, `-b:v:${streamIndex}`, '3500k', ...fpsArgs, '-g', gopSize, '-keyint_min', gopSize, '-sc_threshold', '0',
      '-map', '0:a', `-c:a:${streamIndex}`, 'aac', `-b:a:${streamIndex}`, '128k'
    );
    varStreamMap.push(`v:${streamIndex},a:${streamIndex}`);
    streamIndex++;
  }

  if (needs720) {
    const videoInput = filterComplex.includes('[v2out]') ? '[v2out]' : '0:v';
    ffmpegArgs.push(
      '-map', videoInput, `-c:v:${streamIndex}`, videoEncoder, ...encoderFlags, `-b:v:${streamIndex}`, '1800k', ...fpsArgs, '-g', gopSize, '-keyint_min', gopSize, '-sc_threshold', '0',
      '-map', '0:a', `-c:a:${streamIndex}`, 'aac', `-b:a:${streamIndex}`, '128k'
    );
    varStreamMap.push(`v:${streamIndex},a:${streamIndex}`);
    streamIndex++;
  }

  if (needs360) {
    const videoInput = filterComplex.includes('[v3out]') ? '[v3out]' : '0:v';
    ffmpegArgs.push(
      '-map', videoInput, `-c:v:${streamIndex}`, videoEncoder, ...encoderFlags, `-b:v:${streamIndex}`, '800k', ...fpsArgs, '-g', gopSize, '-keyint_min', gopSize, '-sc_threshold', '0',
      '-map', '0:a', `-c:a:${streamIndex}`, 'aac', `-b:a:${streamIndex}`, '128k'
    );
    varStreamMap.push(`v:${streamIndex},a:${streamIndex}`);
    streamIndex++;
  }

  // HLS output configuration for low-latency (2s segments, 6 segments playlist)
  ffmpegArgs.push(
    '-f', 'hls',
    '-hls_time', '2',
    '-hls_list_size', '6',
    '-hls_flags', 'delete_segments+temp_file',
    '-var_stream_map', varStreamMap.join(' '),
    '-master_pl_name', 'live.m3u8',
    '-hls_segment_filename', path.join(WATCH_DIR, '%v', `seg_${streamId}_%d.ts`),
    path.join(WATCH_DIR, '%v', 'index.m3u8')
  );

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
nms.on('prePublish', (session) => {
  console.log(`[Event Log] prePublish triggered`);
  if (session && session.streamApp && session.streamName) {
    const constructedPath = `/${session.streamApp}/${session.streamName}`;
    console.log(`[Event Log] Detected streamPath: "${constructedPath}"`);
    handlePublish(session.id || 'publisher', constructedPath);
  } else {
    console.log(`[Event Log] session parameters missing or undefined`);
  }
});

nms.on('postPublish', (session) => {
  console.log(`[Event Log] postPublish triggered`);
  if (session && session.streamApp && session.streamName) {
    const constructedPath = `/${session.streamApp}/${session.streamName}`;
    console.log(`[Event Log] Detected streamPath: "${constructedPath}"`);
    handlePublish(session.id || 'publisher', constructedPath);
  } else {
    console.log(`[Event Log] session parameters missing or undefined`);
  }
});

// Listen to stream disconnect
nms.on('donePublish', (session) => {
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
