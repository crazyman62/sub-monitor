from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app import db
from app.models import User, Settings
from app.tasks import sync_and_check_expiry
from datetime import datetime

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
        user.package = request.form.get('package')

        expiry_date_str = request.form.get('expiry_date')
        if expiry_date_str:
            try:
                user.expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                pass # Or handle error
        else:
            user.expiry_date = None

        user.do_not_expire = 'do_not_expire' in request.form

        payer_id = request.form.get('payer_id')
        if payer_id and payer_id != 'none':
            user.payer_id = int(payer_id)
        else:
            user.payer_id = None

        db.session.commit()
        flash("User details updated successfully.", "success")
        return redirect(url_for('main.user_details', user_id=user.id))

    return render_template('user_details.html', user=user, all_users=all_users)

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
