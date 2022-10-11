from typing import Optional
from pydantic import BaseModel				


#properties required during RQ job creation
class RqJobCreate(BaseModel):
	rel_path: str
	crc32_path: int
	status: str
