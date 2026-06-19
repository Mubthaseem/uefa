const fs = require('fs');
const path = require('path');

const UPLOAD_URL = 'https://mubthaseem-zeta-stream.hf.space/upload';
const WATCH_DIR = path.join(__dirname, 'hls_out');

// Ensure watch directory exists
if (!fs.existsSync(WATCH_DIR)) {
  fs.mkdirSync(WATCH_DIR);
}

// Clean old files from the directory on startup
console.log("Cleaning old temporary files from watch folder...");
const files = fs.readdirSync(WATCH_DIR);
for (const file of files) {
  if (file.endsWith('.ts') || file.endsWith('.m3u8')) {
    try {
      fs.unlinkSync(path.join(WATCH_DIR, file));
    } catch (e) {
      console.error(`Could not delete old file ${file}:`, e.message);
    }
  }
}

console.log(`===================================================`);
console.log(` HUGGING FACE / CLOUDFLARE LIVE WATCHER RUNNING`);
console.log(` Watching folder: ${WATCH_DIR}`);
console.log(` Upload URL: ${UPLOAD_URL}`);
console.log(`===================================================`);

const uploadQueue = new Set();

async function uploadFile(filename) {
  const filePath = path.join(WATCH_DIR, filename);
  if (!fs.existsSync(filePath)) return;

  // If it's a playlist, we rename the uploaded file to "live.m3u8"
  // so the player always has a single static URL to fetch.
  const targetFilename = filename.endsWith('.m3u8') ? 'live.m3u8' : filename;

  // Prevent duplicate concurrent uploads for the SAME target filename
  if (uploadQueue.has(targetFilename)) return;
  uploadQueue.add(targetFilename);

  try {
    const fileBuffer = fs.readFileSync(filePath);
    const blob = new Blob([fileBuffer]);
    const formData = new FormData();
    formData.append('file', blob, targetFilename);

    const response = await fetch(UPLOAD_URL, {
      method: 'POST',
      body: formData
    });

    if (response.ok) {
      console.log(`Uploaded successfully: ${filename} -> ${targetFilename}`);
      
      // Delete local .ts file after successful upload to save disk space
      if (filename.endsWith('.ts')) {
        fs.unlink(filePath, (err) => {
          if (err) console.error(`Error deleting local file ${filename}:`, err.message);
        });
      }
    } else {
      console.error(`Failed to upload ${filename}. Status: ${response.status}`);
    }
  } catch (err) {
    console.error(`Error uploading ${filename}:`, err.message);
  } finally {
    uploadQueue.delete(targetFilename);
  }
}

// Watch directory for file changes
fs.watch(WATCH_DIR, (eventType, filename) => {
  if (!filename) return;
  
  // Only upload stream playlist and video segments
  if (filename.endsWith('.m3u8') || filename.endsWith('.ts')) {
    // 50ms trigger for ultra-low latency uploads
    setTimeout(() => uploadFile(filename), 50);
  }
});
