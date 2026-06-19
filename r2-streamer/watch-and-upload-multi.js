const fs = require('fs');
const path = require('path');

const UPLOAD_URL = 'https://mubthaseem-zeta-stream.hf.space/upload';
const WATCH_DIR = path.join(__dirname, 'hls_out');

// Ensure watch directory exists
if (!fs.existsSync(WATCH_DIR)) {
  fs.mkdirSync(WATCH_DIR);
}

// Clean old files from the directory on startup recursively
console.log("Cleaning old temporary files from watch folder...");
const folders = ['', '0', '1', '2'];
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

console.log(`===================================================`);
console.log(` HUGGING FACE / CLOUDFLARE MULTI-QUALITY WATCHER`);
console.log(` Watching folder: ${WATCH_DIR}`);
console.log(` Upload URL: ${UPLOAD_URL}`);
console.log(`===================================================`);

const uploadQueue = new Set();

async function uploadFile(relativePath) {
  // Normalize Windows slashes to forward slashes for the server header
  const targetPath = relativePath.replace(/\\/g, '/');
  const filePath = path.join(WATCH_DIR, relativePath);
  
  if (!fs.existsSync(filePath)) return;

  // Prevent duplicate concurrent uploads for the same file path
  if (uploadQueue.has(targetPath)) return;
  uploadQueue.add(targetPath);

  try {
    const fileBuffer = fs.readFileSync(filePath);

    const response = await fetch(UPLOAD_URL, {
      method: 'POST',
      headers: {
        'x-path': targetPath
      },
      body: fileBuffer
    });

    if (response.ok) {
      console.log(`Uploaded successfully: ${targetPath}`);
      
      // Delete local .ts file after successful upload to save disk space
      if (targetPath.endsWith('.ts')) {
        fs.unlink(filePath, (err) => {
          if (err) console.error(`Error deleting local file ${targetPath}:`, err.message);
        });
      }
    } else {
      console.error(`Failed to upload ${targetPath}. Status: ${response.status}`);
    }
  } catch (err) {
    console.error(`Error uploading ${targetPath}:`, err.message);
  } finally {
    uploadQueue.delete(targetPath);
  }
}

// Watch directory recursively for file changes (supported natively on Windows)
fs.watch(WATCH_DIR, { recursive: true }, (eventType, filename) => {
  if (!filename) return;
  
  // Only upload stream playlists and video segments
  if (filename.endsWith('.m3u8') || filename.endsWith('.ts')) {
    // 50ms trigger to ensure file writing is finished
    setTimeout(() => uploadFile(filename), 50);
  }
});
