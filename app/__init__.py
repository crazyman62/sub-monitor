from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
import os
import atexit

db = SQLAlchemy()
scheduler = BackgroundScheduler()

def create_app():
    app = Flask(__name__)

    # Configure Database
    db_path = os.environ.get('DATABASE_PATH', 'sqlite:////data/emby_manager.db')
    # If running locally without docker
    if not os.path.exists('/data'):
        db_path = 'sqlite:///emby_manager.db'

    app.config['SQLALCHEMY_DATABASE_URI'] = db_path
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key-change-in-production')

    db.init_app(app)

    with app.app_context():
        from . import models
        db.create_all()

        # Run database migrations for old schemas
        try:
            from migrate_db import migrate
            migrate(app, db)
        except Exception as e:
            print(f"Migration failed: {e}")

        # Start Scheduler if not already running
        if not scheduler.running:
            from app.tasks import sync_and_check_expiry
            scheduler.add_job(func=lambda: sync_and_check_expiry(app), trigger="interval", hours=1)
            scheduler.start()

            # Shut down the scheduler when exiting the app
            atexit.register(lambda: scheduler.shutdown())

    from .routes import bp as main_bp
    app.register_blueprint(main_bp)

    return app
