from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
import io
import tempfile
import shutil
import random

app = Flask(__name__)
CORS(app)

# User agents to avoid bot detection
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
]

@app.route("/")
def home():
    return jsonify({"status": "YouTube Downloader API is running!", "version": "1.0"})

@app.route("/api/video-info", methods=['POST'])
def get_video_info():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'headers': {'User-Agent': random.choice(USER_AGENTS)},
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            duration = info.get('duration', 0)
            mins = duration // 60
            secs = duration % 60
            
            # Get ALL available formats
            formats = []
            seen_qualities = set()
            
            for f in info.get('formats', []):
                height = f.get('height')
                ext = f.get('ext')
                format_id = f.get('format_id')
                
                # Skip weird formats
                if not height or height < 144:
                    continue
                    
                quality_key = f"{height}p"
                if quality_key not in seen_qualities:
                    seen_qualities.add(quality_key)
                    formats.append({
                        'quality': quality_key,
                        'format': ext or 'mp4',
                        'format_id': format_id,
                        'height': height
                    })
            
            # Sort by height (descending)
            formats.sort(key=lambda x: x.get('height', 0), reverse=True)
            
            # Add audio only option
            formats.append({'quality': 'Audio Only', 'format': 'mp3', 'format_id': 'audio'})
            
            return jsonify({
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': duration,
                'duration_formatted': f"{mins}:{secs:02d}",
                'formats': formats
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/api/download", methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    quality = data.get('quality', '720p')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    try:
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, '%(title)s.%(ext)s')
        
        is_audio_only = (quality == 'Audio Only')
        
        # Extract the height from quality string (e.g., "720p" -> 720)
        try:
            target_height = int(quality.replace('p', ''))
        except:
            target_height = 720
        
        ydl_opts = {
            'outtmpl': output_path,
            'nocolor': True,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': True,
            'headers': {'User-Agent': random.choice(USER_AGENTS)},
        }
        
        if is_audio_only:
            # Audio only
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            # Try multiple format strategies - most flexible first
            format_strategies = [
                # Strategy 1: Best video with mp4 + best audio
                f'bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={target_height}][ext=mp4]',
                # Strategy 2: Best video up to target height + best audio
                f'bestvideo[height<={target_height}]+bestaudio/best[height<={target_height}]',
                # Strategy 3: Best overall up to target height
                f'best[height<={target_height}]',
                # Strategy 4: Best available (fallback)
                'best',
            ]
            
            # Try each strategy until one works
            for fmt in format_strategies:
                try:
                    ydl_opts.update({
                        'format': fmt,
                        'merge_output_format': 'mp4',
                    })
                    break
                except:
                    continue
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Find the downloaded file
            base_filename = ydl.prepare_filename(info)
            file_path = None
            
            # Check for different extensions
            for ext in ['.mp4', '.webm', '.mkv', '.mp3', '.m4a']:
                test_path = base_filename
                # Remove template placeholders
                test_path = re.sub(r'\.%(ext)s$', '', test_path)
                test_path = re.sub(r'\.%(title)s', '', test_path)
                # Try with extension
                test_path_alt = test_path + ext
                if os.path.exists(test_path_alt):
                    file_path = test_path_alt
                    break
            
            if not file_path:
                # Search in temp directory
                for f in os.listdir(temp_dir):
                    if f.endswith(('.mp4', '.webm', '.mkv', '.mp3', '.m4a')):
                        file_path = os.path.join(temp_dir, f)
                        break
            
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    file_data = f.read()
                
                shutil.rmtree(temp_dir)
                
                ext = os.path.splitext(file_path)[1]
                content_type = 'video/mp4' if ext in ['.mp4', '.webm', '.mkv'] else 'audio/mpeg'
                download_name = f"{re.sub(r'[<>:"/\\|?*]', '_', info.get('title', 'video'))}{ext}"
                
                return send_file(
                    io.BytesIO(file_data),
                    as_attachment=True,
                    download_name=download_name,
                    mimetype=content_type
                )
            else:
                return jsonify({'error': 'File not found after download'}), 404
                
    except Exception as e:
        error_msg = str(e)
        return jsonify({'error': error_msg}), 500

@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"status": 404, "message": "Not Found"}), 404

# For Vercel serverless
app = app