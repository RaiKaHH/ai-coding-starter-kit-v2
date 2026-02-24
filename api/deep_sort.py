"""
API routes for PROJ-8: Deep-AI Smart Sorting.

Endpoints:
  POST /deep-sort/analyse/{file_name} – AI analysis of a single low-confidence file
  POST /deep-sort/analyse-batch       – AI analysis for all unmatched triage items
"""
from fastapi import APIRouter, BackgroundTasks

router = APIRouter()


@router.post("/analyse/{file_name}")
async def analyse_single(file_name: str, source_path: str):
    """Read file content, query AI Gateway, return folder suggestion + reasoning."""
    ...


@router.post("/analyse-batch")
async def analyse_batch(batch_id: str, background_tasks: BackgroundTasks):
    """Process all low-confidence files from a triage batch via AI."""
    ...
