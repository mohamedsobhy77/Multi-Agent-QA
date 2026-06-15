import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.models.document import Document
from backend.services.artifact_service import ArtifactService
from backend.services.summary_agent import RequirementSummaryAgent

router = APIRouter(tags=["Artifacts"])


@router.post("/sessions/{session_id}/generate-summary")
async def generate_summary(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.session_id == session_id)
    )

    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    agent = RequirementSummaryAgent()

    summary = await agent.generate(document.raw_text)

    artifact = await ArtifactService.create(
        db=db,
        session_id=session_id,
        artifact_type="REQUIREMENT_SUMMARY",
        content=summary,
        generation_order=1,
    )

    return {
        "artifact_id": str(artifact.id),
        "artifact_type": artifact.artifact_type,
        "summary": summary,
    }