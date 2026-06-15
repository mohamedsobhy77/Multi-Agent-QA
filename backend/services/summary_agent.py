import json

from backend.services.openrouter_client import OpenRouterClient


class RequirementSummaryAgent:
    def __init__(self) -> None:
        self.client = OpenRouterClient()

    async def generate(self, requirement_text: str):
        prompt = f"""
Act as a Senior Business Analyst and QA Lead.

Analyze ONLY the information explicitly provided in the requirement.

Rules:
- Do NOT invent requirements.
- Do NOT assume business rules that are not stated.
- Do NOT add security, performance, scalability, availability, audit, MFA, session, or password requirements unless explicitly mentioned.
- If information is missing, place it under MissingInformation.
- Base every output item on the provided text only.

Return ONLY valid JSON.
Do not use markdown.
Do not add explanations before or after the JSON.

Requirement:

{requirement_text}
"""

        response = await self.client.chat(prompt)

        response = response.strip()

        if response.startswith("```json"):
            response = response.replace("```json", "", 1)

        if response.endswith("```"):
            response = response[:-3]

        response = response.strip()

        return json.loads(response)