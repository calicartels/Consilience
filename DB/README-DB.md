# Database Layer

Real-time message storage and persistence using Redis and Supabase for multi-team transcription sessions.

## Architecture

**Redis**: Fast temporary storage with sorted sets for chronological message ordering and automatic expiration
**Supabase**: Persistent PostgreSQL storage for long-term conversation history
**Background Worker**: Asynchronous batch processing from Redis queue to Supabase

## Setup

Install dependencies:
```bash
python -m pip install redis supabase python-dotenv
```

Install Redis server:
```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl start redis-server
```

Create `.env` file:
```
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password_or_leave_empty
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
```

## Components

### storage.py
Main storage module with session-based message management and background processing.

**Core Functions:**
- `save_message()`: Stores messages in Redis with timestamp scoring and queues for Supabase
- `get_recent_messages()`: Retrieves messages from last N minutes for a session
- `get_all_messages()`: Gets complete message history for a session from Redis
- `background_worker()`: Processes Redis queue in batches to Supabase

### auth.py
Team-based session authentication and management system.

**Core Functions:**
- `create_session()`: Creates new team with password-protected session
- `join_session()`: Authenticates team members and returns session ID
- `end_session()`: Marks session as inactive when team finishes
- `get_active_sessions()`: Lists all currently active team sessions
- `hash_password()`: SHA-256 password hashing for secure storage

**Data Structure:**
```python
message = {
    'session_id': 'team-alpha-session-001',
    'speaker': 'Speaker_0',
    'text': 'transcribed text',
    'timestamp': '2025-10-02T10:30:45.123456',
    'confidence': 0.95,
    'message_number': 42
}
```

**Redis Keys:**
- `session:{session_id}:messages` - Sorted set with timestamp scores
- `db_write_queue` - FIFO queue for Supabase batch processing
- Auto-expires session data after 1 hour

## Usage

### Create Team Session
```bash
# Create new team
python DB/auth.py create "team-alpha" "password123"
# Returns session_id for team use

# Join existing team
python DB/auth.py join "team-alpha" "password123"
```

### Start Background Worker
```bash
python DB/storage.py
```

### Import for Use in Transcription
```python
from DB.storage import save_message, get_recent_messages

# Save a transcribed message
save_message(
    session_id="team-alpha-001", 
    speaker="Speaker_0",
    text="Hello world",
    timestamp=datetime.now().isoformat(),
    confidence=0.95,
    message_number=1
)

# Get recent messages for context
recent = get_recent_messages("team-alpha-001", minutes=5)
```

## Database Tables

### Supabase Schema

**Table: `sessions`**
```sql
id: uuid (primary key, auto-generated)
team_name: text (unique)
password_hash: text
active: boolean
created_at: timestamptz (default: now())
last_activity: timestamptz
```

**Table: `conversations`**
```sql
session_id: text (references sessions.id)
speaker: text  
text: text
timestamp: timestamptz
confidence: real
message_number: integer
```

## Team Isolation

Each team gets isolated data streams with secure authentication:
- **Password Protection**: Teams secured with SHA-256 hashed passwords
- **Unique Sessions**: Sessions identified by UUID-based `session_id`
- **Data Separation**: Redis keys prefixed with `session:{id}:messages`
- **Query Filtering**: Supabase queries filtered by `session_id`
- **Concurrent Teams**: Multiple teams can run simultaneously with complete data isolation
- **Session Management**: Active/inactive states track team lifecycle

## Performance

- **Redis**: Sub-millisecond message storage with sorted sets for chronological access
- **Batch Processing**: Groups up to 10 messages per Supabase write to reduce API calls
- **Error Recovery**: Failed Supabase writes are re-queued to Redis for retry
- **Memory Management**: 1-hour TTL on Redis session data prevents memory bloat

## Notes

Redis provides the speed needed for real-time transcription storage, while Supabase ensures data persistence. The authentication layer adds secure team management with password protection and session lifecycle tracking. The background worker decouples transcription speed from database write performance, allowing multiple teams to transcribe simultaneously without blocking each other.

**The hybrid Redis+Supabase architecture with secure authentication ensures both real-time performance and long-term data persistence for team-based transcription workflows.**
