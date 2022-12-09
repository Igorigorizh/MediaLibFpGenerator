from pydantic import BaseModel

class FolderRequestsBody(BaseModel):
    path: str
    fp_flag: str | None = None
    post_proc_flag: str | None = None

class UserBody(BaseModel):

    username: str
    email: str

