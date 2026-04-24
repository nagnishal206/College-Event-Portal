from app import app
from extensions import db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            db.session.execute(text("ALTER TABLE events ADD COLUMN poster VARCHAR(255) DEFAULT 'default_poster.jpg';"))
            db.session.commit()
            print("Events table migrated: added 'poster' column.")
        except Exception as e:
            db.session.rollback()
            print(f"Events table migration failed: {e}")

if __name__ == "__main__":
    migrate()
