# Context Builder Module

Intelligent conversation context management with rolling summarization, domain inference, and keyword extraction.

## Architecture

**Message Buffering**: Maintains 2-minute sliding window of raw messages
**Domain Inference**: LLM classifies academic disciplines every 5 messages or 30 seconds
**Summarization**: LLM generates rolling summaries when buffer exceeds 2 minutes
**Keyword Extraction**: LLM extracts key concepts from each message
**State Persistence**: Redis storage with Supabase archival

## Purpose

The Context Builder maintains comprehensive conversation state for the entire system. It:

1. **Receives all messages** from Listener (dumb pipe input)
2. **Buffers recent messages** in 2-minute sliding window
3. **Summarizes older messages** to maintain conversation history
4. **Infers academic domains** from conversation content
5. **Extracts keywords** for relevance checking
6. **Tracks silence** for delivery timing
7. **Stores Consilience responses** separately for anti-repetition
8. **Provides context** to Orchestrator and Delivery Monitor

The Context Builder does NOT detect triggers or make decisions. It purely manages conversation state.

## Setup

Install dependencies:
```bash
python -m pip install openai redis python-dotenv supabase
```

Create `.env` file with:
```
OPENAI_API_KEY=your_openai_api_key
REDIS_HOST=localhost
REDIS_PORT=6379
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
```

## Configuration

### Timing Parameters
- **POLL_INTERVAL**: `0.5s` - How often to check input queue
- **RAW_BUFFER_TIME_WINDOW**: `120s` - 2-minute buffer before summarization
- **DOMAIN_INFERENCE_INTERVAL**: `5` messages
- **DOMAIN_INFERENCE_TIME_INTERVAL**: `30s`
- **SILENCE_THRESHOLD**: `4.0s` - Silence detection for delivery timing

### LLM Settings

**Keyword Extraction**:
- Model: `gpt-4o-mini`
- Temperature: `0.2`
- Max Tokens: `100`

**Domain Inference**:
- Model: `gpt-4o-mini`
- Temperature: `0.2`
- Max Tokens: `400`

**Summarization**:
- Model: `gpt-4o`
- Temperature: `0.3`
- Max Tokens: `1000`

## Components

### ConversationContext Class
Main state management class tracking all conversation data.

**State Fields:**
- `rolling_summary`: Previous conversation summary with metadata
- `raw_recent_buffer`: Last 2 minutes of messages
- `consilience_responses`: History of Consilience contributions
- `current_domains`: Active academic disciplines
- `domain_confidence`: Confidence scores per domain
- `current_keywords`: Topic keywords from recent messages
- `last_message_time`: For silence detection

**Core Methods:**

#### add_message(message)
Processes incoming user messages:
- Extracts keywords using LLM
- Adds to raw buffer with metadata
- Tags with `buffer_entry_time` for expiration
- Updates message time for silence detection

#### add_consilience_response(response)
Stores Consilience responses separately:
- Maintains `consilience_responses` history
- Also adds to raw buffer for context
- Extracts keywords from response
- Used by Orchestrator to avoid repetition

#### infer_domains()
Uses LLM to classify academic disciplines:
- Triggered every 5 messages OR 30 seconds
- Analyzes last 10 messages from buffer
- Returns domains, confidence scores, topic keywords
- Tags all untagged buffer messages with domain metadata

**Domain List** (18 supported):
- Biology / Life Sciences
- Chemistry / Biochemistry
- Physics / Astronomy
- Mathematics / Statistics
- Computer Science / Software Engineering
- Medicine / Health Sciences / Neuroscience
- Psychology / Cognitive Science
- Engineering (Mechanical, Electrical, Civil, etc.)
- Business / Economics / Management
- Social Sciences / Sociology / Anthropology
- Environmental Science / Ecology
- Political Science / Law
- Philosophy / Ethics
- History / Humanities
- Linguistics / Communication
- Data Science / Machine Learning
- Design / User Experience
- Robotics / Automation

#### update_summary()
Generates rolling summaries using LLM:
- Triggered when buffer exceeds 2 minutes
- Merges previous summary with buffered messages
- Maintains chronological flow
- Persists to Supabase for historical record
- Clears buffer after summarization

#### extract_keywords(text)
Extracts 5-10 meaningful keywords per message:
- Focus on technical terms and domain vocabulary
- Preserves compound terms (e.g., "machine learning algorithm")
- Used for relevance checking in Delivery Monitor

#### get_conversation_state()
Provides real-time state to Delivery Monitor:
- Silence status (>4s since last message)
- Time since last message
- Active domains
- Current keywords
- Last message timestamp

## Usage

### Start Context Builder
```bash
python CONTEXT/context_builder.py <session_id>
```

### Integration with System
```bash
# Terminal 1: Start Context Builder first
python CONTEXT/context_builder.py session-123

# Terminal 2: Start Listener (feeds Context Builder)
python LISTENER/listener.py session-123

# Terminal 3: Start Orchestrator (reads Context Builder state)
python ORCHESTRATOR/orchestrator.py session-123
```

## Message Flow

1. **Listener** → Sends all messages to `context_builder:{session_id}:input` queue
2. **Context Builder** → Polls queue every 0.5s
3. **Processing** → Extracts keywords, adds to buffer
4. **Domain Inference** → Every 5 messages or 30s, classify disciplines
5. **Summarization** → When buffer exceeds 2 min, generate summary and clear
6. **State Storage** → Save to Redis `context_builder:{session_id}:state`
7. **Conversation State** → Update Redis `conversation_state:{session_id}` for Delivery Monitor
8. **Supabase Archive** → Persist summaries for historical record

## Data Storage

### Redis Keys

**Input Queue**: `context_builder:{session_id}:input`
- Receives messages from Listener
- Receives Consilience responses from Orchestrator

**State Storage**: `context_builder:{session_id}:state`
- Full context state (summary, buffer, domains, keywords)
- Expires after 1 hour
- Read by Orchestrator

**Conversation State**: `conversation_state:{session_id}`
- Lightweight state for Delivery Monitor
- Expires after 10 seconds (refreshed continuously)
- Contains: silence, time_since_last, domains, keywords

### Supabase Table

**context_summaries**:
- Permanent archive of all summaries
- Fields: session_id, summary_text, covers_message_start/end, message_count, time_range, domains_covered

## State Format

Context Builder provides this state to Orchestrator:

```json
{
  "rolling_summary": {
    "text": "Summary of conversation...",
    "covers_messages": [1, 45],
    "message_count": 45,
    "time_range_start": "2024-11-02T20:10:00",
    "time_range_end": "2024-11-02T20:12:00",
    "last_updated": "2024-11-02T20:12:05"
  },
  "raw_recent_buffer": [
    {
      "message_number": 46,
      "speaker": "Alice",
      "text": "How does DNA replication work?",
      "timestamp": "2024-11-02T20:12:10",
      "buffer_entry_time": 1698876730.5,
      "keywords": ["DNA", "replication", "molecular biology"],
      "domains": ["Biology / Life Sciences"],
      "domain_confidence": {"Biology / Life Sciences": 0.95}
    }
  ],
  "consilience_responses": [
    {
      "message_number": 40,
      "speaker": "Consilience",
      "text": "From a Biology perspective...",
      "timestamp": "2024-11-02T20:11:30",
      "metadata": {"trigger_type": "explicit_request", "domains": ["Biology / Life Sciences"]}
    }
  ],
  "current_domains": ["Biology / Life Sciences", "Chemistry / Biochemistry"],
  "domain_confidence": {"Biology / Life Sciences": 0.95, "Chemistry / Biochemistry": 0.78},
  "current_keywords": ["DNA", "replication", "enzymes", "helicase"]
}
```

## Performance

- **Polling Speed**: 0.5s intervals for input queue monitoring
- **LLM Efficiency**: 
  - Keywords: ~100-200ms per message
  - Domains: ~300-500ms every 5 messages
  - Summaries: ~1-2s every 2 minutes
- **Memory Management**: 2-minute buffer window prevents unbounded growth
- **State Persistence**: Redis ensures recovery after crashes
- **Supabase Archive**: Async persistence doesn't block processing

## Silence Detection

Context Builder tracks message timing for delivery coordination:
- Updates `last_message_time` on every message
- Calculates `time_since_last_message()` for Delivery Monitor
- `is_silence()` returns true if >4s elapsed
- Enables intelligent delivery timing (wait for natural pauses)

## Notes

The Context Builder is the system's memory. It maintains a complete view of the conversation through intelligent buffering and summarization. The 2-minute sliding window keeps recent messages available verbatim while older content is compressed into summaries. Domain inference and keyword extraction happen continuously to keep metadata fresh for decision-making and relevance checking. The separation of Consilience responses into dedicated storage enables anti-repetition checking in the Orchestrator.

