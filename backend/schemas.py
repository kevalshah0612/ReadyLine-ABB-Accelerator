"""Validated HTTP and agent boundaries; arbitrary model output never becomes SQL."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Credentials(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)


class NewUser(Credentials):
    role: Literal["supervisor", "planner", "technician"]


class AssetInput(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=100)
    area: str = Field(min_length=1, max_length=80)
    equipment_class: Literal["motor", "pump", "fan", "drive"]
    rated_power: float = Field(gt=0, le=100000)
    duty_cycle: float = Field(ge=0, le=1)
    safety: int = Field(ge=1, le=10)
    production_impact: int = Field(ge=1, le=10)
    hourly_cost: float = Field(ge=0, le=10000000)
    vibration_limit: float = Field(gt=0, le=1000)
    temperature_limit: float = Field(gt=0, le=1000)


class Reading(StrictModel):
    observed_at: datetime
    vibration: float = Field(ge=0, le=1000)
    temperature: float = Field(ge=-100, le=1000)
    load: float = Field(ge=0, le=200)
    source: str = Field(min_length=1, max_length=80)

    @field_validator("observed_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        if value.timestamp() > datetime.now(timezone.utc).timestamp() + 60:
            raise ValueError("Future sensor readings are not accepted")
        return value.astimezone(timezone.utc)


class TelemetryBatch(StrictModel):
    readings: list[Reading] = Field(min_length=1, max_length=1000)
    analyze: bool = False


class PartInput(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    stock: int = Field(ge=0, le=1000000)


class RequiredPart(StrictModel):
    part_id: str = Field(min_length=1, max_length=40)
    quantity: int = Field(ge=1, le=10000)


class ProcedureInput(StrictModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    equipment_class: Literal["motor", "pump", "fan", "drive"]
    title: str = Field(min_length=1, max_length=160)
    duration_hours: float = Field(gt=0, le=168)
    parts: list[RequiredPart] = Field(max_length=30)
    steps: list[str] = Field(min_length=1, max_length=30)
    source: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_parts_and_steps(self):
        if len({p.part_id for p in self.parts}) != len(self.parts):
            raise ValueError("Duplicate part IDs")
        if any(not s.strip() or len(s) > 500 for s in self.steps):
            raise ValueError("Each procedure step must contain 1-500 characters")
        return self


class WindowInput(StrictModel):
    area: str = Field(min_length=1, max_length=80)
    starts_at: datetime
    ends_at: datetime
    production_fraction: float = Field(ge=0, le=1)
    technicians: int = Field(ge=0, le=100)
    permit_ready: bool

    @model_validator(mode="after")
    def validate_interval(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Window timestamps must include timezone")
        self.starts_at = self.starts_at.astimezone(timezone.utc)
        self.ends_at = self.ends_at.astimezone(timezone.utc)
        if self.ends_at <= self.starts_at:
            raise ValueError("End must be after start")
        return self


class FeedbackInput(StrictModel):
    finding: str = Field(min_length=5, max_length=2000)
    actual_hours: float = Field(gt=0, le=168)
    post_vibration: float = Field(ge=0, le=1000)
    completed_steps: list[int] = Field(min_length=1, max_length=30)


class AgentConclusion(StrictModel):
    summary: str = Field(min_length=10, max_length=2000)
    observations: list[str] = Field(min_length=1, max_length=8)
    disposition: Literal["proceed", "escalate"] = Field(
        description="proceed means pass evidence to the next specialist or propose human-reviewed work, never authorization to operate. escalate means evidence is insufficient to form even a bounded proposal or a hard constraint is unmet."
    )
    uncertainty: str = Field(min_length=5, max_length=1000)
