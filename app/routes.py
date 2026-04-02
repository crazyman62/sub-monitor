from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app import db
from app.models import User, Settings, Payment
from app.tasks import sync_and_check_expiry
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import uuid

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    users = User.query.order_by(User.username).all()
    settings = Settings.query.first()

    # Analytics Calculations
    active_vod_count = User.query.filter_by(is_disabled=False).count()
    active_iptv_count = User.query.filter_by(iptv_is_disabled=False).count()

    # Revenue for current month
    now = datetime.utcnow()
    start_of_month = datetime(now.year, now.month, 1)
    monthly_payments = Payment.query.filter(Payment.date >= start_of_month).all()

    vod_revenue = 0.0
    iptv_revenue = 0.0

    for payment in monthly_payments:
        if payment.service_applied == 'VOD':
            vod_revenue += payment.amount
        elif payment.service_applied == 'IPTV':
            iptv_revenue += payment.amount
        elif payment.service_applied == 'Both':
            # Split proportionally based on default prices if we don't know the exact split
            default_vod = settings.default_vod_price if settings else 10.0
            default_iptv = settings.default_iptv_price if settings else 10.0
            total_default = default_vod + default_iptv

            if total_default > 0:
                vod_revenue += payment.amount * (default_vod / total_default)
                iptv_revenue += payment.amount * (default_iptv / total_default)
            else:
                vod_revenue += payment.amount / 2
                iptv_revenue += payment.amount / 2

    return render_template('index.html', users=users, active_vod_count=active_vod_count, active_iptv_count=active_iptv_count, vod_revenue=vod_revenue, iptv_revenue=iptv_revenue)

@bp.route('/sync', methods=['POST'])
def sync_now():
    sync_and_check_expiry(current_app)
    flash("Manual sync completed.", "success")
    return redirect(url_for('main.index'))

@bp.route('/user/<int:user_id>', methods=['GET', 'POST'])
def user_details(user_id):
    user = User.query.get_or_404(user_id)
    all_users = User.query.filter(User.id != user_id).order_by(User.username).all()

    if request.method == 'POST':
        # Determine which action/form was submitted
        is_payment = 'payment_amount' in request.form
        is_toggle = 'toggle_vod' in request.form or 'toggle_iptv' in request.form

        if not is_payment and not is_toggle:
            user.first_name = request.form.get('first_name')
            user.last_name = request.form.get('last_name')
            user.email = request.form.get('email')
            user.fb_account = request.form.get('fb_account')
            user.paypal_account = request.form.get('paypal_account')

            # Pricing overrides
            try:
                cvp = request.form.get('custom_vod_price')
                user.custom_vod_price = float(cvp) if cvp else None
            except (ValueError, TypeError):
                user.custom_vod_price = None

            try:
                cip = request.form.get('custom_iptv_price')
                user.custom_iptv_price = float(cip) if cip else None
            except (ValueError, TypeError):
                user.custom_iptv_price = None

            # Determine expiry dates (VOD and IPTV)
            vod_expiry = request.form.get('vod_expiry_date')
            if vod_expiry:
                try:
                    user.vod_expiry_date = datetime.strptime(vod_expiry, '%Y-%m-%dT%H:%M')
                except ValueError:
                    pass
            else:
                user.vod_expiry_date = None

            iptv_expiry = request.form.get('iptv_expiry_date')
            if iptv_expiry:
                try:
                    user.iptv_expiry_date = datetime.strptime(iptv_expiry, '%Y-%m-%dT%H:%M')
                except ValueError:
                    pass
            else:
                user.iptv_expiry_date = None

            # Handle do_not_expire
            user.do_not_expire = request.form.get('do_not_expire') == 'on'
            user.iptv_do_not_expire = request.form.get('iptv_do_not_expire') == 'on'

        # Emby Client instantiation for toggles
        settings = Settings.query.first()
        emby = None
        if settings and settings.emby_url and settings.emby_api_key:
            from app.services.emby import EmbyClient
            emby = EmbyClient(settings.emby_url, settings.emby_api_key)

        # Handle Toggles
        if 'toggle_vod' in request.form:
            if emby:
                if user.is_disabled:
                    if emby.enable_user(user.emby_user_id):
                        user.is_disabled = False
                        flash("VOD Account manually enabled.", "success")
                    else:
                        flash("Failed to enable VOD Account in Emby.", "danger")
                else:
                    if emby.disable_user(user.emby_user_id):
                        user.is_disabled = True
                        flash("VOD Account manually disabled.", "success")
                    else:
                        flash("Failed to disable VOD Account in Emby.", "danger")
                db.session.commit()
            else:
                flash("Emby not configured, cannot toggle.", "danger")
            return redirect(url_for('main.user_details', user_id=user.id))

        if 'toggle_iptv' in request.form:
            if emby:
                if user.iptv_is_disabled:
                    if emby.enable_iptv(user.emby_user_id):
                        user.iptv_is_disabled = False
                        flash("Live TV access manually enabled.", "success")
                    else:
                        flash("Failed to enable Live TV access in Emby.", "danger")
                else:
                    if emby.disable_iptv(user.emby_user_id):
                        user.iptv_is_disabled = True
                        flash("Live TV access manually disabled.", "success")
                    else:
                        flash("Failed to disable Live TV access in Emby.", "danger")
                db.session.commit()
            else:
                flash("Emby not configured, cannot toggle.", "danger")
            return redirect(url_for('main.user_details', user_id=user.id))

        if not is_payment and not is_toggle:
            # Trial Logic Check First
            trial_type = request.form.get('start_trial')
            override_trial = request.form.get('override_trial') == 'true'

            if trial_type == 'vod':
                if user.vod_had_trial and not override_trial:
                    return {"require_override": "vod"}, 400
                user.vod_expiry_date = datetime.utcnow() + timedelta(days=7)
                user.vod_had_trial = True
                db.session.commit()
                flash("Started 7-day VOD trial.", "success")
                return redirect(url_for('main.user_details', user_id=user.id))

            if trial_type == 'iptv':
                if user.iptv_had_trial and not override_trial:
                    return {"require_override": "iptv"}, 400
                user.iptv_expiry_date = datetime.utcnow() + timedelta(days=7)
                user.iptv_had_trial = True
                db.session.commit()
                flash("Started 7-day IPTV trial.", "success")
                return redirect(url_for('main.user_details', user_id=user.id))

            vod_expiry_date_str = request.form.get('vod_expiry_date')
            if vod_expiry_date_str:
                try:
                    user.vod_expiry_date = datetime.strptime(vod_expiry_date_str, '%Y-%m-%dT%H:%M')
                except ValueError:
                    pass
            else:
                user.vod_expiry_date = None

            iptv_expiry_date_str = request.form.get('iptv_expiry_date')
            if iptv_expiry_date_str:
                try:
                    user.iptv_expiry_date = datetime.strptime(iptv_expiry_date_str, '%Y-%m-%dT%H:%M')
                except ValueError:
                    pass
            else:
                user.iptv_expiry_date = None

            user.vod_do_not_expire = 'vod_do_not_expire' in request.form
            user.iptv_do_not_expire = 'iptv_do_not_expire' in request.form

            user.vod_auto_renew = 'vod_auto_renew' in request.form
            user.iptv_auto_renew = 'iptv_auto_renew' in request.form

            payer_id = request.form.get('payer_id')
            if payer_id and payer_id != 'none':
                user.payer_id = int(payer_id)
            else:
                user.payer_id = None

        # Handle New Payment
        if is_payment:
            try:
                amount = float(request.form.get('payment_amount', 0))
                method = request.form.get('payment_method')
                service_applied = request.form.get('service_applied')
                payment_date_str = request.form.get('payment_date')

                payment_date = datetime.utcnow()
                if payment_date_str:
                    try:
                        payment_date = datetime.strptime(payment_date_str, '%Y-%m-%dT%H:%M')
                    except ValueError:
                        pass

                if amount > 0:
<<<<<<< feature/paypal-integration-6173929968939190067
                    transaction_id = f"Manual-{uuid.uuid4()}"
                    payment = Payment(user_id=user.id, amount=amount, method=method, service_applied=service_applied, transaction_id=transaction_id)
=======
                    payment = Payment(user_id=user.id, amount=amount, method=method, service_applied=service_applied, date=payment_date)
>>>>>>> feature/emby-manager-13838444456425977904
                    db.session.add(payment)

                    user.credit_balance = (user.credit_balance or 0.0) + amount

                    vod_price = user.custom_vod_price if user.custom_vod_price is not None else (settings.default_vod_price if settings else 10.0)
                    iptv_price = user.custom_iptv_price if user.custom_iptv_price is not None else (settings.default_iptv_price if settings else 10.0)

                    cost_per_month = 0.0
                    if service_applied == 'VOD':
                        cost_per_month = vod_price
                    elif service_applied == 'IPTV':
                        cost_per_month = iptv_price
                    elif service_applied == 'Both':
                        cost_per_month = vod_price + iptv_price

                    if cost_per_month > 0:
                        months_to_add = int(user.credit_balance // cost_per_month)
                        remainder = user.credit_balance % cost_per_month

                        if months_to_add > 0:
                            now = datetime.utcnow()
                            if service_applied in ['VOD', 'Both']:
                                current_vod_expiry = user.vod_expiry_date if user.vod_expiry_date and user.vod_expiry_date > now else now
                                user.vod_expiry_date = current_vod_expiry + relativedelta(months=months_to_add)

                            if service_applied in ['IPTV', 'Both']:
                                current_iptv_expiry = user.iptv_expiry_date if user.iptv_expiry_date and user.iptv_expiry_date > now else now
                                user.iptv_expiry_date = current_iptv_expiry + relativedelta(months=months_to_add)

                            user.credit_balance = remainder
                            flash(f"Payment recorded. Added {months_to_add} month(s) to {service_applied}. Remaining credit: ${remainder:.2f}", "success")
                        else:
                            flash(f"Payment recorded. Credit balance (${user.credit_balance:.2f}) is not enough for a full month of {service_applied} (${cost_per_month:.2f}).", "info")
                    else:
                        flash("Cost per month is $0, cannot calculate extension.", "warning")
            except ValueError:
                flash("Invalid payment amount.", "danger")

        db.session.commit()
        flash("User details updated successfully.", "success")
        return redirect(url_for('main.user_details', user_id=user.id))

    # Fetch dynamic activity from Emby
    emby_activity = {}
    past_activity = []
    settings = Settings.query.first()
    if settings and settings.emby_url and settings.emby_api_key:
        from app.services.emby import EmbyClient
        emby = EmbyClient(settings.emby_url, settings.emby_api_key)
        activity = emby.get_user_activity(user.emby_user_id)
        if activity:
            emby_activity = activity
            if activity.get('current_playing'):
                # Also save last_device and last_ip dynamically here if active
                if not user.last_device and activity.get('last_device'):
                    user.last_device = activity['last_device']
                if not user.last_ip and activity.get('last_ip'):
                    user.last_ip = activity['last_ip']
                db.session.commit()
        past_activity = emby.get_past_activity(user.emby_user_id)

    return render_template('user_details.html', user=user, all_users=all_users, emby_activity=emby_activity, past_activity=past_activity)

@bp.route('/user/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    settings = Settings.query.first()

    if settings and settings.emby_url and settings.emby_api_key:
        from app.services.emby import EmbyClient
        emby = EmbyClient(settings.emby_url, settings.emby_api_key)
        # Attempt to delete from Emby
        if emby.delete_user(user.emby_user_id):
            flash(f"User {user.username} deleted from Emby.", "success")
        else:
            flash(f"Failed to delete {user.username} from Emby. They may have already been deleted.", "warning")

    # Delete from local DB regardless
    db.session.delete(user)
    db.session.commit()
    flash("User deleted from local database.", "info")
    return redirect(url_for('main.index'))

@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    setting = Settings.query.first()
    if not setting:
        setting = Settings()
        db.session.add(setting)

    if request.method == 'POST':
        setting.emby_url = request.form.get('emby_url')
        setting.emby_api_key = request.form.get('emby_api_key')

        try:
            setting.default_vod_price = float(request.form.get('default_vod_price', 10.0))
            setting.default_iptv_price = float(request.form.get('default_iptv_price', 10.0))
        except ValueError:
            flash("Invalid price values. Defaults kept.", "warning")

        setting.paypal_client_id = request.form.get('paypal_client_id')
        setting.paypal_secret = request.form.get('paypal_secret')
        setting.paypal_sandbox = 'paypal_sandbox' in request.form

        db.session.commit()
        flash("Settings saved successfully.", "success")
        return redirect(url_for('main.settings'))

    return render_template('settings.html', setting=setting)

# Context processor to inject the current year into all templates
@bp.context_processor
def inject_now():
    return {'now': datetime.utcnow()}
