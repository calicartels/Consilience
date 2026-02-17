# Orchestrator Module

Intelligent decision-making system with dual-task architecture for direct triggers and background analysis.

## Architecture

**Dual-Task System**: Two parallel async tasks running simultaneously
**Task 1**: Direct trigger processing (P0 priority)
**Task 2**: Background analysis (P1/P2/P3 priorities)
**Liaison Agent**: LLM-based decision engine choosing response paths
**Deduplication**: Semantic similarity checking to avoid repetition
**Specialist Activation**: Calls domain experts based on missing perspectives

## Purpose

The Orchestrator is the brain of Consilience. It:

1. **Monitors triggers** from Listener (explicit "consilience" mentions)
2. **Waits for context** (5s or 5 messages) before deciding
3. **Verifies follow-ups** semantically to previous Consilience responses
4. **Makes intelligent decisions** via Liaison Agent (PATH A/B/C)
5. **Calls specialists** based on missing domain perspectives
6. **Performs background analysis** for factual errors and stuck signals
7. **Deduplicates responses** using semantic similarity
8. **Queues responses** by priority for Delivery Monitor

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

### Task 1: Direct Triggers (P0)
- **POLL_INTERVAL**: `0.5s` - How often to check for triggers
- **WAIT_FOR_FOLLOWUP_SECONDS**: `5s` - Wait time for context accumulation
- **WAIT_FOR_FOLLOWUP_MESSAGES**: `5` messages - Alternative wait trigger
- **FOLLOW_UP_WINDOW**: `30s` - Window to verify follow-up intent

### Task 2: Background Analysis (P1/P2/P3)
- **BACKGROUND_ANALYSIS_STARTUP_DELAY**: `120s` - Initial wait before starting
- **BACKGROUND_ANALYSIS_INTERVAL**: `90s` - Check frequency
- **P1_DELIVERY_TARGET**: `30s` - Target delivery time for factual errors
- **P2P3_DELIVERY_TARGET**: `90s` - Target delivery time for stuck signals

## Task 1: Direct Triggers

Handles explicit "consilience" mentions from Listener.

### Process Flow

1. **Receive Signal**: Monitor `orchestrator_triggers:{session_id}` queue
2. **Wait for Context**: 5 seconds OR 5 new messages (whichever first)
3. **Follow-up Verification**: If `potential_follow_up` tag present:
   - Use LLM to verify semantic connection to last Consilience response
   - If connected: Include previous response in context
   - If not connected: Treat as new topic
4. **Pull Context**: Read full state from Context Builder (after wait)
5. **Liaison Agent Decision**: LLM analyzes trigger + context → Choose path
6. **Execute Path**: Generate response or continue monitoring
7. **Queue Response**: Add to P0 queue for immediate delivery
8. **Store Response**: Send to Context Builder for history tracking

### Liaison Agent Paths

**PATH A - Continue Monitoring**:
- Conversation flowing smoothly, no response needed
- Question was rhetorical or already being addressed
- Team actively working through issue themselves
- **Action**: Do nothing, return to monitoring

**PATH B - Generate Response**:
- User asked direct question requiring expert answer
- Clear interdisciplinary topic needing multiple perspectives
- Missing expert perspective that would enhance discussion
- User asking follow-up about previous Consilience response
- **Action**: Call specialists based on `missing_domains`, queue P0 response

**PATH C - Request Clarification**:
- Transcribed text garbled or unclear
- Cannot determine what user is asking
- Need more context to understand
- **Action**: Queue clarification message "I didn't catch that clearly, could you repeat?"

### Liaison Agent Decision Factors

The Liaison Agent (GPT-4o) considers:
- Trigger message content (the "consilience" mention)
- Recent conversation messages (last 5-10 messages)
- Previous summary (if available)
- Active domains (currently discussed topics)
- Missing domains (expert perspectives not yet present)
- Follow-up context (if within 30s of last response)
- Consilience history (avoid repetition)

**Output**:
```json
{
  "decision_path": "PATH_B",
  "reasoning": "User asked direct question about DNA",
  "active_domains": ["Biology / Life Sciences"],
  "missing_domains": ["Biology / Life Sciences", "Chemistry / Biochemistry"],
  "urgency": 8,
  "needs_response": true,
  "response_type": "missing_perspective",
  "task_type": "provide_perspective"
}
```

## Task 2: Background Analysis

Proactive monitoring for factual errors and stuck signals.

### Startup & Timing
- **Startup Delay**: Waits 120s from conversation start to avoid premature intervention
- **Check Interval**: Runs every 90s thereafter
- **Conservative Prompting**: Only flags clear, unambiguous issues

### P1: Factual Error Detection

Uses GPT-5 with conservative prompting to detect serious errors.

**Criteria (VERY CONSERVATIVE)**:
- Only unambiguous, serious errors (e.g., "DNA has 3 bases")
- NOT incomplete sentences or truncated speech
- NOT teaching examples or simplified explanations
- NOT quiz questions or hypothetical scenarios
- When in doubt, DO NOT FLAG

**Examples of what TO flag**:
- "DNA has 3 bases: A, T, G" (missing C)
- "RNA uses thymine instead of uracil" (backwards)
- "Proteins are made of nucleotides" (wrong - amino acids)

**Examples of what NOT to flag**:
- "in eukaryotic cells dna tends to be found in the" (incomplete)
- "eight DNA nucleotides would have eight bases" (correct)
- Quiz questions or teaching scenarios

**Deduplication**: Checks P0/P1/P2/P3 queues and last 5 Consilience responses using semantic similarity

**If detected**:
- Activate specialists from relevant domains (max 2)
- Generate correction: "Quick correction: {correct_info}\n\n{specialist_perspectives}"
- Queue as P1 (target delivery: within 30s)

### P2/P3: Stuck Signal Detection

Uses GPT-5 with conservative prompting to detect when team needs help.

**Criteria (VERY CONSERVATIVE)**:
- Only clear, unambiguous evidence of being stuck
- NOT if conversation flowing naturally
- NOT quiz questions or teaching scenarios
- NOT if someone actively explaining
- When in doubt, DO NOT FLAG

**Stuck Types**:
1. **Repeated Questions**: Same question asked 3+ times with no answer
2. **Unanswered Questions**: 5+ questions about same topic, none addressed
3. **Explicit Uncertainty**: "I'm completely lost", "I have no idea"
4. **Strong Negative Sentiment**: "This is impossible", "I'm so frustrated"
5. **Explicit Requests**: "Can someone explain this?"
6. **Jargon Confusion**: "What does [term] mean?" (explicit confusion)

**Deduplication**: Same semantic similarity checking as P1

**If detected**:
- Activate specialists from relevant domains (max 2)
- Generate perspective response
- Queue as P2 or P3 based on severity (target delivery: within 90s)

## Deduplication System

Prevents redundant responses through semantic similarity checking.

**Checks Against**:
1. **All Priority Queues**: P0, P1, P2, P3 (already queued items)
2. **Recent Responses**: Last 5 Consilience responses within 5 minutes

**Method**:
- Compares `issue_description` fields using LLM
- GPT-4o-mini determines if issues are semantically similar
- If similar: Skip generating new response

**Example**:
- Issue 1: "DNA location in eukaryotic cells unclear"
- Issue 2: "Where is DNA found in eukaryotes?"
- Result: Similar → Skip second response

## Components

### Core Functions

#### process_trigger(signal, session_id)
Task 1 handler:
- Waits 5s OR 5 messages for context
- Verifies follow-up if tagged
- Calls Liaison Agent
- Executes chosen path
- Queues P0 response

#### liaison_agent_decision(trigger_info, context, session_id)
Main decision engine:
- Analyzes trigger + conversation context
- Returns PATH A, B, or C decision
- Identifies active and missing domains
- Temperature: 0.3, Model: GPT-4o

#### follow_up_verification(message_text, speaker, last_response)
Semantic follow-up checker:
- Verifies if message references previous response
- Checks direct references, continuation words, related questions
- Temperature: 0.2, Model: GPT-4o-mini

#### background_analysis(session_id)
Task 2 handler:
- Waits 120s startup delay
- Runs factual error detection every 90s
- Runs stuck signal detection every 90s
- Deduplicates before queueing

#### factual_error_detection(context)
Conservative error checking:
- Analyzes recent raw buffer
- Returns: error_detected, error_description, correct_information, severity, domains_needed
- Temperature: 0.2, Model: GPT-5

#### stuck_signal_detection(context)
Conservative stuck detection:
- Analyzes recent raw buffer + Consilience history
- Returns: stuck_detected, stuck_type, description, severity, domains_needed, priority
- Temperature: 0.2, Model: GPT-5

#### deduplication_check(session_id, issue_description, domains, priority)
Semantic similarity checker:
- Checks all queues and recent responses
- Uses GPT-4o-mini for comparison
- Returns: true (duplicate) or false (unique)

#### semantic_similarity_check(issue1, issue2)
LLM comparison:
- Determines if two issues describe same problem
- Temperature: 0.2, Model: GPT-4o-mini

## Usage

### Start Orchestrator
```bash
python ORCHESTRATOR/orchestrator.py <session_id>
```

### Integration with System
```bash
# Terminal 1: Start Context Builder
python CONTEXT/context_builder.py session-123

# Terminal 2: Start Listener
python LISTENER/listener.py session-123

# Terminal 3: Start Orchestrator
python ORCHESTRATOR/orchestrator.py session-123

# Terminal 4: Start Delivery Monitor
python DELIVERY/delivery_monitor.py session-123
```

## Data Flow

### Task 1 (Direct Triggers - P0)
1. **Listener** → Detects "consilience" → Signal to `orchestrator_triggers:{session_id}`
2. **Orchestrator** → Reads signal → Waits 5s or 5 msgs
3. **Context Fetch** → Reads Context Builder state (after wait)
4. **Liaison Agent** → Analyzes → PATH A/B/C decision
5. **Specialists** → If PATH B → Generate perspectives
6. **Queue** → Add to `response_queue:{session_id}:P0`
7. **Storage** → Send to Context Builder via `context_builder:{session_id}:input`

### Task 2 (Background Analysis - P1/P2/P3)
1. **Orchestrator** → Waits 120s → Then checks every 90s
2. **Context Fetch** → Reads Context Builder state
3. **Error Detection** → Checks factual errors → If found → P1 response
4. **Stuck Detection** → Checks stuck signals → If found → P2/P3 response
5. **Deduplication** → Semantic check against queues + history
6. **Specialists** → Generate perspectives
7. **Queue** → Add to `response_queue:{session_id}:{priority}`
8. **Storage** → Send to Context Builder

## Priority System

**P0 (Immediate)**:
- Direct "consilience" mentions (Task 1)
- Delivered immediately, no conditions
- Target: Instant delivery

**P1 (High - 30s target)**:
- Factual errors requiring correction (Task 2)
- Delivered during silence within 30s of detection
- Critical but not interrupting

**P2 (Medium - 90s target)**:
- Moderate stuck signals (Task 2)
- Delivered during silence within 90s of detection
- Helpful but not urgent

**P3 (Low - 90s target)**:
- Low-priority stuck signals (Task 2)
- Delivered during silence within 90s of detection
- Nice-to-have perspectives

## Performance

- **Task 1 Latency**: 5s wait + LLM calls (~2-3s) = ~8s total response time
- **Task 2 Frequency**: Every 90s (conservative to avoid false positives)
- **LLM Efficiency**:
  - Liaison Agent: GPT-4o (~1-2s)
  - Error Detection: GPT-5 (~2-3s)
  - Stuck Detection: GPT-5 (~2-3s)
  - Follow-up Verification: GPT-4o-mini (~200ms)
  - Semantic Similarity: GPT-4o-mini (~200ms)
- **Deduplication**: Prevents ~30-40% redundant responses in testing
- **Memory**: Minimal state, relies on Context Builder for conversation memory

## Notes

The Orchestrator's dual-task architecture separates immediate user requests from proactive background monitoring. Task 1 ensures responsive handling of direct "consilience" mentions with intelligent follow-up detection. Task 2 provides safety net for factual errors and team difficulties, but uses conservative prompting to avoid false positives. The Liaison Agent's PATH A/B/C decision framework keeps responses focused and prevents over-participation. Semantic deduplication ensures Consilience doesn't repeat itself or address already-resolved issues. All responses flow through the same priority queue system for coordinated delivery.

