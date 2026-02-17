import asyncio
import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from DB.storage import redis_client

load_dotenv()

POLL_INTERVAL = 0.5
SILENCE_THRESHOLD = 4.0
P1_DELIVERY_TARGET = 30
P2P3_DELIVERY_TARGET = 90
EXPIRATION_TIME = 120
CONSILIENCE_SPOKE_EXPIRATION = 30

last_delivery_times = {}

def redis_conversation_state_get(session_id):
    try:
        state_json = redis_client.get(f'conversation_state:{session_id}')
        if state_json:
            return json.loads(state_json)
        return None
    except Exception as e:
        print(f"Error getting conversation state: {e}")
        return None

def relevance_check(item, current_keywords):
    if not current_keywords:
        return True
    
    item_keywords = item.get('keywords', [])
    
    if not item_keywords:
        return True
    
    item_set = set(item_keywords)
    current_set = set(current_keywords)
    
    overlap = len(item_set.intersection(current_set))
    
    if overlap > 0:
        return True
    
    print(f"Item no longer relevant (topics changed)")
    return False

def overdue_check(item, priority):
    try:
        created_at = datetime.fromisoformat(item['timestamp']).timestamp()
        elapsed = time.time() - created_at
        
        if priority == 'P1':
            return elapsed > P1_DELIVERY_TARGET
        elif priority in ['P2', 'P3']:
            return elapsed > P2P3_DELIVERY_TARGET
        
        return False
    except Exception as e:
        print(f"Error checking overdue: {e}")
        return False

def redis_consilience_spoke_write(session_id, message_number):
    try:
        flag_data = {
            'timestamp': time.time(),
            'message_number': message_number or int(time.time() * 1000)
        }
        
        redis_client.set(
            f'consilience_spoke:{session_id}',
            json.dumps(flag_data),
            ex=CONSILIENCE_SPOKE_EXPIRATION
        )
        
        print(f"Set consilience_spoke flag (expires in {CONSILIENCE_SPOKE_EXPIRATION}s)")
        
    except Exception as e:
        print(f"Error setting consilience_spoke flag: {e}")

def deliverable_next_get(session_id, silence_detected, current_keywords, time_since_last):
    global last_delivery_times
    
    last_delivery = last_delivery_times.get(session_id, 0)
    
    p0_item = redis_client.rpop(f'response_queue:{session_id}:P0')
    if p0_item:
        item = json.loads(p0_item)
        print(f"P0 (immediate): {item['response_text'][:60]}...")
        return item, 'P0'
    
    if not silence_detected:
        return None, None
    
    if time.time() - last_delivery < SILENCE_THRESHOLD:
        return None, None
    
    for priority in ['P1', 'P2', 'P3']:
        queue_key = f'response_queue:{session_id}:{priority}'
        queue_length = redis_client.llen(queue_key)
        
        for i in range(queue_length):
            item_json = redis_client.lindex(queue_key, i)
            if not item_json:
                continue
            
            item = json.loads(item_json)
            
            try:
                created_at = datetime.fromisoformat(item['timestamp']).timestamp()
                if time.time() - created_at > EXPIRATION_TIME:
                    redis_client.lrem(queue_key, 1, item_json)
                    print(f"Removed expired {priority} item")
                    continue
            except:
                pass
            
            if not relevance_check(item, current_keywords):
                redis_client.lrem(queue_key, 1, item_json)
                print(f"Removed irrelevant {priority} item")
                continue
            
            overdue = overdue_check(item, priority)
            
            if overdue:
                print(f"{priority} item overdue, delivering now")
                redis_client.lrem(queue_key, 1, item_json)
                return item, priority
            
            if priority == 'P1':
                try:
                    created_at = datetime.fromisoformat(item['timestamp']).timestamp()
                    elapsed = time.time() - created_at
                    if elapsed > P1_DELIVERY_TARGET * 0.7:
                        redis_client.lrem(queue_key, 1, item_json)
                        return item, priority
                except:
                    pass
            
            redis_client.lrem(queue_key, 1, item_json)
            return item, priority
    
    return None, None

async def monitor_and_deliver(session_id):
    global last_delivery_times
    
    print(f"Delivery Monitor started for session: {session_id}")
    print(f"Silence threshold: {SILENCE_THRESHOLD}s")
    print(f"P1 delivery target: {P1_DELIVERY_TARGET}s")
    print(f"P2/P3 delivery target: {P2P3_DELIVERY_TARGET}s")
    print(f"Item expiration: {EXPIRATION_TIME}s")
    print(f"Follow-up window: {CONSILIENCE_SPOKE_EXPIRATION}s\n")
    
    if session_id not in last_delivery_times:
        last_delivery_times[session_id] = 0
    
    while True:
        try:
            state = redis_conversation_state_get(session_id)
            
            if not state:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            
            silence_detected = state.get('silence', False)
            current_keywords = state.get('current_keywords', [])
            time_since_last = state.get('time_since_last_message', 0)
            
            item, priority = deliverable_next_get(
                session_id,
                silence_detected, 
                current_keywords,
                time_since_last
            )
            
            if item:
                print("\n" + "="*70)
                print(f"DELIVERING {priority} RESPONSE")
                print("="*70)
                
                response_text = item['response_text']
                print(f"Response:\n{response_text}")
                print("="*70 + "\n")
                
                message_number = item.get('trigger_info', {}).get('message_number')
                redis_consilience_spoke_write(session_id, message_number)
                
                last_delivery_times[session_id] = time.time()
            
            await asyncio.sleep(POLL_INTERVAL)
            
        except Exception as e:
            print(f"Error in delivery monitor: {e}")
            await asyncio.sleep(POLL_INTERVAL)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python delivery_monitor.py <session_id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    
    print("="*70)
    print("DELIVERY MONITOR")
    print("="*70)
    print(f"Session: {session_id}")
    print(f"P0: Immediate delivery")
    print(f"P1: During silence, within 30s target")
    print(f"P2/P3: During silence, within 90s target")
    print(f"Relevance checking: keyword overlap")
    print(f"One item per silence window")
    print("="*70 + "\n")
    
    await monitor_and_deliver(session_id)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping Delivery Monitor")