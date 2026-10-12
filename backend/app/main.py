from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from . import models, database, api
from .seed import seed_categories
from .migrate import add_missing_columns

models.Base.metadata.create_all(bind=database.engine)
add_missing_columns(database.engine)

# Make sure a fresh database has categories; transactions can't be created without one
with database.SessionLocal() as db:
    seed_categories(db)

app = FastAPI(
    title="Family Budget Dashboard API", description="Backend for the Family Budget Dashboard", version="0.1.0"
)

app.include_router(api.router, prefix="/api/v1")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency removed from here, imported from database


@app.get("/")
async def root():
    return {"message": "Welcome to the Family Budget Dashboard API"}


@app.get("/health")
async def health_check(db: Session = Depends(database.get_db)):
    return {"status": "ok", "db": "connected"}
