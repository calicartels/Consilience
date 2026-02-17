import asyncio
import json
import os
import sys
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from DB.storage import redis_client, get_messages_since

load_dotenv()

POLL_INTERVAL = 0.5
FOLLOW_UP_WINDOW = 30

client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

last_processed_message_numbers = {}
processed_message_ids = {}

CONSILIENCE_DETECTION_PROMPT = """You are monitoring a live academic conversation for when users address Consilience, an AI assistant.

IMPORTANT CONTEXT:
- This is spoken conversation transcribed by STT
- Expect typos, fragments, incomplete sentences
- "Consilience" may be misspelled: consoliance, consillience, consilient, consoliant, etc
- A standalone "consilience" is the user calling for attention

Your job: Detect if the user is ADDRESSING Consilience directly

Examples to FLAG as true:
- hey consilience how are you
- consilience (standalone, calling for attention)
- consilience what is rna
- and how does the dna work consilience (question ending with consilience)
- consoliance can you help
- yo Consilience
- consilient what do you think
- hey consoliant (misspelling)

Examples to FLAG as false:
- the consilience of knowledge (academic concept discussion)
- consilience is a theory about (discussing the theory)
- exploring consilience in science (abstract discussion)

Key rule: If "consilience" appears with a question or as standalone, FLAG as true

Message: "{text}"
Speaker: {speaker}

Respond with JSON only:
{{
  "is_addressing_consilience": true or false
}}"""

def context_builder_input(session_id, message):
    redis_client.lpush(
        f'context_builder:{session_id}:input',
        json.dumps(message)
    )

def follow_up_window_check(session_id):
    try:
        spoke_data = redis_client.get(f'consilience_spoke:{session_id}')
        if spoke_data:
            spoke_info = json.loads(spoke_data)
            time_since = time.time() - spoke_info['timestamp']
            if time_since < FOLLOW_UP_WINDOW:
                return True
        return False
    except Exception as e:
        print(f"Error checking follow-up window: {e}")
        return False

def orchestrator_signal_input(session_id, message_number, message, is_follow_up=False):
    signal = {
        'trigger_type': 'explicit_request',
        'message_number': message_number,
        'triggering_message': {
            'speaker': message.get('speaker', 'Unknown'),
            'text': message.get('text', ''),
            'timestamp': message.get('timestamp', '')
        }
    }
    
    if is_follow_up:
        signal['potential_follow_up'] = True
    
    redis_client.lpush(
        f'orchestrator_triggers:{session_id}',
        json.dumps(signal)
    )

async def consilience_detection(message):
    text = message.get('text', '')
    speaker = message.get('speaker', 'Unknown')
    
    if len(text.strip()) < 3:
        return False
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            max_completion_tokens=50,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": CONSILIENCE_DETECTION_PROMPT.format(text=text, speaker=speaker)
            }]
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get('is_addressing_consilience', False)
        
    except Exception as e:
        print(f"Error in consilience detection: {e}")
        return False

async def monitor_session(session_id):
    global last_processed_message_numbers, processed_message_ids
    
    print(f"Listener monitoring session {session_id}")
    print(f"Follow-up window: {FOLLOW_UP_WINDOW}s\n")
    
    if session_id not in last_processed_message_numbers:
        last_processed_message_numbers[session_id] = 0
    
    if session_id not in processed_message_ids:
        processed_message_ids[session_id] = set()
    
    while True:
        try:
            messages = get_messages_since(
                session_id,
                last_processed_message_numbers[session_id]
            )
            
            if messages:
                for message in messages:
                    message_number = message.get('message_number')
                    
                    if message_number in processed_message_ids[session_id]:
                        continue
                    
                    processed_message_ids[session_id].add(message_number)
                    
                    speaker = message.get('speaker', 'Unknown')
                    
                    if speaker == 'Consilience' or message.get('type') == 'consilience':
                        print(f"Skipping Consilience message {message_number}")
                        last_processed_message_numbers[session_id] = message_number
                        continue
                    
                    text = message.get('text', '')
                    print(f"New message {message_number}: {text[:50]}")
                    
                    context_builder_input(session_id, message)
                    
                    is_explicit_trigger = await consilience_detection(message)
                    in_follow_up_window = follow_up_window_check(session_id)
                    
                    if is_explicit_trigger or in_follow_up_window:
                        orchestrator_signal_input(session_id, message_number, message, is_follow_up=in_follow_up_window)
                        
                        if is_explicit_trigger and in_follow_up_window:
                            print(f"Explicit trigger in follow-up window, signal sent")
                        elif is_explicit_trigger:
                            print(f"Explicit trigger detected, signal sent")
                        else:
                            print(f"Follow-up window active, tagged as potential follow-up")
                    
                    last_processed_message_numbers[session_id] = message_number
            
            await asyncio.sleep(POLL_INTERVAL)
            
        except Exception as e:
            print(f"Error monitoring session: {e}")
            await asyncio.sleep(POLL_INTERVAL)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python listener.py <session_id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    
    await monitor_session(session_id)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping Listener")