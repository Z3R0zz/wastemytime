import json
import re
from dataclasses import dataclass

import ollama


@dataclass
class EmailClassification:
    email_uid: str
    importance: str  # critical | important | noise
    confidence: float
    reason: str
    deadline: str | None
    action_required: str
    summary: str


def _build_system_prompt(config: dict) -> str:
    profile = config["profile"]
    care = "\n".join(f"  - {item}" for item in profile["care_about"])
    ignore = "\n".join(f"  - {item}" for item in profile["ignore"])

    return f"""You are an email classifier for a university student. Your job is to classify emails by importance.

STUDENT SITUATION:
{profile['situation']}

TOPICS THE STUDENT CARES ABOUT:
{care}

TOPICS TO IGNORE:
{ignore}

CLASSIFICATION RULES:
- critical  = requires action OR hard deadline within 7 days
- important = relevant and worth knowing, not urgent
- noise     = matches ignore list or irrelevant to student's situation
- Job fairs, career events, employer recruitment emails = ALWAYS noise, no exceptions
- Internship or graduate scheme offers = ALWAYS noise, no exceptions

Respond ONLY with a raw JSON object. No markdown fences. No preamble. No explanation.

JSON schema:
{{
  "importance": "critical|important|noise",
  "confidence": 0.0-1.0,
  "reason": "one short sentence",
  "deadline": "YYYY-MM-DD or null",
  "action_required": "what to do or none",
  "summary": "1-2 sentence plain English summary"
}}"""


def _parse_json_response(text: str) -> dict | None:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None


def classify_email(email_obj, config: dict) -> EmailClassification:
    model = config["ai"].get("model", "qwen2.5:14b-instruct")
    system_prompt = _build_system_prompt(config)

    user_prompt = f"""Subject: {email_obj.subject}
From: {email_obj.sender} <{email_obj.sender_email}>
Body:
{email_obj.body}"""

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.1},
        )
        content = response["message"]["content"]
        parsed = _parse_json_response(content)

        if parsed is None:
            return EmailClassification(
                email_uid=email_obj.uid,
                importance="noise",
                confidence=0.0,
                reason="Failed to parse AI response",
                deadline=None,
                action_required="none",
                summary="Classification failed // treating as noise",
            )

        return EmailClassification(
            email_uid=email_obj.uid,
            importance=parsed.get("importance", "noise"),
            confidence=float(parsed.get("confidence", 0.0)),
            reason=parsed.get("reason", ""),
            deadline=parsed.get("deadline"),
            action_required=parsed.get("action_required", "none"),
            summary=parsed.get("summary", ""),
        )
    except Exception as e:
        return EmailClassification(
            email_uid=email_obj.uid,
            importance="noise",
            confidence=0.0,
            reason=f"AI engine error: {e}",
            deadline=None,
            action_required="none",
            summary="Classification failed // treating as noise",
        )


def generate_weekly_digest(items: list[EmailClassification], config: dict) -> str:
    if not items:
        return "No important emails this week."

    model = config["ai"].get("model", "qwen2.5:14b-instruct")

    items_text = ""
    for item in items:
        items_text += f"- [{item.importance.upper()}] {item.summary}"
        if item.deadline:
            items_text += f" (deadline: {item.deadline})"
        if item.action_required and item.action_required != "none":
            items_text += f" — Action: {item.action_required}"
        items_text += "\n"

    prompt = f"""Write a concise weekly email digest for a student. Include:
1. A one-line overall status
2. Deadlines sorted by urgency
3. Required actions
4. Passive awareness items

Here are the important emails from the past week:
{items_text}

Write in plain text, no markdown. Be brief and actionable."""

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": "You write concise, actionable weekly email digests for students."},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.3},
        )
        return response["message"]["content"]
    except Exception:
        lines = ["Weekly Digest — Fallback (AI unavailable)", ""]
        for item in items:
            line = f"• [{item.importance}] {item.summary}"
            if item.deadline:
                line += f" (deadline: {item.deadline})"
            lines.append(line)
        return "\n".join(lines)
