from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
import threading
import uuid
import time

app = Flask(__name__)
CORS(app)

# Store download progress for each job
download_jobs = {}

# ============================================================
# GET VIDEO INFO
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
# START DOWNLOAD
# ============================================================

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start a video download"""
    data = request.json
    url = data.get('url')
    quality = data.get('quality', '720p')
    output_path = data.get('output_path', 'D:/exe app')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    job_id = str(uuid.uuid4())
    
    download_jobs[job_id] = {
        'status': 'starting',
        'progress': 0,
        'speed': '0 KB/s',
        'eta': 'N/A',
        'file_path': None,
        'error': None
    }
    
    thread = threading.Thread(
        target=download_video,
        args=(job_id, url, quality, output_path)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({'job_id': job_id, 'status': 'started'})

# ============================================================
# CHECK STATUS
# ============================================================

@app.route('/api/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """Check download progress"""
    status = download_jobs.get(job_id, {'status': 'not_found'})
    return jsonify(status)

# ============================================================
# DOWNLOAD FILE
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
# DOWNLOAD VIDEO FUNCTION - FIXED FOR AAC AUDIO
# ============================================================

def download_video(job_id, url, quality, output_path):
    """Background download function - Forces AAC audio codec"""
    try:
        # Ensure output path exists
        os.makedirs(output_path, exist_ok=True)
        
        print(f"🎬 Starting download job: {job_id}")
        print(f"📹 URL: {url}")
        print(f"📁 Output: {output_path}")
        
        # ============================================================
        # QUALITY SETTINGS - FORCES AAC AUDIO
        # ============================================================
        
        is_audio_only = (quality == 'Audio Only')
        
        # Base options
        ydl_opts = {
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
            'progress_hooks': [lambda d: progress_hook(d, job_id)],
            'nocolor': True,
            'quiet': False,  # Set to False to see output
            'no_warnings': False,
            'ignoreerrors': True,
        }
        
        if is_audio_only:
            # ============================================================
            # AUDIO ONLY - MP3
            # ============================================================
            print("🎵 Downloading audio only...")
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            # ============================================================
            # VIDEO - MP4 with AAC AUDIO (FIXED)
            # ============================================================
            
            quality_map = {
                '1080p': 1080,
                '720p': 720,
                '480p': 480,
                '360p': 360
            }
            
            height = quality_map.get(quality, 720)
            print(f"📹 Downloading video up to {height}p with AAC audio...")
            
            # IMPORTANT: Force MP4 container with AAC audio
            ydl_opts.update({
                # Format: best video up to height + best audio, then merge
                'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                'merge_output_format': 'mp4',
                # Force audio codec to AAC during merge
                'postprocessor_args': {
                    'ffmpeg': [
                        '-c:v', 'libx264',      # Video codec: H.264
                        '-c:a', 'aac',           # Audio codec: AAC (universally supported)
                        '-b:a', '192k',          # Audio bitrate
                        '-pix_fmt', 'yuv420p',   # Compatible pixel format
                        '-movflags', '+faststart', # Web optimized
                    ]
                },
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
                # Force the final format
                'format_sort': ['res', 'codec:avc', 'codec:aac'],
            })
        
        # ============================================================
        # START DOWNLOAD
        # ============================================================
        
        print("⏳ Downloading...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Get the downloaded file path
            if is_audio_only:
                # Audio file
                base_filename = ydl.prepare_filename(info)
                file_path = base_filename.replace('.webm', '.mp3').replace('.m4a', '.mp3')
                
                # Search for the actual file
                if not os.path.exists(file_path):
                    for f in os.listdir(output_path):
                        if f.endswith('.mp3') and info.get('title', '') in f:
                            file_path = os.path.join(output_path, f)
                            break
            else:
                # Video file - look for MP4
                base_filename = ydl.prepare_filename(info)
                file_path = base_filename.replace('.webm', '.mp4').replace('.mkv', '.mp4')
                
                # Search for MP4 file if expected path doesn't exist
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
                print(f"✅ Download complete! File saved to: {file_path}")
            else:
                # Try to find any video file in the output directory
                for f in os.listdir(output_path):
                    if f.endswith(('.mp4', '.mkv', '.webm', '.mp3')):
                        file_path = os.path.join(output_path, f)
                        if os.path.getsize(file_path) > 1024 * 1024:  # > 1MB
                            download_jobs[job_id]['file_path'] = file_path
                            download_jobs[job_id]['status'] = 'completed'
                            download_jobs[job_id]['progress'] = 100
                            print(f"✅ Download complete! File saved to: {file_path}")
                            break
            
            # If still no file found, raise error
            if download_jobs[job_id].get('status') != 'completed':
                raise Exception("Could not find downloaded file")
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Download error: {error_msg}")
        download_jobs[job_id]['status'] = 'error'
        download_jobs[job_id]['error'] = error_msg

# ============================================================
# PROGRESS HOOK
# ============================================================

def progress_hook(d, job_id):
    """Update progress during download"""
    try:
        if d['status'] == 'downloading':
            progress_str = d.get('_percent_str', '0%')
            speed_str = d.get('_speed_str', 'N/A')
            eta_str = d.get('_eta_str', 'N/A')
            
            import re
            progress = float(re.sub(r'\x1b\[[0-9;]*m', '', progress_str).strip('%'))
            speed = re.sub(r'\x1b\[[0-9;]*m', '', speed_str).strip()
            eta = re.sub(r'\x1b\[[0-9;]*m', '', eta_str).strip()
            
            download_jobs[job_id].update({
                'progress': progress,
                'speed': speed,
                'eta': eta
            })
            
            # Print progress to terminal
            print(f"\r📥 Progress: {progress:.1f}% | Speed: {speed} | ETA: {eta}", end='')
            
        elif d['status'] == 'finished':
            print(f"\n✅ Download finished for job {job_id}!")
            download_jobs[job_id]['progress'] = 95
            
        elif d['status'] == 'error':
            print(f"\n❌ Download error for job {job_id}!")
            
    except Exception as e:
        print(f"Progress hook error: {e}")

# ============================================================
# RUN SERVER
# ============================================================

if __name__ == '__main__':
    # Create downloads folder if it doesn't exist
    os.makedirs('D:/exe app', exist_ok=True)
    print("=" * 60)
    print("🎬 YouTube Downloader Backend")
    print("=" * 60)
    print(f"📁 Download folder: D:/exe app")
    print(f"🌐 Server running on: http://localhost:5000")
    print(f"📡 API endpoint: http://localhost:5000/api")
    print("=" * 60)
    print("Press CTRL+C to stop the server")
    print("=" * 60)
    application = app