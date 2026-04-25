from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


def make_review_response_model(max_length: int):
    class DynamicReviewResponse(BaseModel):
        response: str = Field(
            ...,
            min_length=1,
            max_length=max_length,
            description=(
                "Generated customer review text only. "
                f"Must be natural, human-like, and no more than {max_length} characters."
            ),
        )

        model_config = ConfigDict(extra="forbid")

    DynamicReviewResponse.__name__ = f"ReviewResponseMax{max_length}"
    return DynamicReviewResponse
