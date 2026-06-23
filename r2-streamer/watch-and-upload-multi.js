const fs = require('fs');
const path = require('path');
const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');

// Cloudflare R2 Credentials
const R2_ACCOUNT_ID = '613d51ec4093f97108f44dc4bfaaf47d';
const R2_ACCESS_KEY_ID = '12c1ff6dfe253603cf04f5937cef216e';
const R2_SECRET_ACCESS_KEY = 'eba4ff360c23dd636a8f0f360cbe12a41b631faf823d6263e34b88cb81843a16';
const R2_BUCKET = 'zeta-stream';

// Initialize S3 client
const s3Client = new S3Client({
  endpoint: `https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
  credentials: {
    accessKeyId: R2_ACCESS_KEY_ID,
    secretAccessKey: R2_SECRET_ACCESS_KEY,
  },
  region: 'auto',
});

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
console.log(` DIRECT CLOUDFLARE R2 WATCHER & UPLOADER`);
console.log(` Watching folder: ${WATCH_DIR}`);
console.log(` Target Bucket: ${R2_BUCKET}`);
console.log(`===================================================`);

const uploadQueue = new Set();

async function uploadFile(relativePath) {
  // Normalize Windows slashes to forward slashes for R2 keys
  const targetPath = relativePath.replace(/\\/g, '/');
  const filePath = path.join(WATCH_DIR, relativePath);
  
  if (!fs.existsSync(filePath)) return;

  // Prevent duplicate concurrent uploads for the same file path
  if (uploadQueue.has(targetPath)) return;
  uploadQueue.add(targetPath);

  try {
    let fileBuffer;
    let contentType = 'application/octet-stream';

    // If it's the master playlist, fix the Windows backslash issue locally before uploading
    if (relativePath === 'live.m3u8') {
      let content = fs.readFileSync(filePath, 'utf8');
      content = content.replace(/\\/g, '/'); // Convert \ to /
      fileBuffer = Buffer.from(content, 'utf8');
      contentType = 'application/vnd.apple.mpegurl';
    } else if (relativePath.endsWith('.m3u8')) {
      fileBuffer = fs.readFileSync(filePath);
      contentType = 'application/vnd.apple.mpegurl';
    } else if (relativePath.endsWith('.ts')) {
      fileBuffer = fs.readFileSync(filePath);
      contentType = 'video/MP2T';
    } else {
      fileBuffer = fs.readFileSync(filePath);
    }

    const cacheControl = relativePath.endsWith('.ts') 
      ? 'public, max-age=3600' 
      : 'public, max-age=0, s-maxage=3, must-revalidate';

    const command = new PutObjectCommand({
      Bucket: R2_BUCKET,
      Key: `live/${targetPath}`,
      Body: fileBuffer,
      ContentType: contentType,
      CacheControl: cacheControl
    });

    await s3Client.send(command);
    console.log(`Uploaded successfully to R2: live/${targetPath}`);
    
    // Delete local .ts file after successful upload to save disk space
    if (targetPath.endsWith('.ts')) {
      fs.unlink(filePath, (err) => {
        if (err) console.error(`Error deleting local file ${targetPath}:`, err.message);
      });
    }
  } catch (err) {
    console.error(`Error uploading ${targetPath} to R2:`, err.message);
  } finally {
    uploadQueue.delete(targetPath);
  }
}

// Watch directory recursively for file changes
fs.watch(WATCH_DIR, { recursive: true }, (eventType, filename) => {
  if (!filename) return;
  
  // Only upload stream playlists and video segments
  if (filename.endsWith('.m3u8') || filename.endsWith('.ts')) {
    // 50ms trigger to ensure file writing is finished
    setTimeout(() => uploadFile(filename), 50);
  }
});
