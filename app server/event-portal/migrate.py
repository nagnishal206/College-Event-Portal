from app import app
from extensions import db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            db.session.execute(text("ALTER TABLE users ADD COLUMN registration_number VARCHAR(50) UNIQUE;"))
            db.session.execute(text("ALTER TABLE users ADD COLUMN gender VARCHAR(20);"))
            db.session.execute(text("ALTER TABLE users ADD COLUMN mobile_number VARCHAR(20);"))
            db.session.execute(text("ALTER TABLE users ADD COLUMN profile_photo VARCHAR(255) DEFAULT 'default.png';"))
            db.session.commit()
            print("Users table migrated.")
        except Exception as e:
            db.session.rollback()
            print(f"Users table migration failed: {e}")

        try:
            db.session.execute(text("ALTER TABLE pending_otps ADD COLUMN registration_number VARCHAR(50);"))
            db.session.execute(text("ALTER TABLE pending_otps ADD COLUMN gender VARCHAR(20);"))
            db.session.execute(text("ALTER TABLE pending_otps ADD COLUMN mobile_number VARCHAR(20);"))
            db.session.commit()
            print("PendingOtps table migrated.")
        except Exception as e:
            db.session.rollback()
            print(f"PendingOtps table migration failed: {e}")

if __name__ == "__main__":
    migrate()
