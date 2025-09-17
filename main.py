from flask import Flask, request, jsonify
import speech_recognition as sr
import requests
import tempfile
import os
import json
from pydub import AudioSegment
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Initialize Firebase Admin SDK
def initialize_firebase():
    """Initialize Firebase with environment variable or local file"""
    try:
        # Try to get Firebase key from environment variable (for production)
        firebase_key_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')
        
        if firebase_key_json:
            print("Using Firebase key from environment variable")
            # Parse JSON from environment variable
            key_dict = json.loads(firebase_key_json)
            
            # Create temporary file for the key
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                json.dump(key_dict, temp_file)
                temp_key_path = temp_file.name
            
            cred = credentials.Certificate(temp_key_path)
        else:
            # Fallback to local file for development
            print("Using local Firebase key file")
            local_key_path = "./keys/serviceAccountKey.json"
            if os.path.exists(local_key_path):
                cred = credentials.Certificate(local_key_path)
            else:
                raise FileNotFoundError("Firebase service account key not found")
        
        # Initialize Firebase app if not already initialized
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            print("Firebase initialized successfully")
        
        return firestore.client()
        
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        raise

# Initialize Firebase and get Firestore client
try:
    db = initialize_firebase()
except Exception as e:
    print(f"Failed to initialize Firebase: {e}")
    db = None

def download_audio_file(audio_url):
    """Download audio file from URL to temporary file"""
    try:
        print(f"Downloading audio from: {audio_url}")
        response = requests.get(audio_url, timeout=30)
        response.raise_for_status()
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.aac') as temp_file:
            temp_file.write(response.content)
            print(f"Audio downloaded to: {temp_file.name}")
            return temp_file.name
    except Exception as e:
        print(f"Error downloading audio: {e}")
        raise

def convert_audio_to_wav(input_path):
    """Convert audio file to WAV format for better speech recognition"""
    try:
        print(f"Converting audio file: {input_path}")
        # Load audio file
        audio = AudioSegment.from_file(input_path)
        
        # Convert to WAV with optimal settings for speech recognition
        output_path = input_path.replace('.aac', '.wav')
        audio = audio.set_frame_rate(16000).set_channels(1)  # Mono, 16kHz
        audio.export(output_path, format='wav')
        
        print(f"Audio converted to: {output_path}")
        return output_path
    except Exception as e:
        print(f"Error converting audio: {e}")
        # Return original path if conversion fails
        return input_path

def transcribe_audio(audio_path):
    """Transcribe audio file to text using Google Speech Recognition"""
    recognizer = sr.Recognizer()
    
    try:
        print(f"Transcribing audio: {audio_path}")
        
        # Convert to WAV first for better compatibility
        wav_path = convert_audio_to_wav(audio_path)
        
        with sr.AudioFile(wav_path) as source:
            # Adjust for ambient noise
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # Record the audio
            audio_data = recognizer.record(source)
            
        # Transcribe using Google Speech Recognition (free tier)
        text = recognizer.recognize_google(audio_data)
        print(f"Transcription successful: {text[:50]}..." if len(text) > 50 else f"Transcription: {text}")
        return text
        
    except sr.UnknownValueError:
        error_msg = "Could not understand the audio - please speak clearly"
        print(f"Transcription error: {error_msg}")
        return error_msg
    except sr.RequestError as e:
        error_msg = f"Could not request results from speech recognition service: {e}"
        print(f"Speech service error: {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Error during transcription: {e}"
        print(f"General transcription error: {error_msg}")
        return error_msg

def save_to_firestore(transcription, audio_url):
    """Save transcription to Firestore database"""
    if db is None:
        print("Firestore not available - skipping save")
        return None
        
    try:
        print("Saving transcription to Firestore")
        doc_ref = db.collection('voice_transcriptions').document()
        doc_ref.set({
            'transcription': transcription,
            'audio_url': audio_url,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'treatment_page': 'Treatment Eight',
            'processed_by': 'python_backend',
            'status': 'completed'
        })
        print(f"Saved to Firestore with ID: {doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        print(f"Error saving to Firestore: {e}")
        # Don't raise - continue without saving to Firestore
        return None

@app.route('/transcribe', methods=['POST'])
def transcribe_endpoint():
    """Main endpoint for transcribing audio"""
    temp_files = []  # Keep track of temp files to clean up
    
    try:
        # Get audio URL from request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        audio_url = data.get('audio_url')
        
        if not audio_url:
            return jsonify({'error': 'No audio URL provided'}), 400
        
        print(f"Processing transcription request for: {audio_url}")
        
        # Download audio file
        temp_audio_path = download_audio_file(audio_url)
        temp_files.append(temp_audio_path)
        
        # Convert to WAV for better recognition
        wav_path = convert_audio_to_wav(temp_audio_path)
        if wav_path != temp_audio_path:
            temp_files.append(wav_path)
        
        # Transcribe audio
        transcription = transcribe_audio(temp_audio_path)
        
        print(f"Transcription completed: {transcription[:100]}..." if len(transcription) > 100 else f"Transcription: {transcription}")
        
        # Save to Firestore (optional - don't fail if this fails)
        firestore_doc_id = save_to_firestore(transcription, audio_url)
        
        # Prepare response
        response_data = {
            'transcription': transcription,
            'status': 'success',
            'audio_url': audio_url
        }
        
        if firestore_doc_id:
            response_data['firestore_doc_id'] = firestore_doc_id
        
        return jsonify(response_data)
        
    except requests.RequestException as e:
        error_msg = f"Error downloading audio file: {e}"
        print(error_msg)
        return jsonify({'error': error_msg}), 400
        
    except Exception as e:
        error_msg = f"Error processing request: {e}"
        print(error_msg)
        return jsonify({'error': error_msg}), 500
        
    finally:
        # Clean up temporary files
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
                    print(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                print(f"Error cleaning up {temp_file}: {e}")

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check if Firebase is working
        firebase_status = "connected" if db is not None else "not connected"
        
        return jsonify({
            'status': 'healthy',
            'service': 'speech-to-text',
            'firebase': firebase_status,
            'python_version': f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
            'environment': 'production' if os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY') else 'development'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        'message': 'Flutter Voice Backend API',
        'version': '1.0.0',
        'endpoints': {
            'health': '/health - GET - Health check',
            'transcribe': '/transcribe - POST - Transcribe audio to text'
        },
        'usage': {
            'transcribe': {
                'method': 'POST',
                'content-type': 'application/json',
                'body': {'audio_url': 'https://example.com/audio.aac'},
                'response': {'transcription': 'transcribed text', 'status': 'success'}
            }
        }
    })

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Endpoint not found',
        'available_endpoints': ['/', '/health', '/transcribe']
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({
        'error': 'Internal server error',
        'message': 'Something went wrong on our end'
    }), 500

if __name__ == '__main__':
    # Configuration for different environments
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    print(f"Starting Flask app on port {port}")
    print(f"Debug mode: {debug_mode}")
    print(f"Environment: {'Production' if os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY') else 'Development'}")
    
    # Install required packages info
    print("\n" + "="*50)
    print("REQUIRED PACKAGES:")
    print("pip install Flask SpeechRecognition pydub requests firebase-admin python-dotenv gunicorn")
    print("\nSYSTEM DEPENDENCIES (for audio processing):")
    print("- FFmpeg (optional but recommended)")
    print("- PortAudio (for better audio handling)")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)