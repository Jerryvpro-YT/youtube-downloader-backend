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

# List of user agents to rotate
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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
        # Rotate user agent
        user_agent = random.choice(USER_AGENTS)
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'headers': {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            duration = info.get('duration', 0)
            mins = duration // 60
            secs = duration % 60
            
            formats = []
            for f in info.get('formats', []):
                if f.get('height') and f.get('ext') in ['mp4', 'webm']:
                    formats.append({
                        'quality': f"{f.get('height')}p",
                        'format': f.get('ext'),
                        'format_id': f.get('format_id')
                    })
            
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
        
        # Rotate user agent
        user_agent = random.choice(USER_AGENTS)
        
        ydl_opts = {
            'outtmpl': output_path,
            'nocolor': True,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': True,
            'headers': {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            },
            # Add YouTube specific options to avoid bot detection
            'extractor_args': {
                'youtube': {
                    'skip': ['hls', 'dash'],
                }
            }
        }
        
        if is_audio_only:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            quality_map = {'1080p': 1080, '720p': 720, '480p': 480, '360p': 360}
            height = quality_map.get(quality, 720)
            
            # Try multiple format approaches
            format_strings = [
                f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]',
                f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
                f'best[height<={height}]',
                'best'
            ]
            
            for fmt in format_strings:
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
            
            base_filename = ydl.prepare_filename(info)
            file_path = None
            
            for ext in ['.mp4', '.webm', '.mkv', '.mp3', '.m4a']:
                test_path = base_filename.replace('.%(ext)s', '').replace('.webm', '').replace('.mkv', '') + ext
                if os.path.exists(test_path):
                    file_path = test_path
                    break
            
            if not file_path:
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
                
                return send_file(
                    io.BytesIO(file_data),
                    as_attachment=True,
                    download_name=f"{info.get('title', 'video')}{ext}",
                    mimetype=content_type
                )
            else:
                return jsonify({'error': 'File not found after download'}), 404
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"status": 404, "message": "Not Found"}), 404

# For Vercel serverless
app = app