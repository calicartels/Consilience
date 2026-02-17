import asyncio
import json
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from DB.storage import redis_client
from SPECIALISTS.specialists import SpecialistSystem

load_dotenv()

POLL_INTERVAL = 0.5
WAIT_FOR_FOLLOWUP_SECONDS = 5
WAIT_FOR_FOLLOWUP_MESSAGES = 5
FOLLOW_UP_WINDOW = 30
BACKGROUND_ANALYSIS_STARTUP_DELAY = 120
BACKGROUND_ANALYSIS_INTERVAL = 90
P1_DELIVERY_TARGET = 30
P2P3_DELIVERY_TARGET = 90

client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
specialist_system = SpecialistSystem()

LIAISON_AGENT_PROMPT = """You are the Liaison Agent for Consilience, an AI assistant monitoring interdisciplinary research conversations.

Your role: Analyze trigger events and decide if Consilience should respond.

TRIGGER INFORMATION:
{trigger_info}

IMPORTANT: The trigger_info contains "triggering_message" which shows the EXACT message where the user said "consilience" or addressed Consilience directly. This is WHY the trigger fired. However, the full question may span multiple messages in the RECENT MESSAGES section below. Analyze both the triggering message AND the surrounding context to understand the complete request.

CONVERSATION CONTEXT:
{conversation_context}

CURRENT DOMAINS BEING DISCUSSED: {active_domains}

FOLLOW-UP CONTEXT:
If trigger_info contains 'verified_follow_up': true, the user message is asking for more detail or clarification about Consilience's previous response (included in 'last_consilience_response'). Consider this when making your decision.

DECISION FRAMEWORK:
Analyze and choose ONE path:

PATH_A - Continue Monitoring: 
- User explicitly called "consilience" but conversation is flowing smoothly
- No real interdisciplinary gap or missing perspective
- Question was rhetorical or already being addressed
- Team is actively working through the issue themselves
- IMPORTANT: Only choose PATH_A if there is NO question or request. If the user asks ANY question after saying "consilience", choose PATH_B.

PATH_B - Generate Response:
- User said "consilience" AND asked a question (check triggering_message and surrounding messages)
- Clear interdisciplinary topic needing multiple perspectives
- User asked a direct question requiring expert answer
- Missing EXPERT perspective that would enhance discussion
- Factual error that should be addressed
- User explicitly requested input
- User asking follow-up question about previous Consilience response
- IMPORTANT: If you see "consilience" followed by "how", "what", "why", "explain", etc., this is PATH_B

PATH_C - Request Clarification:
- Transcribed text is garbled, incomplete, or unclear
- Cannot determine what the user is asking
- Need more context to understand the discussion

CRITICAL DISTINCTION:
- "active_domains" = What TOPICS/SUBJECTS are being discussed
- "missing_domains" = What EXPERT PERSPECTIVES are MISSING from the conversation
  
For example:
- User asks "How does DNA work?" 
  → active_domains: ["Biology / Life Sciences"]
  → missing_domains: ["Biology / Life Sciences", "Chemistry / Biochemistry"]

If user ASKS A QUESTION about a domain, that domain should be in missing_domains because they need an expert answer.

IMPORTANT: missing_domains should NEVER be empty if you choose PATH_B. Always identify at least one domain.

Respond with JSON only:
{{
  "decision_path": "PATH_A" | "PATH_B" | "PATH_C",
  "reasoning": "brief explanation of decision",
  "active_domains": ["domain1", "domain2"],
  "missing_domains": ["domain3", "domain4"],
  "urgency": 0-10,
  "needs_response": true/false,
  "response_type": "factual_correction" | "missing_perspective" | "jargon_translation" | "clarification" | null,
  "task_type": "provide_perspective" | "translate_jargon" | "fill_gap" | "factual_correction"
}}"""

FOLLOW_UP_DETECTION_PROMPT = """Analyze if this message is a follow-up question to Consilience's previous response.

CONSILIENCE'S LAST RESPONSE:
{last_consilience_response}

CURRENT MESSAGE:
Speaker: {speaker}
Text: {text}

Is this message asking about, referencing, or continuing the topic from Consilience's response?

Consider:
- Direct references: "that", "you said", "what you mentioned"
- Continuation words: "also", "and", "but", "what about"
- Related questions about the same topic
- Requests for clarification or more detail

Respond with JSON only:
{{
  "is_follow_up": true/false,
  "reasoning": "brief explanation"
}}"""

FACTUAL_ERROR_DETECTION_PROMPT = """Analyze the recent conversation for SERIOUS factual errors that would significantly harm understanding.

CONVERSATION:
{conversation}

CRITICAL INSTRUCTIONS - BE VERY CONSERVATIVE:
- Only flag UNAMBIGUOUS, SERIOUS errors (e.g., "DNA has 3 bases" when it has 4)
- DO NOT flag incomplete sentences or truncated speech (this is live transcription)
- DO NOT flag teaching examples or simplified explanations
- DO NOT flag quiz questions or hypothetical scenarios
- DO NOT flag when someone is ABOUT to explain something
- When in doubt, DO NOT FLAG

Examples of what NOT to flag:
- "in eukaryotic cells dna tends to be found in the" [incomplete sentence, likely continuing]
- "eight DNA nucleotides would have eight bases" [this is CORRECT - 8 nucleotides = 8 bases]
- "if I have 8 nucleotides, that's 4 base pairs" [CORRECT if double-stranded DNA]
- Quiz questions or teaching examples
- Simplified explanations for educational purposes

Examples of what TO flag:
- "DNA has 3 bases: A, T, G" [clearly wrong - missing C]
- "RNA uses thymine instead of uracil" [backwards - RNA uses uracil]
- "Proteins are made of nucleotides" [wrong - made of amino acids]

If you're uncertain whether something is an error, DO NOT FLAG IT.

IMPORTANT: Use EXACT domain format from this list:
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

Respond with valid JSON only:
{{
  "error_detected": true/false,
  "error_description": "what is wrong",
  "correct_information": "what should be said instead",
  "severity": "low" | "medium" | "high",
  "domains_needed": ["Biology / Life Sciences", "Chemistry / Biochemistry"],
  "issue_description": "brief description for deduplication"
}}"""

STUCK_DETECTION_PROMPT = """Analyze the conversation for CLEAR "stuck" signals indicating the team genuinely needs help.

CONVERSATION:
{conversation}

PREVIOUS CONSILIENCE CONTRIBUTIONS:
{consilience_history}

CRITICAL INSTRUCTIONS - BE VERY CONSERVATIVE:
- Only flag if there is CLEAR, UNAMBIGUOUS evidence of being stuck
- DO NOT flag if the conversation is flowing naturally
- DO NOT flag quiz questions or teaching scenarios
- DO NOT flag if someone is actively explaining something
- When in doubt, DO NOT FLAG

Check for these signals (must be CLEAR and OBVIOUS):
1. Repeated questions: Same question asked 3+ times with no answer
2. Multiple unanswered questions: 5+ questions about same topic, none addressed
3. Explicit uncertainty: "I'm completely lost", "I have no idea", "I don't understand at all"
4. Strong negative sentiment: "This is impossible", "I'm so frustrated", "This makes no sense"
5. Explicit requests for help: "Can someone explain this?", "I need help understanding"
6. Explicit jargon confusion: "What does [term] mean?", "I don't know what [term] is"

DO NOT flag:
- Normal educational flow or quiz questions
- Rhetorical questions
- Questions immediately followed by answers
- Casual uncertainty ("hmm", "interesting")
- Someone actively teaching/explaining

Consider what Consilience has ALREADY addressed - don't flag issues already resolved.

IMPORTANT: Use EXACT domain format from this list:
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

Respond with valid JSON only:
{{
  "stuck_detected": true/false,
  "stuck_type": "repeated_questions" | "unanswered_questions" | "uncertainty" | "negative_sentiment" | "missing_perspective" | "jargon_confusion" | null,
  "description": "what the issue is",
  "severity": "low" | "medium" | "high",
  "domains_needed": ["Biology / Life Sciences", "Chemistry / Biochemistry"],
  "priority": "P2" | "P3",
  "issue_description": "brief description for deduplication"
}}"""

SEMANTIC_SIMILARITY_PROMPT = """Compare these two issues to determine if they are semantically similar.

ISSUE 1:
{issue1}

ISSUE 2:
{issue2}

Are these describing the SAME issue or question? Consider:
- Same topic/subject matter
- Same underlying problem
- Would addressing one resolve the other?

Respond with JSON only:
{{
  "are_similar": true/false,
  "reasoning": "brief explanation"
}}"""

def context_builder_state(session_id):
    try:
        state_json = redis_client.get(f'context_builder:{session_id}:state')
        
        if not state_json:
            return {
                'summary': {'text': '', 'covers_messages': [0, 0], 'message_count': 0},
                'recent_raw': [],
                'consilience_history': [],
                'active_domains': [],
                'current_keywords': []
            }
        
        state = json.loads(state_json)
        
        return {
            'summary': state.get('rolling_summary', {}),
            'recent_raw': state.get('raw_recent_buffer', []),
            'consilience_history': state.get('consilience_responses', [])[-5:],
            'active_domains': state.get('current_domains', []),
            'current_keywords': state.get('current_keywords', [])
        }
        
    except Exception as e:
        print(f"Error getting context: {e}")
        return {
            'summary': {'text': '', 'covers_messages': [0, 0], 'message_count': 0},
            'recent_raw': [],
            'consilience_history': [],
            'active_domains': [],
            'current_keywords': []
        }

def llm_context_format(context):
    formatted_parts = []
    
    if context['summary'].get('text'):
        formatted_parts.append("=== PREVIOUS DISCUSSION (SUMMARIZED) ===")
        formatted_parts.append(context['summary']['text'])
        formatted_parts.append("")
    
    if context['recent_raw']:
        formatted_parts.append("=== RECENT MESSAGES ===")
        for msg in context['recent_raw']:
            domains_str = f"[Domains: {', '.join(msg.get('domains', []))}]" if msg.get('domains') else ""
            formatted_parts.append(f"{msg['speaker']}: {msg['text']} {domains_str}")
        formatted_parts.append("")
    
    if context['consilience_history']:
        formatted_parts.append("=== CONSILIENCE PREVIOUS CONTRIBUTIONS ===")
        for resp in context['consilience_history']:
            formatted_parts.append(f"[{resp['timestamp']}] {resp['text'][:100]}...")
    
    return "\n".join(formatted_parts)

def context_builder_input(session_id, response_text, metadata, message_number=None):
    response_message = {
        'message_number': message_number or int(time.time() * 1000),
        'speaker': 'Consilience',
        'text': response_text,
        'timestamp': datetime.now().isoformat(),
        'type': 'consilience',
        'metadata': metadata
    }
    
    redis_client.lpush(
        f'context_builder:{session_id}:input',
        json.dumps(response_message)
    )

def delivery_queue_input(session_id, priority, response_text, trigger_info, liaison_decision):
    response_item = {
        'queue_id': f"{session_id}-{int(time.time() * 1000)}",
        'session_id': session_id,
        'priority': priority,
        'response_text': response_text,
        'timestamp': datetime.now().isoformat(),
        'trigger_info': trigger_info,
        'decision_info': liaison_decision,
        'status': 'queued',
        'keywords': liaison_decision.get('active_domains', []) + liaison_decision.get('missing_domains', [])
    }
    
    redis_client.lpush(
        f'response_queue:{session_id}:{priority}',
        json.dumps(response_item)
    )
    
    return response_item

async def semantic_similarity_check(issue1, issue2):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            max_completion_tokens=100,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": SEMANTIC_SIMILARITY_PROMPT.format(
                    issue1=issue1,
                    issue2=issue2
                )
            }]
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get('are_similar', False)
        
    except Exception as e:
        print(f"Error checking similarity: {e}")
        return False

async def deduplication_check(session_id, issue_description, domains_needed, priority):
    try:
        for p in ['P0', 'P1', 'P2', 'P3']:
            queued = redis_client.lrange(f'response_queue:{session_id}:{p}', 0, -1)
            for item_json in queued:
                item = json.loads(item_json)
                queued_issue = item.get('decision_info', {}).get('issue_description', '')
                
                if queued_issue:
                    is_similar = await semantic_similarity_check(issue_description, queued_issue)
                    if is_similar:
                        print(f"Deduplication: Similar issue already in {p} queue")
                        return True
        
        context = context_builder_state(session_id)
        recent_responses = context['consilience_history']
        current_time = time.time()
        
        for resp in recent_responses:
            resp_time = datetime.fromisoformat(resp['timestamp']).timestamp()
            if current_time - resp_time < 300:
                resp_issue = resp.get('metadata', {}).get('issue_description', '')
                
                if resp_issue:
                    is_similar = await semantic_similarity_check(issue_description, resp_issue)
                    if is_similar:
                        print(f"Deduplication: Similar issue addressed {(current_time - resp_time):.0f}s ago")
                        return True
        
        return False
        
    except Exception as e:
        print(f"Error in deduplication: {e}")
        return False

async def follow_up_verification(message_text, speaker, last_consilience_response):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            max_completion_tokens=100,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": FOLLOW_UP_DETECTION_PROMPT.format(
                    last_consilience_response=last_consilience_response,
                    speaker=speaker,
                    text=message_text
                )
            }]
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get('is_follow_up', False)
        
    except Exception as e:
        print(f"Error checking follow-up: {e}")
        return False

async def liaison_agent_decision(trigger_info, context, session_id):
    conversation_context = llm_context_format(context)
    active_domains_str = ", ".join(context.get('active_domains', [])) if context.get('active_domains') else "none identified yet"
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            temperature=0.3,
            max_completion_tokens=500,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": LIAISON_AGENT_PROMPT.format(
                    trigger_info=json.dumps(trigger_info, indent=2),
                    conversation_context=conversation_context,
                    active_domains=active_domains_str
                )
            }]
        )
        
        return json.loads(response.choices[0].message.content)
        
    except Exception as e:
        print(f"Error in Liaison Agent: {e}")
        return {
            "decision_path": "PATH_A",
            "reasoning": f"Error: {e}",
            "active_domains": [],
            "missing_domains": [],
            "urgency": 0,
            "needs_response": False,
            "response_type": None,
            "task_type": "provide_perspective"
        }

async def wait_for_context(session_id, initial_message_number):
    start_time = time.time()
    
    print(f"Waiting for additional context (5s OR 5 messages)...")
    
    if initial_message_number is None:
        print(f"Wait complete: {WAIT_FOR_FOLLOWUP_SECONDS:.1f}s elapsed (no message number)")
        await asyncio.sleep(WAIT_FOR_FOLLOWUP_SECONDS)
        return
    
    while True:
        elapsed = time.time() - start_time
        
        if elapsed >= WAIT_FOR_FOLLOWUP_SECONDS:
            print(f"Wait complete: {elapsed:.1f}s elapsed")
            return
        
        context = context_builder_state(session_id)
        recent_messages = context['recent_raw']
        
        new_messages = [m for m in recent_messages if m.get('message_number') and m['message_number'] > initial_message_number]
        
        if len(new_messages) >= WAIT_FOR_FOLLOWUP_MESSAGES:
            print(f"Wait complete: {len(new_messages)} new messages received")
            return
        
        await asyncio.sleep(0.5)

async def process_trigger(signal, session_id):
    message_number = signal.get('message_number')
    is_potential_follow_up = signal.get('potential_follow_up', False)
    triggering_message = signal.get('triggering_message', {})
    
    print(f"\n{'='*70}")
    print(f"TASK 1: Direct Trigger")
    print(f"Message #{message_number}")
    print(f"Triggering text: {triggering_message.get('text', 'N/A')[:60]}")
    print(f"Potential follow-up: {is_potential_follow_up}")
    print(f"{'='*70}\n")
    
    await wait_for_context(session_id, message_number)
    
    context = context_builder_state(session_id)
    
    if is_potential_follow_up and context['consilience_history']:
        last_response = context['consilience_history'][-1]['text']
        
        trigger_message = None
        if message_number:
            trigger_message = next(
                (m for m in context['recent_raw'] if m.get('message_number') == message_number),
                None
            )
        
        if trigger_message:
            is_actually_follow_up = await follow_up_verification(
                trigger_message['text'],
                trigger_message['speaker'],
                last_response
            )
            
            print(f"Follow-up verification: {is_actually_follow_up}")
            
            signal['verified_follow_up'] = is_actually_follow_up
            if is_actually_follow_up:
                signal['last_consilience_response'] = last_response
    
    print("Liaison Agent analyzing...")
    decision = await liaison_agent_decision(signal, context, session_id)
    
    print(f"Decision: {decision['decision_path']}")
    print(f"Reasoning: {decision['reasoning']}")
    print(f"Missing domains: {decision.get('missing_domains', [])}\n")
    
    if decision['decision_path'] == "PATH_A":
        print("PATH A: Continue monitoring - No response needed\n")
        return
    
    elif decision['decision_path'] == "PATH_C":
        print("PATH C: Request clarification")
        response_text = "I didn't catch that clearly, could you repeat?"
        priority = 'P0'
        
        metadata = {
            'trigger_type': signal.get('trigger_type', 'explicit_request'),
            'priority': priority,
            'domains': [],
            'task_type': 'clarification',
            'liaison_decision': decision,
            'issue_description': decision.get('reasoning', '')
        }
        
    elif decision['decision_path'] == "PATH_B":
        print("PATH B: Generate response")
        priority = 'P0'
        missing_domains = decision.get('missing_domains', [])
        
        if not missing_domains:
            print("WARNING: Liaison chose PATH B but no missing_domains - treating as PATH C")
            response_text = "I'm not sure I understand the question. Could you clarify?"
            
            metadata = {
                'trigger_type': signal.get('trigger_type', 'explicit_request'),
                'priority': priority,
                'domains': [],
                'task_type': 'clarification',
                'liaison_decision': decision,
                'issue_description': 'Unclear question - missing domains not identified'
            }
        else:
            print(f"Calling specialists: {missing_domains}")
            perspectives = await specialist_system.generate_multiple_perspectives(
                domains=missing_domains,
                context=context,
                active_domains=context['active_domains'],
                max_specialists=2
            )
            response_text = specialist_system.format_multi_perspective_response(perspectives)
            
            metadata = {
                'trigger_type': signal.get('trigger_type', 'explicit_request'),
                'priority': priority,
                'domains': missing_domains,
                'task_type': decision.get('task_type', 'provide_perspective'),
                'liaison_decision': decision,
                'issue_description': decision.get('reasoning', '')
            }
    
    else:
        print(f"Unknown path: {decision['decision_path']}\n")
        return
    
    print(f"Generated response ({len(response_text)} chars)")
    context_builder_input(session_id, response_text, metadata)
    print(f"Sent to Context Builder for storage")
    delivery_queue_input(session_id, priority, response_text, signal, decision)
    print(f"Queued as {priority} (immediate delivery)\n")

async def factual_error_detection(context):
    if not context['recent_raw']:
        return None
    
    conversation = "\n".join([
        f"{msg['speaker']}: {msg['text']}"
        for msg in context['recent_raw']
    ])
    
    try:
        response = await client.responses.create(
            model="gpt-5",
            input=FACTUAL_ERROR_DETECTION_PROMPT.format(conversation=conversation),
            reasoning={"effort": "low"},
            text={"verbosity": "low"}
        )
        
        result = json.loads(response.output_text)
        
        if result.get('error_detected'):
            return result
        
        return None
        
    except Exception as e:
        print(f"Error detecting factual errors: {e}")
        return None

async def stuck_signal_detection(context):
    if not context['recent_raw']:
        return None
    
    conversation = "\n".join([
        f"{msg['speaker']}: {msg['text']}"
        for msg in context['recent_raw']
    ])
    
    consilience_history_text = "\n".join([
        f"[{resp['timestamp']}] {resp['text'][:100]}..."
        for resp in context['consilience_history']
    ])
    
    try:
        response = await client.responses.create(
            model="gpt-5",
            input=STUCK_DETECTION_PROMPT.format(
                conversation=conversation,
                consilience_history=consilience_history_text
            ),
            reasoning={"effort": "low"},
            text={"verbosity": "low"}
        )
        
        result = json.loads(response.output_text)
        
        if result.get('stuck_detected'):
            return result
        
        return None
        
    except Exception as e:
        print(f"Error detecting stuck signals: {e}")
        return None

async def background_analysis(session_id):
    print(f"\nTASK 2: Background Analysis")
    print(f"Waiting {BACKGROUND_ANALYSIS_STARTUP_DELAY}s before starting...\n")
    
    await asyncio.sleep(BACKGROUND_ANALYSIS_STARTUP_DELAY)
    
    print(f"Background analysis active (checking every {BACKGROUND_ANALYSIS_INTERVAL}s)\n")
    
    while True:
        try:
            print(f"[Background Check - {datetime.now().strftime('%H:%M:%S')}]")
            
            context = context_builder_state(session_id)
            
            if not context['recent_raw']:
                print("No messages in buffer, skipping\n")
                await asyncio.sleep(BACKGROUND_ANALYSIS_INTERVAL)
                continue
            
            print("Checking for factual errors...")
            error = await factual_error_detection(context)
            
            if error:
                domains_needed = error.get('domains_needed', [])
                issue_desc = error.get('issue_description', error.get('error_description', ''))
                
                if not await deduplication_check(session_id, issue_desc, domains_needed, 'P1'):
                    print(f"P1: Factual error detected - {error['error_description']}")
                    
                    perspectives = await specialist_system.generate_multiple_perspectives(
                        domains=domains_needed,
                        context=context,
                        active_domains=context['active_domains'],
                        max_specialists=2
                    )
                    response_text = f"Quick correction: {error['correct_information']}\n\n"
                    response_text += specialist_system.format_multi_perspective_response(perspectives)
                    
                    metadata = {
                        'trigger_type': 'factual_error',
                        'priority': 'P1',
                        'domains': domains_needed,
                        'task_type': 'factual_correction',
                        'error_info': error,
                        'issue_description': issue_desc
                    }
                    context_builder_input(session_id, response_text, metadata)
                    print(f"Sent P1 response to Context Builder for storage")
                    
                    decision = {
                        'issue_description': issue_desc,
                        'active_domains': context['active_domains'],
                        'missing_domains': domains_needed
                    }
                    delivery_queue_input(session_id, 'P1', response_text, {'type': 'factual_error'}, decision)
                    print(f"Queued as P1 (target delivery: {P1_DELIVERY_TARGET}s)\n")
            
            print("Checking for stuck signals...")
            stuck = await stuck_signal_detection(context)
            
            if stuck:
                domains_needed = stuck.get('domains_needed', [])
                priority = stuck.get('priority', 'P2')
                issue_desc = stuck.get('issue_description', stuck.get('description', ''))
                
                if not await deduplication_check(session_id, issue_desc, domains_needed, priority):
                    print(f"{priority}: Stuck detected - {stuck['stuck_type']}")
                    
                    perspectives = await specialist_system.generate_multiple_perspectives(
                        domains=domains_needed,
                        context=context,
                        active_domains=context['active_domains'],
                        max_specialists=2
                    )
                    response_text = specialist_system.format_multi_perspective_response(perspectives)
                    
                    metadata = {
                        'trigger_type': 'stuck_signal',
                        'priority': priority,
                        'domains': domains_needed,
                        'task_type': 'provide_perspective',
                        'stuck_info': stuck,
                        'issue_description': issue_desc
                    }
                    context_builder_input(session_id, response_text, metadata)
                    print(f"Sent {priority} response to Context Builder for storage")
                    
                    decision = {
                        'issue_description': issue_desc,
                        'active_domains': context['active_domains'],
                        'missing_domains': domains_needed
                    }
                    delivery_queue_input(session_id, priority, response_text, {'type': 'stuck_signal'}, decision)
                    print(f"Queued as {priority} (target delivery: {P2P3_DELIVERY_TARGET}s)\n")
            
            if not error and not stuck:
                print("No issues detected\n")
            
            await asyncio.sleep(BACKGROUND_ANALYSIS_INTERVAL)
            
        except Exception as e:
            print(f"Error in background analysis: {e}\n")
            await asyncio.sleep(BACKGROUND_ANALYSIS_INTERVAL)

async def monitor_triggers(session_id):
    print(f"Task 1: Monitoring direct triggers\n")
    
    while True:
        try:
            result = redis_client.brpop(
                f'orchestrator_triggers:{session_id}',
                timeout=1
            )
            
            if result:
                _, signal_json = result
                signal = json.loads(signal_json)
                await process_trigger(signal, session_id)
            
            await asyncio.sleep(POLL_INTERVAL)
            
        except Exception as e:
            print(f"Error in Task 1: {e}")
            await asyncio.sleep(POLL_INTERVAL)

async def main():
    if len(sys.argv) < 2:
        print("Usage: python orchestrator.py <session_id>")
        sys.exit(1)
    
    session_id = sys.argv[1]
    
    print("="*70)
    print("CONSILIENCE ORCHESTRATOR")
    print("="*70)
    print(f"Session: {session_id}")
    print(f"Task 1: Direct triggers (P0)")
    print(f"  - Wait: {WAIT_FOR_FOLLOWUP_SECONDS}s OR {WAIT_FOR_FOLLOWUP_MESSAGES} messages")
    print(f"  - Follow-up window: {FOLLOW_UP_WINDOW}s")
    print(f"  - Paths: A (no response), B (generate), C (clarify)")
    print(f"Task 2: Background analysis (P1/P2/P3)")
    print(f"  - Startup delay: {BACKGROUND_ANALYSIS_STARTUP_DELAY}s")
    print(f"  - Check interval: {BACKGROUND_ANALYSIS_INTERVAL}s")
    print(f"  - Deduplication: Semantic similarity")
    print("="*70 + "\n")
    
    await asyncio.gather(
        monitor_triggers(session_id),
        background_analysis(session_id)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping Orchestrator")