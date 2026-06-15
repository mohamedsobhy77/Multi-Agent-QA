import asyncio

from backend.services.summary_agent import RequirementSummaryAgent


sample_requirement = """
Login Feature

The user enters email and password.

The system validates credentials.

The user is redirected to dashboard after successful login.

The system displays an error message for invalid credentials.
"""


async def main():
    agent = RequirementSummaryAgent()

    result = await agent.generate(sample_requirement)

    print(result)


if __name__ == "__main__":
    asyncio.run(main())