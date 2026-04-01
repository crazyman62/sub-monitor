from app import create_app, db
from sqlalchemy import text

app = create_app()

def migrate():
    with app.app_context():
        # Check if vod_expiry_date column exists
        try:
            db.session.execute(text("SELECT vod_expiry_date FROM user LIMIT 1"))
            print("Database is already up to date.")
            return
        except Exception as e:
            # OperationalError means it doesn't exist. We proceed to migration.
            db.session.rollback()

        print("Starting database migration for VOD and IPTV tracking...")

        commands = [
            "ALTER TABLE user ADD COLUMN vod_expiry_date DATETIME",
            "ALTER TABLE user ADD COLUMN vod_do_not_expire BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN vod_had_trial BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_expiry_date DATETIME",
            "ALTER TABLE user ADD COLUMN iptv_do_not_expire BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_had_trial BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_is_disabled BOOLEAN DEFAULT 0"
        ]

        for cmd in commands:
            try:
                db.session.execute(text(cmd))
            except Exception as e:
                print(f"Skipping (might already exist): {cmd}")
                db.session.rollback()

        print("Migrating existing data based on package types...")

        # Map old 'expiry_date', 'do_not_expire' based on 'package' containing VOD/IPTV
        # Note: Depending on SQLite/SQLAlchemy versions, package and expiry_date might be missing if we recreated tables
        # or we might need to check if they exist first. Assuming they exist from old schema.
        try:
            db.session.execute(text("UPDATE user SET vod_expiry_date = expiry_date, vod_do_not_expire = do_not_expire WHERE package LIKE '%VOD%'"))
            db.session.execute(text("UPDATE user SET iptv_expiry_date = expiry_date, iptv_do_not_expire = do_not_expire WHERE package LIKE '%IPTV%'"))
            db.session.commit()
            print("Data migration completed successfully.")
        except Exception as e:
            db.session.rollback()
            print(f"Failed to migrate data (perhaps old columns are missing): {e}")

if __name__ == "__main__":
    migrate()
