from sqlalchemy.orm import Session

from schemas.jobs import RqJobCreate
from db.models.jobs import FpContext
#from core.hashing import Hasher
import zlib


def create_new_fp_context(job:RqJobCreate,db:Session):
    fp_context = FpContext(path=job.rel_path,
	path_crc32=zlib.crc32(job.rel_path.encode('utf-8')),
	status=job.status,
        is_active=True,
        )
    db.add(fp_context)
    db.commit()
    db.refresh(fp_context)
    return fp_context