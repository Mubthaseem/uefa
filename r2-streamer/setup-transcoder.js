const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ffmpegDir = path.join(__dirname, 'bin');
const ffmpegExe = path.join(ffmpegDir, 'ffmpeg.exe');

console.log("==============================================");
console.log(" MULTI-QUALITY STREAM SETUP");
console.log("==============================================");

// 1. Install node-media-server
console.log("Installing node-media-server...");
try {
  execSync('npm install node-media-server --no-audit --no-fund', { cwd: __dirname, stdio: 'inherit' });
  console.log("✓ node-media-server installed successfully.");
} catch (e) {
  console.error("✗ Failed to install node-media-server:", e.message);
  process.exit(1);
}

// 2. Download portable FFmpeg if not present
if (!fs.existsSync(ffmpegExe)) {
  if (!fs.existsSync(ffmpegDir)) {
    fs.mkdirSync(ffmpegDir);
  }
  
  console.log("Downloading portable FFmpeg (Gyand Essentials)...");
  const zipPath = path.join(ffmpegDir, 'ffmpeg.zip');
  
  // gyand ffmpeg build url
  const url = "https://github.com/GyanD/codexffmpeg/releases/download/7.0.1/ffmpeg-7.0.1-essentials_build.zip";
  
  try {
    // Download using PowerShell
    console.log("Downloading zip archive...");
    execSync(`powershell -Command "Invoke-WebRequest -Uri '${url}' -OutFile '${zipPath}'"`, { stdio: 'inherit' });
    
    console.log("Extracting archive...");
    // Extract using PowerShell
    execSync(`powershell -Command "Expand-Archive -Path '${zipPath}' -DestinationPath '${ffmpegDir}' -Force"`, { stdio: 'inherit' });
    
    // Find ffmpeg.exe in the extracted folder and move it to the bin folder
    const extractedFolders = fs.readdirSync(ffmpegDir).filter(f => f.startsWith('ffmpeg-'));
    if (extractedFolders.length > 0) {
      const srcExe = path.join(ffmpegDir, extractedFolders[0], 'bin', 'ffmpeg.exe');
      if (fs.existsSync(srcExe)) {
        fs.renameSync(srcExe, ffmpegExe);
        console.log("✓ FFmpeg binary extracted successfully.");
      }
    }
    
    // Cleanup zip and extra folder
    fs.unlinkSync(zipPath);
    if (extractedFolders.length > 0) {
      fs.rmSync(path.join(ffmpegDir, extractedFolders[0]), { recursive: true, force: true });
    }
    
  } catch (e) {
    console.error("✗ Failed to download/extract FFmpeg:", e.message);
    process.exit(1);
  }
} else {
  console.log("✓ FFmpeg binary already exists in bin folder.");
}

console.log("==============================================");
console.log(" Setup Complete! Ready to stream.");
console.log("==============================================");
