from fastapi import APIRouter

fp_router = APIRouter(
    prefix="/fp",
)

from . import views, models, tasks
#from . import views, models, tasks
