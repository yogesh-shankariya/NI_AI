from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewResponse(BaseModel):
    response: str = Field(
        ...,
        min_length=1,
        max_length=400,
        description=(
            "Generated customer review text only. "
            "Must be short, natural, and human-like, ideally within 3 to 4 lines. Should not looks like Machine."
        ),
    )

    model_config = {"extra": "forbid"}