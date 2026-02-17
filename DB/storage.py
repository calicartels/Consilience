import redis
import json
import os
from datetime import datetime, timedelta
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_message(session_id, speaker, text, timestamp, confidence, message_number):
    message = {
        'session_id': session_id,
        'speaker': speaker,
        'text': text,
        'timestamp': timestamp,
        'confidence': confidence,
        'message_number': message_number
    }
    
    message_json = json.dumps(message)
    
    redis_client.zadd(
        f"session:{session_id}:messages",
        {message_json: message_number}
    )
    
    redis_client.lpush('db_write_queue', message_json)
    
    redis_client.expire(f"session:{session_id}:messages", 3600)
    
    return message

def get_next_message_number(session_id):
    """Get the next message number for a session"""
    messages = redis_client.zrange(
        f"session:{session_id}:messages",
        -1,
        -1,
        withscores=True
    )
    
    if messages:
        last_score = int(messages[0][1])
        return last_score + 1
    
    return 1

def get_recent_messages(session_id, minutes=5):
    """Get messages from last N minutes by filtering in memory"""
    all_messages = get_all_messages(session_id)
    
    cutoff_time = datetime.now() - timedelta(minutes=minutes)
    
    recent = []
    for msg in all_messages:
        msg_time = datetime.fromisoformat(msg['timestamp'])
        if msg_time >= cutoff_time:
            recent.append(msg)
    
    return recent

def get_all_messages(session_id):
    """Get all messages for a session"""
    messages_json = redis_client.zrange(
        f"session:{session_id}:messages",
        0,
        -1
    )
    
    messages = [json.loads(msg) for msg in messages_json]
    return messages

def get_messages_since(session_id, last_message_number):
    """Get messages after a specific message_number"""
    messages_json = redis_client.zrangebyscore(
        f"session:{session_id}:messages",
        last_message_number + 1,
        '+inf',
        withscores=True
    )
    
    messages = []
    for msg_json, score in messages_json:
        msg = json.loads(msg_json)
        msg['_score'] = score
        messages.append(msg)
    
    return messages

def background_worker():
    print("Background worker started, waiting for messages to write to Supabase")
    
    while True:
        batch_size = 10
        batch = []
        
        for _ in range(batch_size):
            result = redis_client.brpop('db_write_queue', timeout=1)
            if result:
                _, message_json = result
                batch.append(json.loads(message_json))
            else:
                break
        
        if batch:
            try:
                supabase.table('conversations').insert(batch).execute()
                print(f"Wrote {len(batch)} messages to Supabase")
            except Exception as e:
                print(f"Error writing to Supabase: {e}")
                for msg in batch:
                    redis_client.lpush('db_write_queue', json.dumps(msg))

if __name__ == "__main__":
    background_worker()