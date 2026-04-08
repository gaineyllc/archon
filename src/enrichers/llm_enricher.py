"""
LLM Enricher — 100% local via Ollama.
Extracts semantic attributes from file content using local models.
No Anthropic API calls.
"""
from __future__ import annotations
import json
import os
from typing import Any

import httpx


from src.config import (
    OLLAMA_BASE_URL, OLLAMA_SUMMARY_MODEL, OLLAMA_VISION_MODEL,
    OLLAMA_CODE_MODEL, OLLAMA_REASON_MODEL
)

OLLAMA_BASE = OLLAMA_BASE_URL
MODELS = {
    "summary":   OLLAMA_SUMMARY_MODEL,
    "vision":    OLLAMA_VISION_MODEL,
    "code":      OLLAMA_CODE_MODEL,
    "reasoning": OLLAMA_REASON_MODEL,
}


def _ollama_generate(model: str, prompt: str,
                     images: list[str] | None = None,
                     timeout: int = 120) -> str:
    """Call Ollama generate API. images = list of base64-encoded image strings."""
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 512},
    }
    if images:
        payload["images"] = images

    resp = httpx.post(
        f"{OLLAMA_BASE}/api/generate",
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _parse_json_response(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks."""
    import re
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except Exception:
        return {}


# ── Enrichment functions ──────────────────────────────────────────────────────

def enrich_document(text_content: str, file_path: str) -> dict[str, Any]:
    """Extract summary, entities, topics, document type, sentiment from text."""
    prompt = f"""Analyze this document excerpt and return a JSON object with:
- summary: 2-3 sentence summary
- document_type: one of invoice/contract/report/email/memo/article/manual/other
- topics: list of up to 5 key topics
- people: list of person names mentioned
- organizations: list of organization names mentioned
- locations: list of place names mentioned
- sentiment: positive/negative/neutral
- language: ISO 639-1 language code
- action_items: list of any action items or tasks mentioned (max 3)

Document excerpt:
{text_content[:3000]}

Return only valid JSON:"""

    response = _ollama_generate(MODELS["summary"], prompt)
    result = _parse_json_response(response)
    return {
        "summary":       result.get("summary"),
        "document_type": result.get("document_type"),
        "sentiment":     result.get("sentiment"),
        "language":      result.get("language"),
        "_entities": {
            "topics":        result.get("topics", []),
            "people":        result.get("people", []),
            "organizations": result.get("organizations", []),
            "locations":     result.get("locations", []),
        }
    }


def enrich_image_vision(image_path: str) -> dict[str, Any]:
    """Use LLaVA to describe image content, detect objects, mood, scene."""
    import base64
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = """Analyze this image and return a JSON object with:
- description: detailed 2-3 sentence description
- scene_type: one of indoor/outdoor/landscape/portrait/document/screenshot/other
- objects: list of main objects/subjects visible
- people_count: number of people visible (integer)
- text_visible: any text visible in the image
- mood: overall mood/atmosphere
- dominant_colors: list of 3 dominant colors
- is_document: true if this is a photo of a document/screen

Return only valid JSON:"""

    response = _ollama_generate(MODELS["vision"], prompt, images=[img_b64])
    result = _parse_json_response(response)
    return {
        "summary":      result.get("description"),
        "sentiment":    result.get("mood"),
        "_vision": {
            "scene_type":     result.get("scene_type"),
            "objects":        result.get("objects", []),
            "people_count":   result.get("people_count", 0),
            "text_visible":   result.get("text_visible"),
            "dominant_colors": result.get("dominant_colors", []),
            "is_document":    result.get("is_document", False),
        }
    }


def enrich_code(file_path: str, content: str) -> dict[str, Any]:
    """Use qwen2.5-coder to analyze code: purpose, framework, quality signals."""
    prompt = f"""Analyze this code file and return a JSON object with:
- summary: what this code does (1-2 sentences)
- framework: main framework/library used if any
- code_quality: good/fair/poor based on structure
- has_tests: true if this appears to be a test file
- security_concerns: list of any obvious security issues
- topics: list of technical topics/concepts

File: {file_path}
Code:
{content[:2000]}

Return only valid JSON:"""

    response = _ollama_generate(MODELS["code"], prompt)
    result = _parse_json_response(response)
    return {
        "summary":  result.get("summary"),
        "_code": {
            "framework":         result.get("framework"),
            "code_quality":      result.get("code_quality"),
            "has_tests":         result.get("has_tests", False),
            "security_concerns": result.get("security_concerns", []),
            "topics":            result.get("topics", []),
        }
    }


def enrich_binary(file_path: str, props: dict) -> dict[str, Any]:
    """Use reasoning model to assess binary risk and purpose."""
    prompt = f"""Given this Windows executable metadata, return a JSON object with:
- summary: likely purpose of this executable (1-2 sentences)
- risk_assessment: low/medium/high based on metadata
- category: one of system/application/driver/malware_suspect/unknown

Metadata:
{json.dumps(props, indent=2)[:1000]}

Return only valid JSON:"""

    response = _ollama_generate(MODELS["reasoning"], prompt, timeout=60)
    result = _parse_json_response(response)
    return {
        "summary": result.get("summary"),
        "_binary": {
            "risk_assessment": result.get("risk_assessment"),
            "category":        result.get("category"),
        }
    }


def infer_relationships(file_props_a: dict, file_props_b: dict) -> dict[str, Any]:
    """
    Use reasoning model to infer semantic relationships between two files.
    Returns suggested relationship type and confidence.
    """
    prompt = f"""Given two files, determine if there is a meaningful relationship.
Return JSON with:
- relationship: one of REFERENCES/PART_OF/SIMILAR_TO/NONE
- confidence: 0.0 to 1.0
- reason: one sentence explanation

File A: {json.dumps({k: v for k, v in file_props_a.items() if isinstance(v, (str, int, float)) and k in ['name','summary','document_type','topics']}, indent=2)}
File B: {json.dumps({k: v for k, v in file_props_b.items() if isinstance(v, (str, int, float)) and k in ['name','summary','document_type','topics']}, indent=2)}

Return only valid JSON:"""

    response = _ollama_generate(MODELS["reasoning"], prompt, timeout=60)
    return _parse_json_response(response)
