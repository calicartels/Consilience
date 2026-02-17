# Listener Module

Real-time conversation monitoring with intelligent trigger detection for direct Consilience requests.

## Architecture

**Real-time Monitoring**: Polls Redis for new messages at 0.5s intervals
**Dumb Pipe**: Forwards all messages immediately to Context Builder
**LLM Detection**: Uses GPT-4o-mini to detect "consilience" mentions only
**Follow-up Tagging**: Checks 30s window after Consilience speaks to tag potential follow-ups
**No Buffering**: Passes messages immediately, no collection or aggregation

## Purpose

The Listener monitors transcription sessions and performs two simple tasks:

1. **Forward all messages** to Context Builder (dumb pipe)
2. **Detect triggers** when users say "consilience" or ask follow-up questions

It does NOT perform complex analysis, factual error detection, or missing perspective identification. Those responsibilities belong to the Orchestrator's background analysis task.

## Setup

Install dependencies:
```bash
python -m pip install openai redis python-dotenv
```

Create `.env` file with:
```
OPENAI_API_KEY=your_openai_api_key
REDIS_HOST=localhost
REDIS_PORT=6379
```

## Configuration

### Timing Parameters
- **POLL_INTERVAL**: `0.5s` - How often to check for new messages
- **FOLLOW_UP_WINDOW**: `30s` - Time window after Consilience speaks to tag follow-ups

### LLM Settings
- **Model**: `gpt-4o-mini` for fast, cost-effective "consilience" detection
- **Response Format**: JSON structured output
- **Max Tokens**: `50` tokens per detection for speed

## Components

### listener.py
Main monitoring module with simple message forwarding and trigger detection.

**Core Functions:**
- `monitor_session()`: Real-time Redis polling at 0.5s intervals
- `consilience_detection()`: GPT-4o-mini analysis for "consilience" mentions (handles misspellings)
- `follow_up_window_check()`: Reads `consilience_spoke:{session_id}` flag from Redis
- `orchestrator_signal_input()`: Sends trigger signals to Orchestrator
- `context_builder_input()`: Forwards all messages to Context Builder

## Trigger Detection

### Explicit Request
**Keywords**: "consilience" (and misspellings: consoliance, consilient, consoliant, etc.)
**Detection**: LLM identifies when user is addressing Consilience directly
**Response**: Sends signal to Orchestrator with message metadata

**Examples that trigger:**
- "hey consilience how are you"
- "consilience what is RNA"
- "consoliance can you help" (misspelling)
- "consilience" (standalone)

**Examples that DON'T trigger:**
- "the consilience of knowledge" (academic concept)
- "consilience is a theory about" (discussing the theory)
- "exploring consilience in science" (abstract discussion)

### Follow-up Detection
**Window**: 30 seconds after Consilience speaks
**Detection**: Checks `consilience_spoke:{session_id}` Redis flag (set by Delivery Monitor)
**Tagging**: Messages in this window are tagged with `potential_follow_up: true`
**Verification**: Orchestrator performs semantic analysis to verify actual follow-up intent

## Usage

### Start Listener
```bash
python LISTENER/listener.py <session_id>
```

### Integration with System
```bash
# Terminal 1: Start background storage
python DB/storage.py

# Terminal 2: Start Context Builder
python CONTEXT/context_builder.py session-123

# Terminal 3: Start Listener
python LISTENER/listener.py session-123

# Terminal 4: Start transcription
python STT/deepgram.py session-123
```

## Message Flow

1. **STT Module** → Transcribes speech → **Redis** (`messages:{session_id}`)
2. **Listener** → Polls Redis every 0.5s → New message detected
3. **Forward** → Sends to Context Builder immediately (all messages)
4. **Detection** → GPT-4o-mini checks for "consilience" mention
5. **Follow-up Check** → Reads `consilience_spoke:{session_id}` flag (30s expiration)
6. **Signal** → If trigger detected OR in follow-up window → Send to Orchestrator

## Signal Format

When a trigger is detected, Listener sends this to Orchestrator:

```json
{
  "trigger_type": "explicit_request",
  "message_number": 12345,
  "triggering_message": {
    "speaker": "Alice",
    "text": "hey consilience how does DNA work",
    "timestamp": "2024-11-02T20:15:30"
  },
  "potential_follow_up": true
}
```

**Fields:**
- `trigger_type`: Always "explicit_request" for Listener signals
- `message_number`: Unique message identifier
- `triggering_message`: Full message that caused the trigger
- `potential_follow_up`: Optional, present if within 30s follow-up window

## Filtering

**Skips Consilience messages**: Listener ignores messages where `speaker == "Consilience"` or `type == "consilience"` to avoid processing system's own responses.

## Data Processing

**Redis Query**: Uses `get_messages_since()` with message number tracking to fetch only new messages
**Message Number Tracking**: Maintains `last_processed_message_numbers` per session
**Deduplication**: Tracks `processed_message_ids` to avoid reprocessing
**Session Isolation**: Each session monitored independently

## Performance

- **Polling Speed**: 0.5s intervals balance responsiveness with resource usage
- **LLM Efficiency**: GPT-4o-mini provides fast detection (~100-200ms)
- **Memory Management**: Message number tracking prevents replay
- **Concurrent Sessions**: Multiple listeners can monitor different sessions simultaneously

## Notes

The Listener is intentionally simple: it forwards every message to Context Builder and detects explicit "consilience" mentions. It does not perform complex analysis, buffering, or prioritization. The Orchestrator handles all sophisticated decision-making through its Liaison Agent and background analysis tasks. This separation keeps the Listener fast and focused on real-time message routing.
