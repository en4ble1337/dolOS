"""Skills routes for listing and invoking registered skills."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["skills"])


class SkillInfo(BaseModel):
    """Metadata for a registered skill."""
    name: str
    skill_schema: dict[str, Any]


class SkillListResponse(BaseModel):
    """Response listing all registered skills."""
    skills: list[SkillInfo]
    count: int


class SkillInvokeRequest(BaseModel):
    """Request body for invoking a skill."""
    arguments: dict[str, Any] = {}
    trace_id: str | None = None


class SkillInvokeResponse(BaseModel):
    """Response from a skill invocation."""
    skill: str
    result: str
    success: bool


def _get_executor(request: Request):
    executor = getattr(request.app.state, "skill_executor", None)
    if executor is None:
        raise HTTPException(status_code=503, detail="SkillExecutor not configured")
    return executor


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(request: Request) -> SkillListResponse:
    """List all registered skills with their schemas."""
    executor = _get_executor(request)
    registry = executor.registry

    skills = [
        SkillInfo(name=name, skill_schema=registry.get_schema(name))
        for name in registry.get_all_skill_names()
    ]

    return SkillListResponse(skills=skills, count=len(skills))


@router.post("/skills/{name}/invoke", response_model=SkillInvokeResponse)
async def invoke_skill(
    name: str,
    body: SkillInvokeRequest,
    request: Request,
) -> SkillInvokeResponse:
    """Invoke a registered skill by name with the provided arguments."""
    executor = _get_executor(request)

    # Check the skill exists before trying to execute
    try:
        executor.registry.get_skill(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    result = await executor.execute(name, body.arguments, trace_id=body.trace_id)

    # Determine success: executor returns error strings on failure
    success = not (isinstance(result, str) and result.startswith(("Error:", "Timeout Error:", "Execution Error")))

    return SkillInvokeResponse(
        skill=name,
        result=str(result),
        success=success,
    )
