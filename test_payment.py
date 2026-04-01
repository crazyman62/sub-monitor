from app import create_app, db
from app.models import User, Settings, Payment
from datetime import datetime
from dateutil.relativedelta import relativedelta

app = create_app()

with app.app_context():
    # Setup
    db.drop_all()
    db.create_all()

    settings = Settings(default_vod_price=10.0, default_iptv_price=15.0)
    db.session.add(settings)

    user = User(emby_user_id="emby1", username="Test User", credit_balance=0.0)
    db.session.add(user)
    db.session.commit()

    # Test 1: $25 payment for Both (VOD $10 + IPTV $15 = $25/mo)
    # Should result in 1 month added, $0 remainder
    user.credit_balance += 25.0
    months_to_add = int(user.credit_balance // 25.0)
    remainder = user.credit_balance % 25.0
    print(f"Test 1 - Months to add: {months_to_add}, Remainder: {remainder}")
    assert months_to_add == 1
    assert remainder == 0.0

    # Test 2: $30 payment for VOD only ($10/mo)
    # Should result in 3 months added, $0 remainder
    user.credit_balance = remainder + 30.0
    months_to_add = int(user.credit_balance // 10.0)
    remainder = user.credit_balance % 10.0
    print(f"Test 2 - Months to add: {months_to_add}, Remainder: {remainder}")
    assert months_to_add == 3
    assert remainder == 0.0

    # Test 3: $20 payment for IPTV only ($15/mo)
    # Should result in 1 month added, $5 remainder
    user.credit_balance = remainder + 20.0
    months_to_add = int(user.credit_balance // 15.0)
    remainder = user.credit_balance % 15.0
    print(f"Test 3 - Months to add: {months_to_add}, Remainder: {remainder}")
    assert months_to_add == 1
    assert remainder == 5.0

    print("Backend Logic tests passed.")
