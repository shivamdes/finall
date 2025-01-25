from flask import Flask, render_template, request
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
from openai import OpenAI
import os
import logging
import re
from serverless_http import serverless

app = Flask(__name__, template_folder="../templates", static_folder="../static")
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default-secret-key')
API_KEY = os.getenv('OPENAI_API_KEY')

# Configure logging
logging.basicConfig(level=logging.INFO)
app.logger.addHandler(logging.StreamHandler())

def extract_video_id(url):
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})",
        r"youtu.be\/([0-9A-Za-z_-]{11})",
        r"embed\/([0-9A-Za-z_-]{11})",
        r"shorts\/([0-9A-Za-z_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match and len(match.group(1)) == 11:
            return match.group(1)
    return None

def get_youtube_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=['en', 'es', 'fr'],
            preserve_formatting=True
        )
        return ' '.join([entry['text'] for entry in transcript])
    except TranscriptsDisabled:
        return "error:transcripts-disabled"
    except NoTranscriptFound:
        return "error:no-transcript-found"
    except Exception as e:
        app.logger.error(f"Transcript Error: {str(e)}")
        return f"error:unknown-{str(e)}"

def format_transcript(transcript):
    try:
        if not API_KEY:
            return "error:no-api-key"
            
        client = OpenAI(api_key=API_KEY, timeout=30)
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {
                    "role": "system",
                    "content": "Format transcript with proper paragraphs and punctuation. Preserve original wording exactly. No markdown."
                },
                {
                    "role": "user", 
                    "content": f"Format this transcript:\n\n{transcript[:15000]}"
                }
            ],
            temperature=0.5,
            max_tokens=3000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        app.logger.error(f"OpenAI Error: {str(e)}")
        return f"error:openai-{str(e)}"

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        if not url:
            return render_template('index.html', error="Please enter a YouTube URL")
        
        video_id = extract_video_id(url)
        if not video_id:
            return render_template('index.html', error="Invalid YouTube URL format")
        
        raw_transcript = get_youtube_transcript(video_id)
        
        if raw_transcript.startswith("error:"):
            error_type = raw_transcript.split(":")[1]
            messages = {
                "transcripts-disabled": "Subtitles are disabled for this video",
                "no-transcript-found": "No transcript available for this video",
                "unknown": "Failed to retrieve transcript"
            }
            return render_template('index.html', error=messages.get(error_type, "Transcript error"))
        
        formatted = format_transcript(raw_transcript)
        
        if formatted.startswith("error:"):
            error_type = formatted.split(":")[1]
            messages = {
                "no-api-key": "OpenAI API key not configured",
                "openai": "Failed to process transcript",
                "unknown": "Formatting failed"
            }
            return render_template('index.html', error=messages.get(error_type, "Processing error"))

        return render_template('result.html', 
                             transcript=formatted,
                             video_id=video_id)
    
    return render_template('index.html')

handler = serverless(app)
