from fastapi import APIRouter

fp_router = APIRouter(
    prefix="/fp",
)

cdtoc_router = APIRouter(
    prefix="/cdtoc",
)


from . import views, models, tasks
#from . import views, models, tasks
