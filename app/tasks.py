from app import db
from app.models import Settings, User
from app.services.emby import EmbyClient
from datetime import datetime

def sync_and_check_expiry(app):
    """
    Background job to:
    1. Fetch all users from Emby and sync them to the local database.
    2. Check for expired users and disable them via Emby API.
    """
    with app.app_context():
        print(f"[{datetime.utcnow()}] Running hourly sync and expiry check...")

        settings = Settings.query.first()
        if not settings or not settings.emby_url or not settings.emby_api_key:
            print("Emby Settings not configured. Skipping sync.")
            return

        emby = EmbyClient(settings.emby_url, settings.emby_api_key)
        emby_users = emby.get_users()

        if emby_users is None:
            print("Failed to fetch users from Emby. Skipping sync.")
            return

        # Track valid emby user IDs to potentially handle deleted users (optional)
        emby_user_ids = []

        for e_user in emby_users:
            e_id = e_user.get('Id')
            e_username = e_user.get('Name')
            is_disabled = e_user.get('Policy', {}).get('IsDisabled', False)
            iptv_access = e_user.get('Policy', {}).get('EnableLiveTvAccess', True)
            emby_user_ids.append(e_id)

            # Find or create user in DB
            db_user = User.query.filter_by(emby_user_id=e_id).first()
            if not db_user:
                db_user = User(emby_user_id=e_id, username=e_username)
                db.session.add(db_user)
                print(f"Added new user from Emby: {e_username}")
            else:
                db_user.username = e_username

            db_user.is_disabled = is_disabled
            db_user.iptv_is_disabled = not iptv_access

            # Fetch recent activity (lightweight cache)
            # This might add API calls for each user, doing it hourly is acceptable for small servers.
            activity = emby.get_user_activity(e_id)
            if activity:
                if activity['last_login_date']:
                    try:
                        # Emby dates are ISO 8601
                        import dateutil.parser
                        db_user.last_login_date = dateutil.parser.isoparse(activity['last_login_date']).replace(tzinfo=None)
                    except Exception as e:
                        pass

                if activity['last_ip']:
                    db_user.last_ip = activity['last_ip']
                if activity['last_device']:
                    db_user.last_device = activity['last_device']

            # Check VOD Expiry
            if not db_user.vod_do_not_expire and db_user.vod_expiry_date:
                if datetime.utcnow() > db_user.vod_expiry_date:
                    # Expired! Disable if not already disabled
                    if not db_user.is_disabled:
                        print(f"Disabling expired VOD user: {db_user.username}")
                        if emby.disable_user(e_id):
                            db_user.is_disabled = True

            # Check IPTV Expiry
            if not db_user.iptv_do_not_expire and db_user.iptv_expiry_date:
                if datetime.utcnow() > db_user.iptv_expiry_date:
                    # Expired! Disable Live TV if not already disabled
                    if not db_user.iptv_is_disabled:
                        print(f"Disabling Live TV for expired IPTV user: {db_user.username}")
                        if emby.disable_iptv(e_id):
                            db_user.iptv_is_disabled = True

        try:
            db.session.commit()
            print(f"[{datetime.utcnow()}] Sync completed.")
        except Exception as e:
            db.session.rollback()
            print(f"Error during db commit: {e}")
