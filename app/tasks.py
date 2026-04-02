from app import db
from app.models import Settings, User, Payment
from app.services.emby import EmbyClient
from app.services.paypal import PayPalClient
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

def sync_paypal_payments(app, settings, emby=None):
    if not settings.paypal_client_id or not settings.paypal_secret:
        return

    print("Checking PayPal for new payments...")
    try:
        paypal = PayPalClient(settings.paypal_client_id, settings.paypal_secret, settings.paypal_sandbox)

        # Look back 7 days to catch any delayed webhooks/processing
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)

        transactions = paypal.search_transactions(start_date, end_date)

        if not transactions:
            return

        for t in transactions:
            tx_id = t.get('transaction_id')
            amount = t.get('amount')
            payer_email = t.get('payer_email')
            tx_date_str = t.get('date')

            # Check if we already processed this
            existing_payment = Payment.query.filter_by(transaction_id=tx_id).first()
            if existing_payment:
                continue

            print(f"Found new PayPal payment: {tx_id} for ${amount} from {payer_email}")

            # Find matching user
            user = User.query.filter((User.paypal_account == payer_email) | (User.email == payer_email)).first()

            if not user:
                print(f"Could not find matching user for email {payer_email}. Storing payment as unassigned? (Skipping for now)")
                continue

            try:
                tx_date = datetime.strptime(tx_date_str, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
            except (ValueError, TypeError):
                tx_date = datetime.utcnow()

            # Determine eligible services
            vod_eligible = not user.is_disabled or user.vod_auto_renew
            iptv_eligible = not user.iptv_is_disabled or user.iptv_auto_renew

            # If both are disabled and neither has auto_renew, default to restoring whatever had an expiry date
            if not vod_eligible and not iptv_eligible:
                if user.vod_expiry_date:
                    vod_eligible = True
                if user.iptv_expiry_date:
                    iptv_eligible = True

            # Still nothing? default to VOD
            if not vod_eligible and not iptv_eligible:
                vod_eligible = True

            vod_price = user.custom_vod_price if user.custom_vod_price is not None else settings.default_vod_price
            iptv_price = user.custom_iptv_price if user.custom_iptv_price is not None else settings.default_iptv_price

            total_monthly_cost = 0.0
            service_applied = "None"

            if vod_eligible and iptv_eligible:
                total_monthly_cost = vod_price + iptv_price
                service_applied = "Both"
            elif vod_eligible:
                total_monthly_cost = vod_price
                service_applied = "VOD"
            elif iptv_eligible:
                total_monthly_cost = iptv_price
                service_applied = "IPTV"

            # Create payment record
            payment = Payment(
                user_id=user.id,
                amount=amount,
                method="PayPal",
                service_applied=service_applied,
                transaction_id=tx_id,
                date=tx_date
            )
            db.session.add(payment)

            user.credit_balance = (user.credit_balance or 0.0) + amount

            if total_monthly_cost > 0:
                months_to_add = int(user.credit_balance // total_monthly_cost)
                remainder = user.credit_balance % total_monthly_cost

                if months_to_add > 0:
                    user.credit_balance = remainder

                    if vod_eligible:
                        # If service is disabled (or expired in the past), start new time from the transaction date
                        if user.is_disabled or (user.vod_expiry_date and user.vod_expiry_date < tx_date):
                            user.vod_expiry_date = tx_date + relativedelta(months=months_to_add)
                        else:
                            # Active service, append to existing expiry
                            current_expiry = user.vod_expiry_date if user.vod_expiry_date else tx_date
                            user.vod_expiry_date = current_expiry + relativedelta(months=months_to_add)

                        # Re-enable if it was disabled
                        if user.is_disabled and emby:
                            if emby.enable_user(user.emby_user_id):
                                user.is_disabled = False
                                print(f"Re-enabled VOD for {user.username} via PayPal payment.")

                    if iptv_eligible:
                        # If service is disabled (or expired in the past), start new time from the transaction date
                        if user.iptv_is_disabled or (user.iptv_expiry_date and user.iptv_expiry_date < tx_date):
                            user.iptv_expiry_date = tx_date + relativedelta(months=months_to_add)
                        else:
                            # Active service, append to existing expiry
                            current_expiry = user.iptv_expiry_date if user.iptv_expiry_date else tx_date
                            user.iptv_expiry_date = current_expiry + relativedelta(months=months_to_add)

                        # Re-enable if it was disabled
                        if user.iptv_is_disabled and emby:
                            if emby.enable_iptv(user.emby_user_id):
                                user.iptv_is_disabled = False
                                print(f"Re-enabled IPTV for {user.username} via PayPal payment.")

                    print(f"Applied {months_to_add} months to {user.username} for {service_applied}. New Balance: ${remainder}")
                else:
                    print(f"Payment of ${amount} added to {user.username}'s balance (${user.credit_balance}), but not enough for a full month (${total_monthly_cost}).")
            else:
                print(f"Total monthly cost is 0 for {user.username}, added to balance only.")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error checking PayPal payments: {e}")

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

        # Run PayPal Sync
        sync_paypal_payments(app, settings, emby)
