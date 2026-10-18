from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict


def as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


UTCDateTime = Annotated[AwareDatetime, AfterValidator(as_utc)]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
