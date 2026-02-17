import json
import os
from dotenv import load_dotenv
from datetime import datetime
import assemblyai as aai
from assemblyai.streaming.v3 import (
    BeginEvent,
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    StreamingParameters,
    TerminationEvent,
    TurnEvent,
)

load_dotenv()

ASSEMBLY_AI_KEY = os.getenv('ASSEMBLYAI_API_KEY') or os.getenv('ASSEMBLY_AI_KEY')

SAMPLE_RATE = 16000

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

def start_stream():
    if not ASSEMBLY_AI_KEY:
        raise RuntimeError("Set ASSEMBLYAI_API_KEY in your environment")

    client = StreamingClient(StreamingClientOptions(api_key=ASSEMBLY_AI_KEY))

    def on_begin(client: StreamingClient, event: BeginEvent):
        print(f"Session ID: {event.id}")

    def on_turn(client: StreamingClient, event: TurnEvent):
        payload = event.model_dump()

        # Only handle final turns
        if not payload.get('end_of_turn', False):
            return

        # Check for utterances first, then words, then flat transcript
        utterances = payload.get('utterances') or []
        if utterances:
            for utt in utterances:
                speaker = utt.get('speaker', 'Unknown')
                text = utt.get('text', '') or ''
                ts = utt.get('start') or get_timestamp()
                conf = utt.get('confidence', 0.0) or 0.0
                write_to_memory(speaker, text, ts, conf)
            return

        words = payload.get('words') or []
        if words:
            process_words(words)
            return

        text = payload.get('transcript') or ''
        if text:
            write_to_memory('Unknown', text, get_timestamp(), 0.0)

    def on_term(client: StreamingClient, event: TerminationEvent):
        print(f"Session terminated: {event.audio_duration_seconds}s processed")

    def on_error(client: StreamingClient, error: StreamingError):
        print(f"Error: {error}")

    client.on(StreamingEvents.Begin, on_begin)
    client.on(StreamingEvents.Turn, on_turn)
    client.on(StreamingEvents.Termination, on_term)
    client.on(StreamingEvents.Error, on_error)

    print("Starting audio stream...")
    print("Speak now.")

    client.connect(
        StreamingParameters(
            sample_rate=SAMPLE_RATE,
            formatted_finals=True,
            format_turns=True,
        )
    )

    mic_stream = aai.extras.MicrophoneStream(sample_rate=SAMPLE_RATE)
    client.stream(mic_stream)
    client.disconnect()

def process_words(words):
    current_speaker = None
    current_text = []
    current_start = None
    
    for word in words:
        speaker = word.get('speaker', 'Unknown')
        word_text = word.get('text', '')
        start_time = word.get('start', 0)
        
        if speaker != current_speaker:
            if current_text:
                full_text = ' '.join(current_text)
                write_to_memory(current_speaker, full_text, current_start, 0.9)
            
            current_speaker = speaker
            current_text = [word_text]
            current_start = start_time
        else:
            current_text.append(word_text)
    
    if current_text:
        full_text = ' '.join(current_text)
        write_to_memory(current_speaker, full_text, current_start, 0.9)

def save_conversation():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(conversation_memory, f, indent=2)
    
    print(f"\nConversation saved to {filename}")
    print(f"Total messages: {len(conversation_memory)}")

if __name__ == "__main__":
    try:
        start_stream()
    except KeyboardInterrupt:
        print("\nStopping stream.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        save_conversation()
        print("Done")