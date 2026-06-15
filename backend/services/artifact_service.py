import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.artifact import Artifact


class ArtifactService:
    @staticmethod
    async def create(
        db: AsyncSession,
        session_id: uuid.UUID,
        artifact_type: str,
        content: dict,
        generation_order: int,
    ) -> Artifact:

        artifact = Artifact(
            session_id=session_id,
            artifact_type=artifact_type,
            generation_order=generation_order,
            content=json.dumps(content, ensure_ascii=False),
        )

        db.add(artifact)

        await db.flush()

        return artifact