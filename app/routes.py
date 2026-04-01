from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app import db
from app.models import User, Settings
from app.tasks import sync_and_check_expiry
from datetime import datetime, timedelta

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    users = User.query.order_by(User.username).all()
    return render_template('index.html', users=users)

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
        user.first_name = request.form.get('first_name')
        user.last_name = request.form.get('last_name')
        user.email = request.form.get('email')
        user.fb_account = request.form.get('fb_account')
        user.paypal_account = request.form.get('paypal_account')

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

        payer_id = request.form.get('payer_id')
        if payer_id and payer_id != 'none':
            user.payer_id = int(payer_id)
        else:
            user.payer_id = None

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
        db.session.commit()
        flash("Settings saved successfully.", "success")
        return redirect(url_for('main.settings'))

    return render_template('settings.html', setting=setting)

# Context processor to inject the current year into all templates
@bp.context_processor
def inject_now():
    return {'now': datetime.utcnow()}
