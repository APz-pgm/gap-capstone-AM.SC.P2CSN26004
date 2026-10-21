"""
schema.py - what a valid model reply looks like (the Pydantic model).

These are the six output fields from the project brief. Nothing the model
returns is used until it passes this model.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SignificantEvent(BaseModel):
    timestamp: str = Field(min_length=10, max_length=40)
    description: str = Field(min_length=3, max_length=300)


class Analysis(BaseModel):
    overall_assessment: Literal["potentially_significant", "no_significant_sequence"]
    risk_level: Literal["low", "medium", "high"]
    significant_events: list[SignificantEvent] = Field(max_length=50)
    explanation: str = Field(min_length=10, max_length=2000)
    forensic_relevance: str = Field(min_length=10, max_length=1000)
    investigator_questions: list[str] = Field(max_length=10)

    @model_validator(mode="after")
    def check_consistency(self):
        """The fields must agree with each other, not just have the right types."""
        if self.overall_assessment == "no_significant_sequence":
            if self.significant_events:
                raise ValueError("no_significant_sequence cannot list significant events")
            if self.risk_level != "low":
                raise ValueError("no_significant_sequence must have risk_level low")
        else:
            if not self.significant_events:
                raise ValueError("potentially_significant must list the events")
        return self
