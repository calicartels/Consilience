import asyncio
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

UNIVERSAL_SPECIALIST_PROMPT = """You are a specialist in {domain}, communicating at the level of a PhD researcher explaining to university undergraduates.

CONVERSATION CONTEXT:
{context}

ACTIVE DOMAINS IN DISCUSSION:
Currently being discussed: {active_domains}

PREVIOUS CONSILIENCE CONTRIBUTIONS:
{consilience_history}

YOUR TASK: {task_type}

{task_instructions}

Guidelines:
- Tone: PhD researcher explaining to undergraduates
- Be concise (2-4 sentences maximum)
- Use accessible language - bridge technical concepts with simpler terms
- Avoid jargon dumping - explain specialized terms when used
- Provide practical, actionable insights
- Check the previous Consilience contributions - do NOT repeat what was already said
- Focus on what's MISSING from the current discussion
- If Consilience already addressed this domain, skip it or add NEW value only

Respond with only the perspective (no preamble, no JSON):
"""

TASK_INSTRUCTIONS = {
    'provide_perspective': """
The conversation is missing your perspective from {domain}.
Provide what's missing - what considerations from {domain} should the team be thinking about?
Don't repeat what's already been discussed.
""",
    
    'translate_jargon': """
The conversation used terminology from {source_domain}.
Translate this concept into {domain} terms.
Use analogies and examples that someone from your field would understand.
""",
    
    'fill_gap': """
The conversation has a gap in {domain} knowledge.
Fill this gap by explaining the relevant concepts.
Connect it back to what they're working on.
""",
    
    'factual_correction': """
There's a factual error in the conversation about {domain}.
Provide the correct information clearly and concisely.
Explain why the misconception exists if helpful.
"""
}

class SpecialistSystem:
    def __init__(self):
        pass
    
    def format_context_for_specialist(self, context):
        """Format context for specialist prompt"""
        parts = []
        
        if context.get('summary', {}).get('text'):
            parts.append("Previous Discussion (Summary):")
            parts.append(context['summary']['text'])
            parts.append("")
        
        if context.get('recent_raw'):
            parts.append("Recent Messages:")
            for msg in context['recent_raw'][-5:]:
                parts.append(f"{msg['speaker']}: {msg['text']}")
        
        return "\n".join(parts)
    
    def format_consilience_history(self, context):
        """Format Consilience history to avoid repetition"""
        if not context.get('consilience_history'):
            return "None yet"
        
        parts = []
        for resp in context['consilience_history']:
            parts.append(f"[{resp['timestamp']}] {resp['text'][:100]}...")
        
        return "\n".join(parts)
    
    async def generate_perspective(self, domain, context, active_domains, task_type='provide_perspective', source_domain=None):
        """
        Generate specialist perspective
        
        Parameter choices:
        - model: gpt-4o - Best quality for specialist perspectives
        - temperature: 0.7 - Balanced for natural explanations
        - max_tokens: 300 - Enough for 2-4 well-crafted sentences at undergrad level
        """
        context_text = self.format_context_for_specialist(context)
        consilience_history_text = self.format_consilience_history(context)
        active_domains_text = ", ".join(active_domains) if active_domains else "general discussion"
        
        task_instructions = TASK_INSTRUCTIONS.get(task_type, TASK_INSTRUCTIONS['provide_perspective'])
        task_instructions = task_instructions.format(
            domain=domain,
            source_domain=source_domain or 'another field'
        )
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                temperature=0.7,
                max_completion_tokens=300,
                messages=[{
                    "role": "user",
                    "content": UNIVERSAL_SPECIALIST_PROMPT.format(
                        domain=domain,
                        context=context_text,
                        active_domains=active_domains_text,
                        consilience_history=consilience_history_text,
                        task_type=task_type.replace('_', ' ').title(),
                        task_instructions=task_instructions
                    )
                }]
            )
            
            specialist_response = response.choices[0].message.content.strip()
            
            print(f"Generated {domain} perspective")
            
            return {
                'domain': domain,
                'response': specialist_response,
                'task_type': task_type
            }
            
        except Exception as e:
            print(f"Error generating {domain} perspective: {e}")
            return {
                'domain': domain,
                'response': f"[Error generating {domain} perspective]",
                'task_type': task_type
            }
    
    async def generate_multiple_perspectives(self, domains, context, active_domains, max_specialists=2):
        """Generate perspectives from multiple specialists in parallel"""
        domains_to_activate = domains[:max_specialists]
        
        print(f"Activating {len(domains_to_activate)} specialists: {domains_to_activate}")
        
        tasks = [
            self.generate_perspective(domain, context, active_domains)
            for domain in domains_to_activate
        ]
        
        results = await asyncio.gather(*tasks)
        
        return results
    
    def format_multi_perspective_response(self, perspectives):
        """Format multiple specialist perspectives"""
        if not perspectives:
            return ""
        
        if len(perspectives) == 1:
            return perspectives[0]['response']
        
        parts = []
        for p in perspectives:
            parts.append(f"From a {p['domain']} perspective:")
            parts.append(p['response'])
            parts.append("")
        
        return "\n".join(parts).strip()