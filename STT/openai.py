import asyncio
import websockets
import json
import base64
import pyaudio
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
CHANNELS = 1
FORMAT = pyaudio.paInt16

conversation_memory = []

def get_timestamp():
    return datetime.now().isoformat()

def write_to_memory(speaker_id, text, timestamp, confidence):
    entry = {
        'timestamp': timestamp,
        'speaker': speaker_id,
        'text': text,
        'confidence': confidence,
        'message_number': len(conversation_memory) + 1
    }
    conversation_memory.append(entry)
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
        encoded_audio = base64.b64encode(audio_data).decode('utf-8')
        
        audio_event = {
            "type": "input_audio_buffer.append",
            "audio": encoded_audio
        }
        
        await websocket.send(json.dumps(audio_event))
        await asyncio.sleep(0.01)

async def handle_server_events(websocket):
    async for message in websocket:
        event = json.loads(message)
        event_type = event.get('type', '')
        
        if event_type == 'session.created':
            print(f"Session created: {event.get('session', {}).get('id', 'unknown')}")
        
        elif event_type == 'input_audio_buffer.speech_started':
            print("Speech detected...")
        
        elif event_type == 'input_audio_buffer.speech_stopped':
            print("Speech ended, processing...")
        
        elif event_type == 'conversation.item.input_audio_transcription.completed':
            transcript = event.get('transcript', '')
            timestamp = get_timestamp()
            
            if transcript.strip():
                write_to_memory('User', transcript, timestamp, 1.0)
        
        elif event_type == 'conversation.item.input_audio_transcription.failed':
            error = event.get('error', {})
            print(f"Transcription failed: {error}")
        
        elif event_type == 'error':
            print(f"Error: {event.get('error', {})}")

async def start_openai_stream():
    if not OPENAI_API_KEY:
        raise RuntimeError("Set OPENAI_API_KEY in your environment")
    
    audio, stream = setup_audio()
    
    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    print("Connecting to OpenAI Realtime API...")
    
    async with websockets.connect(url, additional_headers=headers) as websocket:
        
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "You are a helpful assistant. Please transcribe what you hear.",
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "gpt-4o-transcribe"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.3,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 800
                }
            }
        }
        
        await websocket.send(json.dumps(session_update))
        print("Session configured for transcription")
        print("Start speaking.")
        
        await asyncio.gather(
            send_audio_data(websocket, stream),
            handle_server_events(websocket)
        )

def save_conversation():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"openai_conversation_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(conversation_memory, f, indent=2)
    
    print(f"\nConversation saved to {filename}")
    print(f"Total messages: {len(conversation_memory)}")

if __name__ == "__main__":
    try:
        asyncio.run(start_openai_stream())
    except KeyboardInterrupt:
        print("\nStopping stream...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        save_conversation()
        print("Done")