"""شحن رصيد يدوي لمرة واحدة — شغّله على السيرفر داخل مجلد البوت."""
from database import DatabaseManager

TELEGRAM_ID = 841981842
AMOUNT = 2000.0

db = DatabaseManager()
user = db.get_user(TELEGRAM_ID)
if not user:
    raise SystemExit(f"المستخدم {TELEGRAM_ID} غير موجود بقاعدة البيانات")

before = float(user.balance or 0)
ok = db.update_user_balance(
    TELEGRAM_ID,
    AMOUNT,
    transaction_type="manual",
    description=f"إضافة رصيد يدوية {AMOUNT}",
    method="admin",
)
after_user = db.get_user(TELEGRAM_ID)
after = float(after_user.balance or 0) if after_user else None
print(f"ok={ok} before={before} after={after} added={AMOUNT} user={TELEGRAM_ID}")
