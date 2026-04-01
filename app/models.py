from app import db
from datetime import datetime

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emby_url = db.Column(db.String(255), nullable=True)
    emby_api_key = db.Column(db.String(255), nullable=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emby_user_id = db.Column(db.String(255), unique=True, nullable=False)
    username = db.Column(db.String(255), nullable=False)

    # Custom fields
    first_name = db.Column(db.String(255), nullable=True)
    last_name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    fb_account = db.Column(db.String(255), nullable=True)
    paypal_account = db.Column(db.String(255), nullable=True)

    # VOD tracking
    vod_expiry_date = db.Column(db.DateTime, nullable=True)
    vod_do_not_expire = db.Column(db.Boolean, default=False)
    vod_had_trial = db.Column(db.Boolean, default=False)

    # IPTV tracking
    iptv_expiry_date = db.Column(db.DateTime, nullable=True)
    iptv_do_not_expire = db.Column(db.Boolean, default=False)
    iptv_had_trial = db.Column(db.Boolean, default=False)
    iptv_is_disabled = db.Column(db.Boolean, default=False) # Sync status from Emby Policy (EnableLiveTvAccess)

    # General Emby Sync Status
    is_disabled = db.Column(db.Boolean, default=False) # Sync status from Emby Policy (IsDisabled)

    # Relationship: Who pays for this user?
    payer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    payer = db.relationship('User', remote_side=[id], backref='paid_users')

    # Emby Activity data (cached for UI)
    last_login_date = db.Column(db.DateTime, nullable=True)
    last_ip = db.Column(db.String(100), nullable=True)
    last_device = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_vod_expired(self):
        if self.vod_do_not_expire:
            return False
        if not self.vod_expiry_date:
            return False
        return datetime.utcnow() > self.vod_expiry_date

    def is_iptv_expired(self):
        if self.iptv_do_not_expire:
            return False
        if not self.iptv_expiry_date:
            return False
        return datetime.utcnow() > self.iptv_expiry_date
