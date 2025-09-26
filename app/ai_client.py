#!/usr/bin/env python3
"""
Handles the creation of Google Generative AI models, ensuring no Vertex AI paths are used.
"""
import os
import google.generativeai as genai

PRIMARY = os.getenv("AI_PRIMARY_MODEL", "gemini-1.5-flash")
FALLBACK = os.getenv("AI_FALLBACK_MODEL", "gemini-1.5-flash") # Defaulting to flash as 8b is not a public model name

def _sanitize(model_id: str) -> str:
    """Prevents any Vertex AI paths from being used."""
    if not model_id or model_id.startswith("projects/"):
        return "gemini-1.5-flash"
    return model_id

def make_model(api_key: str, use_fallback: bool = False) -> genai.GenerativeModel:
    """Creates a GenerativeModel instance with the given API key."""
    genai.configure(api_key=api_key)
    model_id = _sanitize(FALLBACK if use_fallback else PRIMARY)
    return genai.GenerativeModel(model_id)