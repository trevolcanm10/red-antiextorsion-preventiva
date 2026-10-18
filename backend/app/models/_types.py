from enum import StrEnum

from sqlalchemy import Enum, ForeignKey


def enum_type(cls: type[StrEnum], name: str) -> Enum:
    """Persist the documented enum values rather than Python member names."""
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


def fk(target: str) -> ForeignKey:
    """All ownership/history references prohibit cascading writes."""
    return ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")
