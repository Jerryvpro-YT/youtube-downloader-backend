from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import re
import io
import tempfile

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return jsonify({"status": "YouTube Downloader API is running!", "version": "1.0"})

@app.route("/api/video-info", methods=['POST'])
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
            
            # Get available formats
            formats = []
            for f in info.get('formats', []):
                if f.get('height') and f.get('ext') in ['mp4', 'webm']:
                    formats.append({
                        'quality': f"{f.get('height')}p",
                        'format': f.get('ext'),
                        'format_id': f.get('format_id')
                    })
            
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
    """Start a video download"""
    data = request.json
    url = data.get('url')
    quality = data.get('quality', '720p')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, '%(title)s.%(ext)s')
        
        is_audio_only = (quality == 'Audio Only')
        
        ydl_opts = {
            'outtmpl': output_path,
            'nocolor': True,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': True,
        }
        
        if is_audio_only:
            # Audio only - MP3
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            # Video - Try different format approaches
            quality_map = {
                '1080p': 1080,
                '720p': 720,
                '480p': 480,
                '360p': 360
            }
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
            
            # Find the downloaded file
            base_filename = ydl.prepare_filename(info)
            
            # Check for different extensions
            extensions = ['.mp4', '.webm', '.mkv', '.mp3', '.m4a']
            file_path = None
            
            for ext in extensions:
                test_path = base_filename.replace('.%(ext)s', '').replace('.webm', '').replace('.mkv', '') + ext
                if os.path.exists(test_path):
                    file_path = test_path
                    break
            
            if not file_path:
                # Search in temp directory
                for f in os.listdir(temp_dir):
                    if f.endswith(('.mp4', '.webm', '.mkv', '.mp3', '.m4a')):
                        file_path = os.path.join(temp_dir, f)
                        break
            
            if file_path and os.path.exists(file_path):
                # Read file
                with open(file_path, 'rb') as f:
                    file_data = f.read()
                
                # Clean up
                import shutil
                shutil.rmtree(temp_dir)
                
                # Determine file extension
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