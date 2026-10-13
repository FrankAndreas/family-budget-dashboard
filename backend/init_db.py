from app.database import SessionLocal, engine
from app import models
from app.seed import seed_admin, seed_categories

# Create tables
models.Base.metadata.create_all(bind=engine)

# Seed initial categories
db = SessionLocal()
created = seed_categories(db)
if created:
    print(f"Created {created} categories")
else:
    print(f"Categories already exist ({db.query(models.Category).count()} found)")
initial_pin = seed_admin(db)
if initial_pin:
    print(f"Created the first parent 'Admin' with INITIAL PIN {initial_pin}. Change it after logging in.")
db.close()
print("Database initialization complete!")
