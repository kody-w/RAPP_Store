"""
Email Assistant Agent - Smart email drafting with tone analysis and templates

Part of the RAPP Store - https://github.com/kody-w/RAPP_Store
"""

from agents.basic_agent import BasicAgent
import logging
from datetime import datetime


class EmailAssistantAgent(BasicAgent):
    """
    Smart email assistant for drafting professional emails with tone analysis,
    templates, and reply suggestions.
    """

    TEMPLATES = {
        "meeting_request": {
            "name": "Meeting Request",
            "subject": "Meeting Request: {topic}",
            "body": """Hi {recipient_name},

I hope this email finds you well. I would like to schedule a meeting to discuss {topic}.

Would you be available {proposed_time}? The meeting should take approximately {duration}.

Please let me know what works best for your schedule.

Best regards,
{sender_name}"""
        },
        "follow_up": {
            "name": "Follow Up",
            "subject": "Following Up: {topic}",
            "body": """Hi {recipient_name},

I wanted to follow up on our previous conversation regarding {topic}.

{follow_up_details}

Please let me know if you have any questions or need additional information.

Best regards,
{sender_name}"""
        },
        "introduction": {
            "name": "Introduction",
            "subject": "Introduction: {sender_name}",
            "body": """Hi {recipient_name},

My name is {sender_name}, and I'm reaching out to introduce myself.

{introduction_context}

I would love to connect and learn more about {topic}.

Looking forward to hearing from you.

Best regards,
{sender_name}"""
        },
        "thank_you": {
            "name": "Thank You",
            "subject": "Thank You - {topic}",
            "body": """Hi {recipient_name},

I wanted to take a moment to thank you for {reason}.

{additional_thanks}

I truly appreciate your {what_appreciated}.

Best regards,
{sender_name}"""
        },
        "project_update": {
            "name": "Project Update",
            "subject": "Project Update: {project_name}",
            "body": """Hi {recipient_name},

I wanted to provide you with an update on {project_name}.

**Current Status:** {status}

**Key Accomplishments:**
{accomplishments}

**Next Steps:**
{next_steps}

**Timeline:** {timeline}

Please let me know if you have any questions.

Best regards,
{sender_name}"""
        },
        "apology": {
            "name": "Apology",
            "subject": "Apology Regarding {topic}",
            "body": """Hi {recipient_name},

I sincerely apologize for {issue}.

{explanation}

I understand this may have caused {impact}, and I take full responsibility.

To make this right, {resolution}.

Thank you for your understanding.

Best regards,
{sender_name}"""
        }
    }

    TONE_ADJUSTMENTS = {
        "formal": {
            "greeting": "Dear {name},",
            "closing": "Sincerely,",
            "phrases": {
                "I want": "I would like",
                "Can you": "Would you be able to",
                "Thanks": "Thank you",
                "ASAP": "at your earliest convenience",
                "Let me know": "Please inform me",
                "I think": "I believe",
                "Sorry": "I apologize"
            }
        },
        "casual": {
            "greeting": "Hey {name},",
            "closing": "Cheers,",
            "phrases": {
                "I would like": "I'd like",
                "Would you be able to": "Can you",
                "Thank you": "Thanks",
                "at your earliest convenience": "when you get a chance",
                "Please inform me": "Let me know",
                "I believe": "I think"
            }
        },
        "urgent": {
            "greeting": "Hi {name},",
            "closing": "Please respond urgently,",
            "phrases": {
                "when you get a chance": "as soon as possible",
                "Would you be able to": "I need you to",
                "I would like": "I urgently need"
            },
            "prefix": "URGENT: "
        },
        "friendly": {
            "greeting": "Hi {name}!",
            "closing": "Best,",
            "phrases": {}
        }
    }

    def __init__(self):
        self.name = 'EmailAssistant'
        self.metadata = {
            "name": self.name,
            "description": "Smart email drafting assistant with tone analysis, templates, and professional formatting. Draft emails, adjust tone (formal, casual, urgent, friendly), get reply suggestions, and manage templates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action to perform: 'draft' (create new email), 'reply' (suggest reply to email), 'adjust_tone' (modify email tone), 'list_templates' (show available templates), 'use_template' (fill template), 'analyze' (analyze email tone)",
                        "enum": ["draft", "reply", "adjust_tone", "list_templates", "use_template", "analyze"]
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Email recipient name or address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Purpose or main point of the email"
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key points to include in the email"
                    },
                    "tone": {
                        "type": "string",
                        "description": "Desired tone: formal, casual, urgent, friendly",
                        "enum": ["formal", "casual", "urgent", "friendly"]
                    },
                    "email_text": {
                        "type": "string",
                        "description": "Existing email text (for reply, adjust_tone, analyze actions)"
                    },
                    "template_id": {
                        "type": "string",
                        "description": "Template ID to use (for use_template action)"
                    },
                    "template_data": {
                        "type": "object",
                        "description": "Data to fill template placeholders"
                    },
                    "sender_name": {
                        "type": "string",
                        "description": "Sender's name for signature"
                    }
                },
                "required": ["action"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get('action')

        try:
            if action == 'draft':
                return self._draft_email(kwargs)
            elif action == 'reply':
                return self._suggest_reply(kwargs)
            elif action == 'adjust_tone':
                return self._adjust_tone(kwargs)
            elif action == 'list_templates':
                return self._list_templates()
            elif action == 'use_template':
                return self._use_template(kwargs)
            elif action == 'analyze':
                return self._analyze_email(kwargs)
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            logging.error(f"Error in EmailAssistant: {str(e)}")
            return f"Error: {str(e)}"

    def _draft_email(self, params):
        """Draft a new email"""
        recipient = params.get('recipient', 'Recipient')
        subject = params.get('subject', '')
        purpose = params.get('purpose', '')
        key_points = params.get('key_points', [])
        tone = params.get('tone', 'formal')
        sender_name = params.get('sender_name', '[Your Name]')

        if not purpose:
            return "Error: purpose is required for drafting an email"

        tone_config = self.TONE_ADJUSTMENTS.get(tone, self.TONE_ADJUSTMENTS['formal'])
        greeting = tone_config['greeting'].format(name=recipient)
        closing = tone_config['closing']
        prefix = tone_config.get('prefix', '')

        # Build email body
        points_text = ""
        if key_points:
            points_text = "\n\nKey points:\n" + "\n".join(f"• {point}" for point in key_points)

        email_body = f"""{greeting}

{purpose}{points_text}

{closing}
{sender_name}"""

        # Apply tone adjustments
        for old, new in tone_config.get('phrases', {}).items():
            email_body = email_body.replace(old, new)

        if not subject:
            subject = purpose[:50] + "..." if len(purpose) > 50 else purpose

        return f"""📧 Drafted Email

**To:** {recipient}
**Subject:** {prefix}{subject}
**Tone:** {tone.capitalize()}

---

{email_body}

---

**Tips:**
• Review and personalize before sending
• Check all names and details are correct
• Consider adding a specific call-to-action
• Proofread for typos and clarity

**Adjust tone with:**
`action='adjust_tone', email_text='...', tone='casual'`
"""

    def _suggest_reply(self, params):
        """Suggest a reply to an email"""
        email_text = params.get('email_text', '')
        tone = params.get('tone', 'formal')
        sender_name = params.get('sender_name', '[Your Name]')

        if not email_text:
            return "Error: email_text is required for reply action"

        tone_config = self.TONE_ADJUSTMENTS.get(tone, self.TONE_ADJUSTMENTS['formal'])
        greeting = tone_config['greeting'].format(name='[Sender]')
        closing = tone_config['closing']

        # Generate reply suggestions
        return f"""📬 Reply Suggestions

**Original Email:**
```
{email_text[:500]}{'...' if len(email_text) > 500 else ''}
```

**Suggested Reply ({tone.capitalize()} Tone):**

---

{greeting}

Thank you for your email regarding [topic].

[Your response to their main point here]

[Address any questions or action items]

[Next steps or closing thought]

{closing}
{sender_name}

---

**Quick Reply Options:**

1. **Acknowledge & Confirm:**
   "Thank you for the update. I confirm receipt and will review the details."

2. **Request More Info:**
   "Thank you for reaching out. Could you please provide more details about [specific aspect]?"

3. **Schedule Follow-up:**
   "Thanks for this. Let's schedule a call to discuss further. Would [time] work for you?"

4. **Decline Politely:**
   "Thank you for thinking of me. Unfortunately, I'm unable to [request] at this time due to [reason]."
"""

    def _adjust_tone(self, params):
        """Adjust the tone of an existing email"""
        email_text = params.get('email_text', '')
        tone = params.get('tone', 'formal')

        if not email_text:
            return "Error: email_text is required for adjust_tone action"

        tone_config = self.TONE_ADJUSTMENTS.get(tone, self.TONE_ADJUSTMENTS['formal'])

        adjusted_text = email_text

        # Apply phrase replacements
        for old, new in tone_config.get('phrases', {}).items():
            adjusted_text = adjusted_text.replace(old, new)

        return f"""🔄 Tone Adjusted Email

**Original Tone:** [Detected]
**New Tone:** {tone.capitalize()}

---

{adjusted_text}

---

**Tone Characteristics ({tone.capitalize()}):**
• Greeting style: {tone_config['greeting'].format(name='Name')}
• Closing style: {tone_config['closing']}
• Key phrase adjustments applied: {len(tone_config.get('phrases', {}))}

**Available tones:** formal, casual, urgent, friendly
"""

    def _list_templates(self):
        """List all available email templates"""
        response = "📋 Available Email Templates\n\n"

        for template_id, template in self.TEMPLATES.items():
            response += f"**{template['name']}** (`{template_id}`)\n"
            response += f"  Subject: {template['subject']}\n"
            response += f"  Preview: {template['body'][:100]}...\n\n"

        response += """
**Use a template with:**
```
action='use_template',
template_id='meeting_request',
template_data={
    'recipient_name': 'John',
    'topic': 'Q1 Planning',
    'proposed_time': 'Tuesday at 2pm',
    'duration': '30 minutes',
    'sender_name': 'Jane'
}
```
"""
        return response

    def _use_template(self, params):
        """Fill and return a template"""
        template_id = params.get('template_id')
        template_data = params.get('template_data', {})

        if not template_id:
            return "Error: template_id is required. Use list_templates to see available templates."

        if template_id not in self.TEMPLATES:
            return f"Error: Template '{template_id}' not found. Available: {list(self.TEMPLATES.keys())}"

        template = self.TEMPLATES[template_id]

        # Fill template
        subject = template['subject']
        body = template['body']

        for key, value in template_data.items():
            placeholder = "{" + key + "}"
            subject = subject.replace(placeholder, str(value))
            body = body.replace(placeholder, str(value))

        # Find unfilled placeholders
        import re
        unfilled = set(re.findall(r'\{(\w+)\}', body + subject))

        response = f"""📧 Email from Template: {template['name']}

**Subject:** {subject}

---

{body}

---
"""

        if unfilled:
            response += f"\n⚠️ **Unfilled placeholders:** {', '.join(unfilled)}\n"
            response += "Provide these in template_data to complete the email.\n"

        return response

    def _analyze_email(self, params):
        """Analyze an email's tone and characteristics"""
        email_text = params.get('email_text', '')

        if not email_text:
            return "Error: email_text is required for analyze action"

        # Simple analysis
        word_count = len(email_text.split())
        sentence_count = email_text.count('.') + email_text.count('!') + email_text.count('?')
        has_greeting = any(g in email_text.lower() for g in ['dear', 'hi', 'hello', 'hey'])
        has_closing = any(c in email_text.lower() for c in ['regards', 'sincerely', 'best', 'thanks', 'cheers'])
        has_urgent = any(u in email_text.lower() for u in ['urgent', 'asap', 'immediately', 'critical'])
        is_formal = any(f in email_text.lower() for f in ['dear', 'sincerely', 'regards', 'respectfully'])

        # Determine tone
        detected_tone = "formal" if is_formal else "casual"
        if has_urgent:
            detected_tone = "urgent"

        return f"""📊 Email Analysis

**Statistics:**
• Word count: {word_count}
• Sentences: {sentence_count}
• Has greeting: {'Yes' if has_greeting else 'No'}
• Has closing: {'Yes' if has_closing else 'No'}

**Detected Tone:** {detected_tone.capitalize()}

**Tone Indicators:**
• Formal markers: {'Present' if is_formal else 'Not detected'}
• Urgent markers: {'Present' if has_urgent else 'Not detected'}

**Suggestions:**
"""
        suggestions = []
        if not has_greeting:
            suggestions.append("• Add a greeting for a more complete email")
        if not has_closing:
            suggestions.append("• Add a professional closing")
        if word_count > 300:
            suggestions.append("• Consider making the email more concise")
        if sentence_count > 0 and word_count / sentence_count > 25:
            suggestions.append("• Some sentences may be too long - consider breaking them up")

        return response + ("\n".join(suggestions) if suggestions else "• Email looks well-structured!")
