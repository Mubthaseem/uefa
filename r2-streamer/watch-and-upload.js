const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');

const BUCKET_NAME = 'my-live-stream'; // Name of your R2 bucket
const WATCH_DIR = path.join(__dirname, 'hls_out');

// Ensure watch directory exists
if (!fs.existsSync(WATCH_DIR)) {
  fs.mkdirSync(WATCH_DIR);
}

console.log(`===================================================`);
console.log(` R2 LIVE STREAM WATCHER RUNNING`);
console.log(` Watching folder: ${WATCH_DIR}`);
console.log(` Targets R2 Bucket: ${BUCKET_NAME}`);
console.log(`===================================================`);

const uploadQueue = new Set();

function uploadToR2(filename) {
  const filePath = path.join(WATCH_DIR, filename);
  if (!fs.existsSync(filePath)) return;

  // Prevent duplicate concurrent uploads
  if (uploadQueue.has(filename)) return;
  uploadQueue.add(filename);

  const command = `npx wrangler r2 object put ${BUCKET_NAME}/${filename} --file="${filePath}"`;
  
  exec(command, (err, stdout, stderr) => {
    uploadQueue.delete(filename);
    if (err) {
      console.error(`Error uploading ${filename}:`, stderr || err.message);
    } else {
      console.log(`Uploaded: ${filename}`);
    }
  });
}

// Watch directory for file changes
fs.watch(WATCH_DIR, (eventType, filename) => {
  if (!filename) return;
  
  // Only upload stream playlist and video segments
  if (filename.endsWith('.m3u8') || filename.endsWith('.ts')) {
    // Small delay to ensure file write is finished
    setTimeout(() => uploadToR2(filename), 100);
  }
});
