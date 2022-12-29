from pydantic import BaseModel, validator
from pathlib import Path

class FolderRequestsBody(BaseModel):
    path: str
    fp_flag: str | None = None
    cdtoc_flag: str | None = None
    post_proc_flag: str | None = None
    
    @validator("path")
    @classmethod  # Optional, but your linter may like it.
    def check_path_type(cls, value):
        if value == "":
            raise ValueError("Path is not provided")
        if Path(value).is_dir():
            raise ValueError("Path is not of posix type")
        return value

class UserBody(BaseModel):

    username: str
    email: str

