import asyncio
import websockets
import json
import pyaudio
import os
import sys
import uuid
from dotenv import load_dotenv
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from DB.storage import save_message

load_dotenv()

DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')

SAMPLE_RATE = 16000
CHUNK_SIZE = 1024
CHANNELS = 1
FORMAT = pyaudio.paInt16

SESSION_ID = None
message_counter = 0
last_stored_text = set()  # Track stored messages to avoid duplicates

def get_timestamp():
    return datetime.now().isoformat()

def write_to_storage(speaker_id, text, timestamp, confidence):
    global message_counter
    global last_stored_text

    key = f"{speaker_id}:{text}"
    if key in last_stored_text:
        return
    
    last_stored_text.add(key)
    message_counter += 1
    save_message(SESSION_ID, speaker_id, text, timestamp, confidence, message_counter)
    print(f"STORED: [{timestamp}] Speaker {speaker_id}: {text}")

def setup_audio():
    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE
    )
    return audio, stream

async def send_audio_data(websocket, stream):
    while True:
        audio_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
        await websocket.send(audio_data)
        await asyncio.sleep(0.01)

async def handle_responses(websocket):
    async for message in websocket:
        try:
            response = json.loads(message)
        except json.JSONDecodeError:
            continue

        msg_type = response.get('type')

        if msg_type == 'Metadata':
            request_id = response.get('request_id', 'unknown')
            print(f"Connected with request ID: {request_id}")
            continue

        if msg_type == 'SpeechStarted':
            print("Speech detected...")
            continue

        if msg_type != 'Results':
            continue

        channel = response.get('channel', {})
        alternatives = channel.get('alternatives', [])
        if not alternatives:
            continue

        alt0 = alternatives[0]
        confidence = alt0.get('confidence', 0.0)
        words = alt0.get('words', [])

        if words:
            process_words_with_speakers(words, confidence)
        else:
            transcript = (alt0.get('transcript') or '').strip()
            if transcript:
                write_to_storage('Unknown', transcript, get_timestamp(), confidence)

def process_words_with_speakers(words, confidence):
    current_speaker = None
    current_text = []
    current_start = None

    for word in words:
        speaker = word.get('speaker', None)
        word_text = word.get('word', '')
        start_time = word.get('start', 0)

        if speaker is not None:
            speaker_id = f"Speaker_{speaker}"
        else:
            speaker_id = 'Unknown'

        if speaker_id != current_speaker:
            if current_text:
                full_text = ' '.join(current_text)
                timestamp = get_timestamp()
                write_to_storage(current_speaker, full_text, timestamp, confidence)

            current_speaker = speaker_id
            current_text = [word_text]
            current_start = start_time
        else:
            current_text.append(word_text)

    if current_text:
        full_text = ' '.join(current_text)
        timestamp = get_timestamp()
        write_to_storage(current_speaker, full_text, timestamp, confidence)

async def start_deepgram_stream():
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("Set DEEPGRAM_API_KEY in your environment")

    audio, stream = setup_audio()

    params = {
        'encoding': 'linear16',
        'sample_rate': SAMPLE_RATE,
        'channels': CHANNELS,
        'language': 'en-US',
        'punctuate': 'true',
        'interim_results': 'false',
        'diarize': 'true',
        'smart_format': 'true',
        'endpointing': '100',
        'model': 'nova-3',
    }

    param_string = '&'.join([f"{key}={value}" for key, value in params.items()])
    url = f"wss://api.deepgram.com/v1/listen?{param_string}"

    headers = {
        'Authorization': f'Token {DEEPGRAM_API_KEY}'
    }

    print(f"Session ID: {SESSION_ID}")
    print("Connecting to Deepgram...")
    print("Start speaking...")

    async with websockets.connect(url, additional_headers=headers) as websocket:
        await asyncio.gather(
            send_audio_data(websocket, stream),
            handle_responses(websocket)
        )

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python deepgram.py <session_id>")
        print("\nFirst create a session:")
        print("  python DB/auth.py create <team_name> <password>")
        print("\nThen use the session_id:")
        print("  python STT/deepgram.py <session_id>")
        sys.exit(1)
    
    SESSION_ID = sys.argv[1]
    
    try:
        asyncio.run(start_deepgram_stream())
    except KeyboardInterrupt:
        print("\nStopping stream...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Done")
        print(f"Messages stored in Redis and queued for Supabase")
        print(f"Total messages: {message_counter}")