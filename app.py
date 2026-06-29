from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
import threading
import uuid
import time
import shutil

app = Flask(__name__)
CORS(app)  # This allows your frontend to talk to this backend

# Store download progress for each job
download_jobs = {}

# ============================================================
# ROUTE 1: GET VIDEO INFORMATION
# ============================================================

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Get video information without downloading"""
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            duration = info.get('duration', 0)
            mins = duration // 60
            secs = duration % 60
            
            return jsonify({
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': duration,
                'duration_formatted': f"{mins}:{secs:02d}",
                'formats': [
                    {'quality': '1080p', 'format': 'mp4'},
                    {'quality': '720p', 'format': 'mp4'},
                    {'quality': '480p', 'format': 'mp4'},
                    {'quality': '360p', 'format': 'mp4'},
                    {'quality': 'Audio Only', 'format': 'mp3'}
                ]
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ============================================================
# ROUTE 2: START DOWNLOAD
# ============================================================

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start a video download"""
    data = request.json
    url = data.get('url')
    quality = data.get('quality', '720p')
    output_path = data.get('output_path', 'downloads')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    # Generate a unique job ID
    job_id = str(uuid.uuid4())
    
    # Initialize job status
    download_jobs[job_id] = {
        'status': 'starting',
        'progress': 0,
        'speed': '0 KB/s',
        'eta': 'N/A',
        'file_path': None,
        'error': None
    }
    
    # Start download in background thread
    thread = threading.Thread(
        target=download_video,
        args=(job_id, url, quality, output_path)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id, 'status': 'started'})

# ============================================================
# ROUTE 3: CHECK DOWNLOAD STATUS
# ============================================================

@app.route('/api/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """Check download progress"""
    status = download_jobs.get(job_id, {'status': 'not_found'})
    return jsonify(status)

# ============================================================
# ROUTE 4: DOWNLOAD THE FILE
# ============================================================

@app.route('/api/download-file/<job_id>', methods=['GET'])
def download_file(job_id):
    """Download the completed file"""
    job = download_jobs.get(job_id)
    if not job or job.get('status') != 'completed':
        return jsonify({'error': 'File not ready'}), 404
    
    file_path = job.get('file_path')
    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

# ============================================================
# DOWNLOAD FUNCTION (Runs in background)
# ============================================================

def download_video(job_id, url, quality, output_path):
    """Background download function"""
    try:
        # Create downloads folder if it doesn't exist
        os.makedirs(output_path, exist_ok=True)
        
        print(f"🎬 Starting download job: {job_id}")
        print(f"📹 URL: {url}")
        print(f"📁 Output: {output_path}")
        
        # ============================================================
        # DETERMINE IF AUDIO ONLY
        # ============================================================
        
        is_audio_only = (quality == 'Audio Only')
        
        # ============================================================
        # BASE YT-DLP OPTIONS
        # ============================================================
        
        ydl_opts = {
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
            'progress_hooks': [lambda d: progress_hook(d, job_id)],
            'nocolor': True,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': True,
        }
        
        # ============================================================
        # AUDIO ONLY SETTINGS
        # ============================================================
        
        if is_audio_only:
            print("🎵 Downloading audio only...")
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        
        # ============================================================
        # VIDEO SETTINGS
        # ============================================================
        
        else:
            quality_map = {
                '1080p': 1080,
                '720p': 720,
                '480p': 480,
                '360p': 360
            }
            
            height = quality_map.get(quality, 720)
            print(f"📹 Downloading video up to {height}p...")
            
            ydl_opts.update({
                'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                'merge_output_format': 'mp4',
                'postprocessor_args': {
                    'ffmpeg': [
                        '-c:v', 'libx264',
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart',
                    ]
                },
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
                'format_sort': ['res', 'codec:avc', 'codec:aac'],
            })
        
        # ============================================================
        # START DOWNLOAD
        # ============================================================
        
        print("⏳ Downloading...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Find the downloaded file
            base_filename = ydl.prepare_filename(info)
            file_path = None
            
            if is_audio_only:
                # Audio file
                possible_paths = [
                    base_filename.replace('.webm', '.mp3').replace('.m4a', '.mp3'),
                    base_filename,
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        file_path = path
                        break
                
                # If not found, search directory
                if not file_path:
                    for f in os.listdir(output_path):
                        if f.endswith('.mp3') and info.get('title', '') in f:
                            file_path = os.path.join(output_path, f)
                            break
            else:
                # Video file
                file_path = base_filename.replace('.webm', '.mp4').replace('.mkv', '.mp4')
                
                # If not found, search directory
                if not os.path.exists(file_path):
                    for f in os.listdir(output_path):
                        if f.endswith('.mp4') and info.get('title', '') in f:
                            file_path = os.path.join(output_path, f)
                            break
            
            # Update job with file path
            if file_path and os.path.exists(file_path):
                download_jobs[job_id]['file_path'] = file_path
                download_jobs[job_id]['status'] = 'completed'
                download_jobs[job_id]['progress'] = 100
                print(f"✅ Download complete! File: {file_path}")
            else:
                raise Exception("Could not find downloaded file")
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Download error: {error_msg}")
        download_jobs[job_id]['status'] = 'error'
        download_jobs[job_id]['error'] = error_msg

# ============================================================
# PROGRESS HOOK (Called by yt-dlp during download)
# ============================================================

def progress_hook(d, job_id):
    """Update progress during download"""
    try:
        if d['status'] == 'downloading':
            # Extract progress info
            progress_str = d.get('_percent_str', '0%')
            speed_str = d.get('_speed_str', 'N/A')
            eta_str = d.get('_eta_str', 'N/A')
            
            # Clean up ANSI escape codes
            progress = float(re.sub(r'\x1b\[[0-9;]*m', '', progress_str).strip('%'))
            speed = re.sub(r'\x1b\[[0-9;]*m', '', speed_str).strip()
            eta = re.sub(r'\x1b\[[0-9;]*m', '', eta_str).strip()
            
            # Update job status
            download_jobs[job_id].update({
                'progress': progress,
                'speed': speed,
                'eta': eta
            })
            
            # Print to terminal
            print(f"\r📥 Progress: {progress:.1f}% | Speed: {speed} | ETA: {eta}", end='')
            
        elif d['status'] == 'finished':
            print(f"\n✅ Download finished for job {job_id}!")
            download_jobs[job_id]['progress'] = 95
            
        elif d['status'] == 'error':
            print(f"\n❌ Download error for job {job_id}!")
            
    except Exception as e:
        print(f"Progress hook error: {e}")

# ============================================================
# FOR PYTHONANYWHERE / RENDER.COM DEPLOYMENT
# ============================================================

# This is what the hosting platform looks for
application = app

# ============================================================
# RUN LOCAL SERVER (Only when you run python app.py)
# ============================================================

if __name__ == '__main__':
    # Create downloads folder
    os.makedirs('downloads', exist_ok=True)
    
    print("=" * 60)
    print("🎬 YouTube Downloader Backend")
    print("=" * 60)
    print(f"📁 Download folder: downloads/")
    print(f"🌐 Server running on: http://localhost:5000")
    print(f"📡 API endpoint: http://localhost:5000/api")
    print("=" * 60)
    print("Press CTRL+C to stop the server")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)