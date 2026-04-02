from sqlalchemy import text

def migrate(app, db):
    with app.app_context():
        print("Starting database migration for new features...")

        commands = [
            "ALTER TABLE user ADD COLUMN vod_expiry_date DATETIME",
            "ALTER TABLE user ADD COLUMN vod_do_not_expire BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN vod_had_trial BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_expiry_date DATETIME",
            "ALTER TABLE user ADD COLUMN iptv_do_not_expire BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_had_trial BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_is_disabled BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN vod_auto_renew BOOLEAN DEFAULT 0",
            "ALTER TABLE user ADD COLUMN iptv_auto_renew BOOLEAN DEFAULT 0",
            "ALTER TABLE settings ADD COLUMN default_vod_price FLOAT DEFAULT 10.0",
            "ALTER TABLE settings ADD COLUMN default_iptv_price FLOAT DEFAULT 10.0",
            "ALTER TABLE settings ADD COLUMN paypal_client_id VARCHAR(255)",
            "ALTER TABLE settings ADD COLUMN paypal_secret VARCHAR(255)",
            "ALTER TABLE settings ADD COLUMN paypal_sandbox BOOLEAN DEFAULT 1",
            "ALTER TABLE user ADD COLUMN custom_vod_price FLOAT",
            "ALTER TABLE user ADD COLUMN custom_iptv_price FLOAT",
            "ALTER TABLE user ADD COLUMN credit_balance FLOAT DEFAULT 0.0",
            "ALTER TABLE payment ADD COLUMN transaction_id VARCHAR(255)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transaction_id ON payment(transaction_id)"
        ]

        try:
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS payment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount FLOAT NOT NULL,
                    method VARCHAR(100) NOT NULL,
                    service_applied VARCHAR(50) NOT NULL,
                    date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    transaction_id VARCHAR(255) UNIQUE,
                    FOREIGN KEY(user_id) REFERENCES user(id)
                )
            """))
        except Exception as e:
            print(f"Error creating payment table: {e}")
            db.session.rollback()

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
    from app import create_app, db
    app = create_app()
    migrate(app, db)
