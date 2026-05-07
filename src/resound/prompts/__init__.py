"""Versioned prompt templates. Iterate independently of business logic."""

from resound.prompts.classify import CLASSIFY_PROMPT_V1, build_classify_prompt

__all__ = ["CLASSIFY_PROMPT_V1", "build_classify_prompt"]
