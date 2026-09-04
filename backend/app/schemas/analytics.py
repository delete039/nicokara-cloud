from pydantic import BaseModel, Field


class PageviewRequest(BaseModel):
    path: str = Field(min_length=1, max_length=128, pattern=r"^/")
