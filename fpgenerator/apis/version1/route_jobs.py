from fastapi import APIRouter
from sqlalchemy.orm import Session
from fastapi import Depends

from schemas.jobs import RqJobCreate
from db.session import get_db
from db.repository.job_fp import create_new_fp_context
from utils.job_create import job_create

router = APIRouter()

@router.post("/")
def create_job(job : RqJobCreate,db: Session = Depends(get_db)):
	rq_job = job_create(job.rel_path)	
	job = create_new_fp_context(job=job,db=db)
	return job