import asyncio
import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from DB.storage import redis_client, supabase

load_dotenv()

POLL_INTERVAL = 0.5
RAW_BUFFER_TIME_WINDOW = 120
RAW_BUFFER_MIN_MESSAGES = 15
DOMAIN_INFERENCE_INTERVAL = 5
DOMAIN_INFERENCE_TIME_INTERVAL = 30
SILENCE_THRESHOLD = 4.0

client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

session_contexts = {}

SUMMARIZATION_PROMPT = """You are maintaining a rolling summary of an academic research conversation.

PREVIOUS SUMMARY:
{previous_summary}

NEW MESSAGES TO ADD:
{new_messages}

TASK: Update the summary to incorporate the new messages. Maintain chronological flow and preserve key points from both the previous summary and new messages.

Guidelines:
- Keep the summary concise but informative
- Highlight main topics, findings, and interdisciplinary connections
- Note any Consilience interventions and their topics
- Preserve speaker attributions for important claims
- Maintain academic tone

Generate ONLY the updated summary text (no preamble, no JSON):
"""

DOMAIN_INFERENCE_PROMPT = """Analyze this conversation and identify which academic disciplines are being discussed.

RECENT CONVERSATION:
{messages}

Identify ALL disciplines that are relevant to this conversation. Do not limit the number.

Common disciplines include (but not limited to):
- Computer Science / Software Engineering
- Biology / Life Sciences
- Psychology / Cognitive Science
- Business / Economics / Management
- Design / User Experience
- Physics / Astronomy
- Chemistry / Biochemistry
- Mathematics / Statistics
- Social Sciences / Sociology / Anthropology
- Medicine / Health Sciences / Neuroscience
- Engineering (Mechanical, Electrical, Civil, etc.)
- Environmental Science / Ecology
- Political Science / Law
- Philosophy / Ethics
- History / Humanities
- Linguistics / Communication
- Data Science / Machine Learning
- Robotics / Automation

Respond with JSON only:
{{
  "active_domains": ["domain1", "domain2", ...],
  "confidence_scores": {{"domain1": 0.9, "domain2": 0.7, ...}},
  "topic_keywords": ["keyword1", "keyword2", ...]
}}"""

KEYWORD_EXTRACTION_PROMPT = """Extract the key concepts and important terms from this message.

MESSAGE:
{text}

Return 5-10 meaningful keywords that capture the main concepts being discussed.
Focus on: technical terms, domain-specific vocabulary, key concepts, named entities, compound terms.
Ignore: common words, filler words, pronouns.

Examples:
- "machine learning algorithm" → keep as compound term
- "DNA replication" → keep as compound term
- "user experience design" → keep as compound term

Respond with JSON only:
{{
  "keywords": ["keyword1", "keyword2", ...]
}}"""

class ConversationContext:
    def __init__(self, session_id):
        self.session_id = session_id
        self.rolling_summary = {
            'text': '',
            'covers_messages': [0, 0],
            'message_count': 0,
            'time_range_start': None,
            'time_range_end': None,
            'last_updated': None
        }
        self.raw_recent_buffer = []
        self.consilience_responses = []
        self.last_summary_time = time.time()
        self.messages_since_summary = 0
        
        self.last_message_time = time.time()
        self.messages_since_domain_inference = 0
        self.last_domain_inference_time = time.time()
        self.current_domains = []
        self.domain_confidence = {}
        self.current_keywords = []
    
    def update_message_time(self):
        """Update last message timestamp for silence detection"""
        self.last_message_time = time.time()
    
    def is_silence(self):
        """Check if silence threshold exceeded"""
        return time.time() - self.last_message_time > SILENCE_THRESHOLD
    
    def time_since_last_message(self):
        """Get seconds since last message"""
        return time.time() - self.last_message_time
    
    async def extract_keywords(self, text):
        """
        Extract keywords from message using LLM
        
        Parameter choices:
        - model: gpt-4o-mini - Fast and cheap for keyword extraction
        - temperature: 0.2 - Low for consistent extraction
        - max_tokens: 100 - Just need a list of keywords
        """
        if not text or len(text) < 10:
            return []
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                max_completion_tokens=100,
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": KEYWORD_EXTRACTION_PROMPT.format(text=text)
                }]
            )
            
            result = json.loads(response.choices[0].message.content)
            keywords = result.get('keywords', [])
            
            print(f"Keywords: {keywords}")
            return keywords
            
        except Exception as e:
            print(f"Error extracting keywords: {e}")
            words = text.lower().split()
            return [w for w in words if len(w) > 4][:5]
    
    async def add_message(self, message):
        """Add user message to raw recent buffer"""
        speaker = message.get('speaker', 'Unknown')
        
        # Consilience messages handled separately
        if speaker == 'Consilience' or message.get('type') == 'consilience':
            await self.add_consilience_response(message)
            return
        
        keywords = await self.extract_keywords(message.get('text', ''))
        
        message_obj = {
            'message_number': message.get('message_number'),
            'speaker': speaker,
            'text': message.get('text', ''),
            'timestamp': message.get('timestamp'),
            'buffer_entry_time': time.time(),
            'confidence': message.get('confidence', 1.0),
            'type': 'user',
            'keywords': keywords,
            'domains': [],
            'domain_confidence': {}
        }
        
        self.raw_recent_buffer.append(message_obj)
        
        print(f"Message {message_obj['message_number']} added to buffer (size: {len(self.raw_recent_buffer)})")
        
        self.messages_since_summary += 1
        self.messages_since_domain_inference += 1
        self.update_message_time()
    
    async def add_consilience_response(self, response):
        """Add Consilience response to tracking and buffer"""
        keywords = await self.extract_keywords(response.get('text', ''))
        
        # Store in consilience_responses history
        consilience_record = {
            'message_number': response.get('message_number'),
            'speaker': 'Consilience',
            'text': response.get('text', ''),
            'timestamp': response.get('timestamp'),
            'type': 'consilience',
            'metadata': response.get('metadata', {})
        }
        self.consilience_responses.append(consilience_record)
        
        # Also add to raw buffer for context
        buffer_record = {
            'message_number': response.get('message_number'),
            'speaker': 'Consilience',
            'text': response.get('text', ''),
            'timestamp': response.get('timestamp'),
            'buffer_entry_time': time.time(),
            'type': 'consilience',
            'keywords': keywords,
            'domains': [],
            'domain_confidence': {}
        }
        self.raw_recent_buffer.append(buffer_record)
        
        print(f"Consilience response {response.get('message_number')} stored (history: {len(self.consilience_responses)})")
        
        self.messages_since_summary += 1
        self.messages_since_domain_inference += 1  # FIXED: Now counts toward domain inference
        self.update_message_time()
    
    def should_infer_domains(self):
        """Check if it's time to infer domains"""
        messages_threshold = self.messages_since_domain_inference >= DOMAIN_INFERENCE_INTERVAL
        time_threshold = (time.time() - self.last_domain_inference_time) >= DOMAIN_INFERENCE_TIME_INTERVAL
        has_messages = len(self.raw_recent_buffer) > 0
        
        return has_messages and (messages_threshold or time_threshold)
    
    async def infer_domains(self):
        """
        Use LLM to infer domains from recent conversation
        
        Parameter choices:
        - model: gpt-4o-mini - Fast and cost-effective for classification
        - temperature: 0.2 - Low temperature for consistent classification
        - max_tokens: 400 - Sufficient for JSON with multiple domains
        """
        if not self.raw_recent_buffer:
            return
        
        print(f"Inferring domains")
        
        messages_text = '\n'.join([
            f"{msg['speaker']}: {msg['text']}"
            for msg in self.raw_recent_buffer[-10:]
        ])
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                max_completion_tokens=400,
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": DOMAIN_INFERENCE_PROMPT.format(messages=messages_text)
                }]
            )
            
            result = json.loads(response.choices[0].message.content)
            
            self.current_domains = result.get('active_domains', [])
            self.domain_confidence = result.get('confidence_scores', {})
            self.current_keywords = result.get('topic_keywords', [])
            
            print(f"Domains: {self.current_domains}")
            print(f"Topic keywords: {self.current_keywords}")
            
            # Tag messages in buffer with domain metadata
            tagged_count = 0
            for msg in self.raw_recent_buffer:
                if not msg.get('domains'):
                    msg['domains'] = self.current_domains
                    msg['domain_confidence'] = self.domain_confidence
                    tagged_count += 1
            
            print(f"Tagged {tagged_count} messages with domain metadata")
            
            self.messages_since_domain_inference = 0
            self.last_domain_inference_time = time.time()
            
        except Exception as e:
            print(f"Error inferring domains: {e}")
    
    def should_summarize(self):
        """Check if it's time to summarize based on time window only"""
        if not self.raw_recent_buffer:
            return False
        
        current_time = time.time()
        oldest_buffer_entry = self.raw_recent_buffer[0]['buffer_entry_time']
        time_span = current_time - oldest_buffer_entry
        
        time_exceeded = time_span >= RAW_BUFFER_TIME_WINDOW
        
        if time_exceeded:
            buffer_size = len(self.raw_recent_buffer)
            print(f"Summarization triggered: {time_span:.0f}s elapsed, {buffer_size} messages in buffer")
        
        return time_exceeded
    
    async def update_summary(self):
        """
        Generate updated rolling summary using LLM
        
        Parameter choices:
        - model: gpt-4o - Most capable model for maintaining coherent summaries
        - temperature: 0.3 - Lower temperature for consistent, focused summaries
        - max_tokens: 1000 - Sufficient for comprehensive summary without being too long
        """
        if not self.raw_recent_buffer:
            return
        
        print(f"Generating summary for {len(self.raw_recent_buffer)} messages")
        
        new_messages_text = '\n'.join([
            f"[{msg['timestamp']}] {msg['speaker']}: {msg['text']}"
            for msg in self.raw_recent_buffer
        ])
        
        previous_summary = self.rolling_summary['text'] if self.rolling_summary['text'] else "This is the start of the conversation."
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                temperature=0.3,
                max_completion_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": SUMMARIZATION_PROMPT.format(
                        previous_summary=previous_summary,
                        new_messages=new_messages_text
                    )
                }]
            )
            
            new_summary_text = response.choices[0].message.content.strip()
            
            first_msg = self.raw_recent_buffer[0]
            last_msg = self.raw_recent_buffer[-1]
            
            new_summary = {
                'text': new_summary_text,
                'covers_messages': [
                    first_msg['message_number'] if self.rolling_summary['message_count'] == 0 else self.rolling_summary['covers_messages'][0],
                    last_msg['message_number']
                ],
                'message_count': self.rolling_summary['message_count'] + len(self.raw_recent_buffer),
                'time_range_start': self.rolling_summary['time_range_start'] or first_msg['timestamp'],
                'time_range_end': last_msg['timestamp'],
                'last_updated': datetime.now().isoformat()
            }
            
            self.rolling_summary = new_summary
            
            print(f"Summary complete (messages {self.rolling_summary['covers_messages'][0]}-{self.rolling_summary['covers_messages'][1]})")
            
            await self.persist_summary_to_supabase()
            
            # Clear buffer after summarization
            self.raw_recent_buffer = []
            self.last_summary_time = time.time()
            self.messages_since_summary = 0
            
        except Exception as e:
            print(f"Error updating summary: {e}")
    
    async def persist_summary_to_supabase(self):
        """Persist summary to Supabase for historical record"""
        try:
            summary_record = {
                'session_id': self.session_id,
                'summary_text': self.rolling_summary['text'],
                'covers_message_start': self.rolling_summary['covers_messages'][0],
                'covers_message_end': self.rolling_summary['covers_messages'][1],
                'message_count': self.rolling_summary['message_count'],
                'time_range_start': self.rolling_summary['time_range_start'],
                'time_range_end': self.rolling_summary['time_range_end'],
                'domains_covered': json.dumps(self.current_domains)
            }
            
            supabase.table('context_summaries').insert(summary_record).execute()
            print(f"Summary persisted to Supabase")
            
        except Exception as e:
            print(f"Error persisting summary: {e}")
    
    def get_conversation_state(self):
        """Get current conversation state for Delivery Monitor"""
        return {
            'session_id': self.session_id,
            'silence': self.is_silence(),
            'time_since_last_message': self.time_since_last_message(),
            'active_domains': self.current_domains,
            'domain_confidence': self.domain_confidence,
            'current_keywords': self.current_keywords,
            'last_message_time': self.last_message_time
        }
    
    def to_dict(self):
        """Convert to dict for Redis storage"""
        return {
            'session_id': self.session_id,
            'rolling_summary': self.rolling_summary,
            'raw_recent_buffer': self.raw_recent_buffer,
            'consilience_responses': self.consilience_responses,
            'last_summary_time': self.last_summary_time,
            'messages_since_summary': self.messages_since_summary,
            'last_message_time': self.last_message_time,
            'messages_since_domain_inference': self.messages_since_domain_inference,
            'last_domain_inference_time': self.last_domain_inference_time,
            'current_domains': self.current_domains,
            'domain_confidence': self.domain_confidence,
            'current_keywords': self.current_keywords
        }
    
    @classmethod
    def from_dict(cls, data):
        """Load from dict"""
        context = cls(data['session_id'])
        context.rolling_summary = data.get('rolling_summary', context.rolling_summary)
        context.raw_recent_buffer = data.get('raw_recent_buffer', [])
        context.consilience_responses = data.get('consilience_responses', [])
        context.last_summary_time = data.get('last_summary_time', time.time())
        context.messages_since_summary = data.get('messages_since_summary', 0)
        context.last_message_time = data.get('last_message_time', time.time())
        context.messages_since_domain_inference = data.get('messages_since_domain_inference', 0)
        context.last_domain_inference_time = data.get('last_domain_inference_time', time.time())
        context.current_domains = data.get('current_domains', [])
        context.domain_confidence = data.get('domain_confidence', {})
        context.current_keywords = data.get('current_keywords', [])
        return context

def get_or_create_context(session_id):
    """Get existing context or create new one"""
    if session_id not in session_contexts:
        stored_state = redis_client.get(f'context_builder:{session_id}:state')
        if stored_state:
            context = ConversationContext.from_dict(json.loads(stored_state))
            print(f"Loaded existing context")
        else:
            context = ConversationContext(session_id)
            print(f"Created new context")
        
        session_contexts[session_id] = context
    
    return session_contexts[session_id]

def save_context_state(context):
    """Persist context state to Redis"""
    redis_client.set(
        f'context_builder:{context.session_id}:state',
        json.dumps(context.to_dict()),
        ex=3600
    )

def update_conversation_state_in_redis(context):
    """Update conversation state in Redis for Delivery Monitor"""
    redis_client.set(
        f'conversation_state:{context.session_id}',
        json.dumps(context.get_conversation_state()),
        ex=10
    )

async def process_message(session_id, message):
    """Process incoming message"""
    context = get_or_create_context(session_id)
    
    msg_num = message.get('message_number')
    text = message.get('text', '')
    speaker = message.get('speaker', 'Unknown')
    
    print(f"\nMessage {msg_num} ({speaker}): {text[:50]}")
    
    await context.add_message(message)
    
    if context.should_infer_domains():
        await context.infer_domains()
    
    if context.should_summarize():
        await context.update_summary()
    
    save_context_state(context)
    update_conversation_state_in_redis(context)

async def monitor_input_queue(session_id):
    """Monitor input queue for messages from Listener"""
    print(f"Context Builder monitoring session {session_id}")
    print(f"Buffer window: {RAW_BUFFER_TIME_WINDOW}s")
    print(f"Domain inference: Every {DOMAIN_INFERENCE_INTERVAL} messages or {DOMAIN_INFERENCE_TIME_INTERVAL}s")
    print(f"Summarization: Every {RAW_BUFFER_TIME_WINDOW}s\n")
    
    while True:
        try:
            result = redis_client.brpop(
                f'context_builder:{session_id}:input',
                timeout=1
            )
            
            if result:
                _, message_json = result
                message = json.loads(message_json)
                await process_message(session_id, message)
            else:
                # Update conversation state even when no messages
                context = get_or_create_context(session_id)
                update_conversation_state_in_redis(context)
            
            await asyncio.sleep(POLL_INTERVAL)
            
        except Exception as e:
            print(f"Error monitoring input queue: {e}")
            await asyncio.sleep(POLL_INTERVAL)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python context_builder.py <session_id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    
    await monitor_input_queue(session_id)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping Context Builder")