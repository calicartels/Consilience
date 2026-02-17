# Specialists Module

Domain expert perspective generation system with PhD-to-undergraduate communication style.

## Architecture

**Universal Prompt System**: Single flexible prompt template for all domains
**Parallel Generation**: Multiple specialists called simultaneously via asyncio.gather
**Anti-repetition**: Checks Consilience history to avoid redundancy
**Task-specific Instructions**: Four task types with tailored guidance
**Concise Output**: 2-4 sentence responses at undergraduate level

## Purpose

The Specialists module generates domain-specific perspectives when the Orchestrator identifies missing expertise. It:

1. **Receives requests** from Orchestrator with domain list and context
2. **Generates perspectives** using universal specialist prompt
3. **Maintains consistent tone**: PhD researcher → undergraduate student
4. **Checks history** to avoid repeating what Consilience already said
5. **Returns formatted output** for delivery

The Specialists do NOT make decisions about when to speak or which domains are needed. The Orchestrator handles all strategic decisions.

## Setup

Install dependencies:
```bash
python -m pip install openai python-dotenv
```

Create `.env` file with:
```
OPENAI_API_KEY=your_openai_api_key
```

## Configuration

### LLM Settings
- **Model**: `gpt-4o` - Highest quality for domain expertise
- **Temperature**: `0.7` - Balanced for natural explanations
- **Max Tokens**: `300` - Enough for 2-4 well-crafted sentences
- **Max Specialists**: `2` - Limit concurrent perspectives per response

### Supported Domains (18)
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

## Components

### SpecialistSystem Class

Main class for generating domain perspectives.

**Methods:**

#### generate_perspective(domain, context, active_domains, task_type, source_domain)
Generates single specialist perspective:
- Takes domain name (e.g., "Biology / Life Sciences")
- Receives full conversation context
- Gets list of currently active domains
- Uses task-specific instructions
- Returns perspective as dict with domain, response, task_type

**Parameters:**
- `domain`: The specialist's domain of expertise
- `context`: Dict with `summary` and `recent_raw` messages
- `active_domains`: List of domains currently in discussion
- `task_type`: One of 4 task types (default: 'provide_perspective')
- `source_domain`: For 'translate_jargon' task (optional)

#### generate_multiple_perspectives(domains, context, active_domains, max_specialists=2)
Generates perspectives from multiple specialists in parallel:
- Takes list of domains to activate
- Limits to `max_specialists` (default: 2)
- Calls specialists concurrently using asyncio.gather
- Returns list of perspective dicts

**Why parallel?**: Reduces total response time from 2-3s per specialist to ~2-3s for all specialists combined.

#### format_multi_perspective_response(perspectives)
Formats multiple perspectives into readable output:
- Single perspective: Returns text directly
- Multiple perspectives: Adds "From a {domain} perspective:" headers
- Joins with blank lines for readability

**Example output**:
```
From a Biology / Life Sciences perspective:
DNA replication occurs in the nucleus through a semi-conservative process. Helicase unwinds the double helix, and DNA polymerase synthesizes new complementary strands. This ensures genetic information is accurately copied during cell division.

From a Chemistry / Biochemistry perspective:
The replication process involves breaking hydrogen bonds between base pairs and forming new phosphodiester bonds. The energy for these reactions comes from ATP and dNTP hydrolysis. The fidelity of replication depends on Watson-Crick base pairing rules (A-T, G-C).
```

#### format_context_for_specialist(context)
Formats conversation context for specialist prompt:
- Includes previous summary (if available)
- Adds recent messages (last 5)
- Formats as readable text with speaker labels

#### format_consilience_history(context)
Formats Consilience history for anti-repetition:
- Shows recent Consilience contributions
- Truncates to first 100 chars per response
- Enables specialist to avoid repetition

## Task Types

### 1. provide_perspective (Default)
**When**: Missing perspective in conversation
**Instructions**: "The conversation is missing your perspective from {domain}. Provide what's missing - what considerations should the team be thinking about? Don't repeat what's already been discussed."

**Example**: Biology perspective on DNA replication when team discussing chemistry only

### 2. translate_jargon
**When**: Cross-domain terminology confusion
**Instructions**: "The conversation used terminology from {source_domain}. Translate this concept into {domain} terms. Use analogies and examples that someone from your field would understand."

**Example**: Translating computer science "recursion" concept into mathematics terminology

### 3. fill_gap
**When**: Missing foundational knowledge
**Instructions**: "The conversation has a gap in {domain} knowledge. Fill this gap by explaining the relevant concepts. Connect it back to what they're working on."

**Example**: Explaining enzyme kinetics when team discussing metabolism without biochemistry background

### 4. factual_correction
**When**: Factual error detected in domain
**Instructions**: "There's a factual error in the conversation about {domain}. Provide the correct information clearly and concisely. Explain why the misconception exists if helpful."

**Example**: Correcting "DNA has 3 bases" error

## Universal Specialist Prompt

The system uses a single prompt template for all domains and tasks:

**Key Elements:**
1. **Role Assignment**: "You are a specialist in {domain}"
2. **Communication Level**: "PhD researcher explaining to university undergraduates"
3. **Context Provision**: Full conversation context
4. **Active Domains**: Currently discussed topics
5. **Consilience History**: Previous contributions (anti-repetition)
6. **Task Instructions**: Task-specific guidance
7. **Guidelines**: Tone, length, accessibility requirements

**Guidelines:**
- Tone: PhD researcher → undergraduates
- Length: 2-4 sentences maximum
- Accessible language: Bridge technical concepts with simpler terms
- Avoid jargon dumping: Explain specialized terms when used
- Practical insights: Actionable information
- Check history: Don't repeat Consilience
- Focus on missing: What's NOT already discussed

## Usage

### Direct Usage (from Orchestrator)
```python
from SPECIALISTS.specialists import SpecialistSystem

specialist_system = SpecialistSystem()

# Generate single perspective
perspective = await specialist_system.generate_perspective(
    domain="Biology / Life Sciences",
    context=context_dict,
    active_domains=["Chemistry / Biochemistry"],
    task_type="provide_perspective"
)

# Generate multiple perspectives (parallel)
perspectives = await specialist_system.generate_multiple_perspectives(
    domains=["Biology / Life Sciences", "Chemistry / Biochemistry"],
    context=context_dict,
    active_domains=["Physics / Astronomy"],
    max_specialists=2
)

# Format for delivery
response_text = specialist_system.format_multi_perspective_response(perspectives)
```

## Anti-repetition Strategy

Specialists check Consilience history to avoid redundancy:

1. **History Provided**: Last 5 Consilience responses in prompt
2. **Explicit Instruction**: "Check previous contributions - do NOT repeat"
3. **Focus on Missing**: "Focus on what's MISSING from current discussion"
4. **Skip if Covered**: "If already addressed, skip or add NEW value only"

**Example**:
- Previous: Consilience explained DNA structure
- Current: Asked about DNA replication
- Specialist: Focuses on replication process, assumes structure knowledge

## Communication Style

### PhD → Undergraduate Level

**Not too simple**: Avoid patronizing or overly basic explanations
**Not too complex**: Avoid assuming graduate-level background
**Bridge concepts**: Connect technical ideas to accessible analogies
**Define jargon**: Explain specialized terms when necessary

**Good Example**:
"DNA replication uses semi-conservative copying, meaning each new double helix keeps one original strand. This ensures accuracy - like keeping a master copy while making duplicates. The enzyme DNA polymerase does the heavy lifting, reading the template and adding complementary nucleotides."

**Too Simple** (avoid):
"DNA copies itself. It makes two copies from one."

**Too Complex** (avoid):
"The replisome complex, comprising helicase, primase, and DNA polymerase holoenzyme with sliding clamp processivity factors, executes bidirectional replication fork progression at approximately 1000 nucleotides per second in prokaryotes."

### Length Constraint

**Target**: 2-4 sentences
**Why**: Brief interventions maintain conversation flow
**Focus**: One key insight, not comprehensive overview

## Performance

- **Single Perspective**: ~2-3s with GPT-4o
- **Multiple Perspectives (Parallel)**: ~2-3s total for 2 specialists
- **Token Usage**: ~200-300 completion tokens per perspective
- **Quality**: GPT-4o provides authoritative, well-crafted explanations
- **Consistency**: Universal prompt ensures consistent tone across domains

## Integration

### Called By Orchestrator

**Task 1 (Direct Triggers - P0)**:
```python
# Liaison Agent identifies missing_domains
perspectives = await specialist_system.generate_multiple_perspectives(
    domains=missing_domains,
    context=context,
    active_domains=context['active_domains'],
    max_specialists=2
)
response_text = specialist_system.format_multi_perspective_response(perspectives)
```

**Task 2 (Background Analysis - P1/P2/P3)**:
```python
# Error or stuck detection identifies domains_needed
perspectives = await specialist_system.generate_multiple_perspectives(
    domains=domains_needed,
    context=context,
    active_domains=context['active_domains'],
    max_specialists=2
)
# For P1 factual errors, prepend correction
response_text = f"Quick correction: {correct_info}\n\n{formatted_perspectives}"
```

## Notes

The Specialists module is designed for quality over speed. Using GPT-4o ensures domain expertise feels authoritative and well-explained, critical for user trust in an academic research assistant. The PhD-to-undergraduate communication level strikes the right balance - sophisticated enough for researchers, accessible enough for broader teams. The universal prompt system with task-specific instructions allows flexible deployment across all domains and situations while maintaining consistent tone and quality. Anti-repetition checking prevents Consilience from sounding redundant or annoying, a key requirement for natural conversation participation.

