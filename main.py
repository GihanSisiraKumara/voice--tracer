from flask import Flask, request, jsonify
import speech_recognition as sr
import requests
import tempfile
import os
from pydub import AudioSegment
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# Initialize Firebase Admin SDK
# Option 1: Direct path (replace with your actual path)
cred = credentials.Certificate("./keys/serviceAccountKey.json")

# Option 2: Using environment variable (uncomment to use)
# from dotenv import load_dotenv
# import os
# load_dotenv()
# cred = credentials.Certificate(os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY'))

firebase_admin.initialize_app(cred)
db = firestore.client()

def download_audio_file(audio_url):
    """Download audio file from URL to temporary file"""
    response = requests.get(audio_url)
    response.raise_for_status()
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.aac') as temp_file:
        temp_file.write(response.content)
        return temp_file.name

def convert_audio_to_wav(input_path):
    """Convert audio file to WAV format for better speech recognition"""
    try:
        # Load audio file
        audio = AudioSegment.from_file(input_path)
        
        # Convert to WAV
        output_path = input_path.replace('.aac', '.wav')
        audio.export(output_path, format='wav', parameters=['-ar', '16000', '-ac', '1'])
        
        return output_path
    except Exception as e:
        print(f"Error converting audio: {e}")
        return input_path

def transcribe_audio(audio_path):
    """Transcribe audio file to text using Google Speech Recognition"""
    recognizer = sr.Recognizer()
    
    try:
        # Convert to WAV first for better compatibility
        wav_path = convert_audio_to_wav(audio_path)
        
        with sr.AudioFile(wav_path) as source:
            # Adjust for ambient noise
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # Record the audio
            audio_data = recognizer.record(source)
            
        # Transcribe using Google Speech Recognition (free tier)
        text = recognizer.recognize_google(audio_data)
        return text
        
    except sr.UnknownValueError:
        return "Could not understand the audio"
    except sr.RequestError as e:
        return f"Could not request results from speech recognition service: {e}"
    except Exception as e:
        return f"Error during transcription: {e}"

def save_to_firestore(transcription, audio_url):
    """Save transcription to Firestore database"""
    try:
        doc_ref = db.collection('voice_transcriptions').document()
        doc_ref.set({
            'transcription': transcription,
            'audio_url': audio_url,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'treatment_page': 'Treatment Eight',
            'processed_by': 'python_backend'
        })
        return doc_ref.id
    except Exception as e:
        print(f"Error saving to Firestore: {e}")
        raise

@app.route('/transcribe', methods=['POST'])
def transcribe_endpoint():
    """Main endpoint for transcribing audio"""
    try:
        # Get audio URL from request
        data = request.get_json()
        audio_url = data.get('audio_url')
        
        if not audio_url:
            return jsonify({'error': 'No audio URL provided'}), 400
        
        print(f"Processing audio from URL: {audio_url}")
        
        # Download audio file
        temp_audio_path = download_audio_file(audio_url)
        
        try:
            # Convert to WAV for better recognition
            wav_path = convert_audio_to_wav(temp_audio_path)
            
            # Transcribe audio
            transcription = transcribe_audio(wav_path)
            
            print(f"Transcription result: {transcription}")
            
            # Save to Firestore (optional - since Flutter also saves)
            firestore_doc_id = save_to_firestore(transcription, audio_url)
            
            return jsonify({
                'transcription': transcription,
                'status': 'success',
                'firestore_doc_id': firestore_doc_id
            })
            
        finally:
            # Clean up temporary files
            if os.path.exists(temp_audio_path):
                os.unlink(temp_audio_path)
            if 'wav_path' in locals() and os.path.exists(wav_path):
                os.unlink(wav_path)
                
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'speech-to-text'})

if __name__ == '__main__':
    # Install required packages:
    # pip install flask speechrecognition pydub requests firebase-admin
    # You'll also need to install system dependencies:
    # - For Ubuntu/Debian: sudo apt-get install portaudio19-dev python3-pyaudio flac
    # - For macOS: brew install portaudio flac
    
    app.run(host='0.0.0.0', port=5000, debug=True)