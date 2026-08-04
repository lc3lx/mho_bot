"""
لوحات المفاتيح للبوت
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from config import Config

class Keyboards:
    """فئة لوحات المفاتيح"""

    @staticmethod
    def remove_reply_keyboard():
        """يشيل أي Reply Keyboard عالقة تحت الشات."""
        return ReplyKeyboardRemove(selective=False)
    
    @staticmethod
    def main_menu():
        """لوحة المفاتيح الرئيسية (كاملة) — تدعم callback أو url"""
        keyboard = []
        for row in Config.MAIN_BUTTONS:
            button_row = []
            for button in row:
                if button.get("url"):
                    url = button["url"]
                    if url == "FACEBOOK_URL":
                        url = Config.FACEBOOK_URL
                    elif url == "TELEGRAM_CHANNEL_URL":
                        url = Config.TELEGRAM_CHANNEL_URL
                    button_row.append(InlineKeyboardButton(text=button["text"], url=url))
                else:
                    button_row.append(InlineKeyboardButton(
                        text=button["text"],
                        callback_data=button["callback"],
                    ))
            keyboard.append(button_row)
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def start_menu():
        """قائمة /start — أزرار عمودية"""
        keyboard = []
        for row in Config.START_MENU_BUTTONS:
            button_row = []
            for button in row:
                if button.get("url"):
                    url = button["url"]
                    if url == "FACEBOOK_URL":
                        url = Config.FACEBOOK_URL
                    button_row.append(InlineKeyboardButton(text=button["text"], url=url))
                else:
                    button_row.append(InlineKeyboardButton(
                        text=button["text"],
                        callback_data=button["callback"],
                    ))
            keyboard.append(button_row)
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def social_links():
        """أزرار روابط الفيسبوك والقناة"""
        keyboard = [
            [InlineKeyboardButton("📱 صفحتنا على الفيسبوك", url=Config.FACEBOOK_URL)],
            [InlineKeyboardButton("📢 قناتنا على التلغرام", url=Config.TELEGRAM_CHANNEL_URL)],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def first_start_consent():
        """زر الموافقة — يظهر لكل من لم يوافق بعد."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "💊 أوافق على الآثار الجانبية",
                callback_data="accept_side_effects",
            )],
        ])

    @staticmethod
    def required_subscription():
        """بوابة الشروط + اشتراك بقناة واحدة فقط"""
        keyboard = [
            [InlineKeyboardButton(
                "📢 انضم للقناة الرسمية",
                url=Config.TELEGRAM_CHANNEL_URL,
            )],
            [InlineKeyboardButton(
                "✅ اشتركت — افتح البوابة",
                callback_data="check_subscription",
            )],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def start_step1():
        """توافق خلفي — توجيه لشاشة إنشاء Ichancy"""
        return Keyboards.ichancy_required_menu()

    @staticmethod
    def deposit_required_menu():
        """توافق خلفي — الشحن لم يعد إجبارياً"""
        return Keyboards.ichancy_required_menu()

    @staticmethod
    def ichancy_required_menu():
        """إجبار إنشاء حساب Ichancy (الشحن اختياري)"""
        keyboard = [
            [InlineKeyboardButton("🎮 بدّي حساب iChancy", callback_data="ichancy_create_start")],
            [InlineKeyboardButton("📥 شحن محفظة البوت (اختياري)", callback_data="deposit")],
            [InlineKeyboardButton("🏆 استخدام كود هدية", callback_data="gift_code")],
            [InlineKeyboardButton("✉️ تواصل مع الدعم", callback_data="contact")],
            [Keyboards.home_btn()],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def ichancy_name_prompt():
        """بداية إنشاء حساب — اسم بسيط فقط"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 سميني انت", callback_data="ichancy_random_name")],
            [InlineKeyboardButton("🏠 رجعني عالمقر", callback_data="main_menu")],
        ])

    @staticmethod
    def ichancy_topup_gate():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ كمّل التعبئة", callback_data="ichancy_topup_know_id")],
            [Keyboards.home_btn()],
        ])

    
    @staticmethod
    def ichancy_menu(linked: bool = False):
        """توافق خلفي — يوجّه لقائمة الحساب"""
        return Keyboards.ichancy_account_menu() if linked else Keyboards.ichancy_required_menu()

    @staticmethod
    def ichancy_create_prompt():
        """زر إنشاء حساب Ichancy فقط"""
        return Keyboards.ichancy_required_menu()

    @staticmethod
    def ichancy_account_menu():
        """قائمة حساب ichancy"""
        site = Config.ICHANCY_CONFIG.get("website_url", "https://www.ichancy.com/")
        keyboard = [
            [InlineKeyboardButton("🌐 فتح موقع ichancy", url=site)],
            [
                InlineKeyboardButton("⬆️ شحن الحساب", callback_data="ichancy_topup_start"),
                InlineKeyboardButton("⬇️ سحب للحساب", callback_data="ichancy_withdraw_start"),
            ],
            [InlineKeyboardButton("🖊️ تغيير كلمة المرور", callback_data="ichancy_change_password")],
            [Keyboards.home_btn()],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def home_btn():
        return InlineKeyboardButton("🏠 رجّعني للمقر", callback_data="main_menu")

    @staticmethod
    def back_to_main():
        """زر العودة لمقر نابليون"""
        return InlineKeyboardMarkup([[Keyboards.home_btn()]])

    @staticmethod
    def extras_menu():
        """🧰 شغلات زيادة"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 لفّة عالفيس", url=Config.FACEBOOK_URL)],
            [InlineKeyboardButton("↩️ رجعلي حوالتي", callback_data="refund_request")],
            [InlineKeyboardButton("🎁 مفاجآت المعلم", callback_data="extras_surprises")],
            [InlineKeyboardButton("📘 فهمني من الآخر", callback_data="terms")],
            [InlineKeyboardButton("⚙️ دبّرلي الإعدادات", callback_data="extras_settings")],
            [InlineKeyboardButton("📢 شو صاير بالمقر", callback_data="extras_news")],
            [InlineKeyboardButton("📸 ورجيني وضعي", callback_data="fun_status_card")],
            [InlineKeyboardButton("🏆 إنجازاتي", callback_data="fun_achievements")],
            [InlineKeyboardButton("📊 تقريري الأسبوعي", callback_data="fun_weekly")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def fun_status_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 شارك بطاقتي", callback_data="fun_status_share")],
            [InlineKeyboardButton("🔄 طلعلي تعليق غيره", callback_data="fun_status_refresh")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def fun_achievement_notify_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 اعرض الإنجاز", callback_data="fun_achievements")],
            [InlineKeyboardButton("🏆 كل إنجازاتي", callback_data="fun_achievements")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def fun_achievements_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="extras_menu")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def fun_weekly_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 شارك التقرير", callback_data="fun_weekly_share")],
            [InlineKeyboardButton("🔄 حدث التقرير", callback_data="fun_weekly")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def fun_receipt_photo_menu(order_id: int = 0):
        rows = []
        if order_id:
            rows.append([
                InlineKeyboardButton(
                    "📸 إيصال للتصوير",
                    callback_data=f"fun_receipt_photo_{order_id}",
                )
            ])
        rows.append([Keyboards.home_btn()])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def admin_fun_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("☕ مزاج يومي", callback_data="admin_fun_moods")],
            [InlineKeyboardButton("💬 تعليقات البطاقة", callback_data="admin_fun_profile")],
            [InlineKeyboardButton("🧾 تعليقات الإيصال", callback_data="admin_fun_receipt")],
            [InlineKeyboardButton("📊 تعليقات التقرير", callback_data="admin_fun_weekly")],
            [InlineKeyboardButton("✨ رسائل نادرة", callback_data="admin_fun_rare")],
            [InlineKeyboardButton("📢 أخبار المقر", callback_data="admin_fun_news")],
            [InlineKeyboardButton("🎖️ الألقاب", callback_data="admin_fun_titles")],
            [InlineKeyboardButton("🔙 لوحة الإدمن", callback_data="admin_panel")],
        ])

    @staticmethod
    def ichancy_withdraw_gate():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ كمّل السحب", callback_data="ichancy_withdraw_continue")],
            [InlineKeyboardButton("📋 شروط السحب", callback_data="ichancy_withdraw_rules")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def wallet_deposit_menu():
        """عبّي محفظتي — طرق الدفع بعد إدخال المبلغ"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 سيرياتيل كاش", callback_data="deposit_syriatel_cash")],
            [InlineKeyboardButton("💠 شام كاش", callback_data="deposit_shamcash")],
            [InlineKeyboardButton("🌐 عملات رقمية", callback_data="deposit_usdt")],
            [InlineKeyboardButton("🧩 طرق تانية", callback_data="deposit_other")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def shamcash_currency_menu():
        """اختيار عملة شام كاش"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💵 دولار", callback_data="shamcash_cur_usd")],
            [InlineKeyboardButton("🇸🇾 ليرة سورية", callback_data="shamcash_cur_syp")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="wallet_deposit_methods")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def shamcash_pay_menu():
        """شاشة التحويل — عنوان + مساعدة رقم العملية"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 نسخ العنوان", callback_data="shamcash_copy_address")],
            [InlineKeyboardButton("🧾 وين بلاقي رقم العملية", callback_data="shamcash_where_tx")],
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_operation")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def shamcash_tx_help_menu():
        """مساعدة مكان رقم العملية"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ فهمت", callback_data="shamcash_tx_help_ok")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="shamcash_tx_help_back")],
        ])

    @staticmethod
    def shamcash_confirm_keyboard():
        """توافق خلفي — التأكيد صار تلقائي بعد رقم العملية"""
        return Keyboards.shamcash_pay_menu()

    @staticmethod
    def wallet_withdraw_gate():
        """توافق — المسار الجديد يبدأ مباشرة من فحص الرصيد."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 اكتب المبلغ", callback_data="withdraw_enter_amount")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def withdraw_empty_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ عبّي محفظتي", callback_data="deposit")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def withdraw_amount_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 اسحب كل الرصيد", callback_data="withdraw_all_balance")],
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_operation")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def withdraw_methods_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 سيرياتيل كاش", callback_data="wd_method_syriatel_cash")],
            [InlineKeyboardButton("💠 شام كاش", callback_data="wd_method_shamcash")],
            [InlineKeyboardButton("🌐 عملات رقمية", callback_data="wd_method_usdt")],
            [InlineKeyboardButton("🧩 طرق ثانية", callback_data="wd_method_other")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="withdraw")],
        ])

    @staticmethod
    def withdraw_crypto_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("USDT · TRC20", callback_data="wd_crypto_USDT_TRC20")],
            [InlineKeyboardButton("USDT · BEP20", callback_data="wd_crypto_USDT_BEP20")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="wallet_withdraw_methods")],
        ])

    @staticmethod
    def withdraw_dest_back_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="wallet_withdraw_methods")],
        ])

    @staticmethod
    def withdraw_review_menu(locked: bool = False):
        if locked:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 فات الطلب عالتنفيذ", callback_data="withdraw_locked")],
                [Keyboards.home_btn()],
            ])
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ أكد السحب", callback_data="withdraw_confirm_submit")],
            [InlineKeyboardButton("✏️ عدل البيانات", callback_data="withdraw_edit_data")],
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="withdraw_abort")],
        ])

    @staticmethod
    def withdraw_submitted_menu(order_id: int, can_cancel: bool = True):
        rows = []
        if can_cancel:
            rows.append([
                InlineKeyboardButton(
                    "↩️ اطلب إلغاء السحب",
                    callback_data=f"wd_cancel_ask_{order_id}",
                )
            ])
        rows.append([
            InlineKeyboardButton("📋 تابع الطلب", callback_data=f"wd_track_{order_id}")
        ])
        rows.append([Keyboards.home_btn()])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def withdraw_cancel_confirm_menu(order_id: int):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ ابعت طلب الإلغاء",
                callback_data=f"wd_cancel_send_{order_id}",
            )],
            [InlineKeyboardButton(
                "❌ لا كمل السحب",
                callback_data=f"wd_cancel_keep_{order_id}",
            )],
        ])

    @staticmethod
    def withdraw_locked_menu(order_id: int):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 تابع الطلب", callback_data=f"wd_track_{order_id}")],
            [InlineKeyboardButton("🚑 الحقني يا دعم", callback_data="contact")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def withdraw_cancelled_done_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 رجعت المصاري للمحفظة", callback_data="main_menu")],
        ])

    @staticmethod
    def withdraw_paid_menu(order_id: int):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 إيصال للتصوير", callback_data=f"fun_receipt_photo_{order_id}")],
            [InlineKeyboardButton("📋 عرض الإيصال", callback_data=f"wd_track_{order_id}")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def withdraw_rejected_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 جرّب من جديد", callback_data="withdraw")],
            [InlineKeyboardButton("🚑 الحقني يا دعم", callback_data="contact")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def admin_withdraw_order_menu(order_id: int):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ تم التقبيض",
                callback_data=f"admin_wd_paid_{order_id}",
            )],
            [InlineKeyboardButton(
                "⚙️ قيد التنفيذ",
                callback_data=f"admin_wd_processing_{order_id}",
            )],
            [InlineKeyboardButton(
                "❌ ارفض السحب",
                callback_data=f"admin_wd_reject_{order_id}",
            )],
        ])

    @staticmethod
    def admin_withdraw_cancel_menu(order_id: int):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✅ وافق على الإلغاء",
                callback_data=f"admin_wd_cancel_ok_{order_id}",
            )],
            [InlineKeyboardButton(
                "❌ ارفض الإلغاء",
                callback_data=f"admin_wd_cancel_no_{order_id}",
            )],
        ])

    @staticmethod
    def withdraw_pending_menu(can_cancel: bool = True):
        """توافق خلفي"""
        if can_cancel:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ انسف الطلب", callback_data="withdraw_cancel_pending")],
                [Keyboards.home_btn()],
            ])
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 فات الطلب عالتنفيذ", callback_data="withdraw_locked")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def wallet_menu():
        """جيبتي"""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ عبّيها", callback_data="deposit"),
                InlineKeyboardButton("🏧 فضّيها", callback_data="withdraw"),
            ],
            [InlineKeyboardButton("🔄 حدّث الرصيد", callback_data="wallet_refresh")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def ledger_menu():
        """دفتر الفضايح"""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💸 عمليات التعبئة", callback_data="history_deposits"),
                InlineKeyboardButton("💰 عمليات السحب", callback_data="history_withdrawals"),
            ],
            [
                InlineKeyboardButton("⏳ العمليات المعلقة", callback_data="history_pending"),
                InlineKeyboardButton("📆 اختيار التاريخ", callback_data="history_by_date"),
            ],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def profile_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تعديل بياناتي", callback_data="profile_edit")],
            [InlineKeyboardButton("🔐 إعدادات الأمان", callback_data="profile_security")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def support_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 عندي مشكلة", callback_data="message_admin")],
            [InlineKeyboardButton("📸 إرسال صورة", callback_data="support_photo")],
            [InlineKeyboardButton("🧾 مشكلة بعملية", callback_data="support_tx_issue")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def gift_code_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 أكوادي السابقة", callback_data="gift_code_history")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def gift_code_retry_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 جرب كود تاني", callback_data="gift_code")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def gift_code_success_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👛 روح عجيبتي", callback_data="gift_balance")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def gift_code_back_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="gift_code")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def guide_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 كيف أعبّي؟", callback_data="guide_deposit")],
            [InlineKeyboardButton("💰 كيف أسحب؟", callback_data="guide_withdraw")],
            [InlineKeyboardButton("👛 كيف تعمل المحفظة؟", callback_data="guide_wallet")],
            [InlineKeyboardButton("🆘 مشكلة شائعة", callback_data="guide_faq")],
            [InlineKeyboardButton("🔞 استخدام مسؤول", callback_data="guide_responsible")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def referral_menu():
        """توافق — يوجّه لقائمة الجيش"""
        return Keyboards.army_menu()

    @staticmethod
    def army_menu():
        """👑 جيش نابليون"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 جنّد رفيق", callback_data="share_referral")],
            [InlineKeyboardButton("👥 أفراد جيشي", callback_data="army_recruits")],
            [InlineKeyboardButton("💰 عمولتي", callback_data="army_commission")],
            [InlineKeyboardButton("📊 كشف العمولات", callback_data="army_ledger")],
            [InlineKeyboardButton("🎖️ رتبتي", callback_data="army_my_rank")],
            [InlineKeyboardButton("🏧 اسحب عمولتي", callback_data="army_withdraw")],
            [InlineKeyboardButton("📜 الشروط بلا فلسفة", callback_data="army_rules")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def army_back_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="referrals")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def army_recruits_nav(page: int, has_prev: bool, has_next: bool):
        rows = []
        nav = []
        if has_prev:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"army_recruits_p_{page - 1}"))
        if has_next:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"army_recruits_p_{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="referrals")])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def army_ledger_nav(page: int, has_prev: bool, has_next: bool):
        rows = []
        nav = []
        if has_prev:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"army_ledger_p_{page - 1}"))
        if has_next:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"army_ledger_p_{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="referrals")])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def army_rules_ack():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع للجيش", callback_data="referrals")],
            [Keyboards.home_btn()],
        ])

    @staticmethod
    def army_wd_amount_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 اسحب كل المتاح", callback_data="army_wd_all")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="referrals")],
        ])

    @staticmethod
    def army_wd_methods_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 سيرياتيل كاش", callback_data="army_wd_method_syriatel_cash")],
            [InlineKeyboardButton("💠 شام كاش", callback_data="army_wd_method_shamcash")],
            [InlineKeyboardButton("🌐 عملات رقمية", callback_data="army_wd_method_usdt")],
            [InlineKeyboardButton("🧩 طرق ثانية", callback_data="army_wd_method_other")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="army_withdraw")],
        ])

    @staticmethod
    def army_wd_crypto_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("USDT · TRC20", callback_data="army_wd_crypto_USDT_TRC20")],
            [InlineKeyboardButton("USDT · BEP20", callback_data="army_wd_crypto_USDT_BEP20")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="army_withdraw")],
        ])

    @staticmethod
    def army_wd_dest_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data="army_withdraw")],
        ])

    @staticmethod
    def army_wd_review_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ أكد السحب", callback_data="army_wd_confirm")],
            [InlineKeyboardButton("✏️ عدل البيانات", callback_data="army_withdraw")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="referrals")],
        ])

    @staticmethod
    def admin_army_wd_menu(order_id: int):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تم التقبيض", callback_data=f"admin_army_wd_pay_{order_id}")],
            [InlineKeyboardButton("❌ ارفض السحب", callback_data=f"admin_army_wd_no_{order_id}")],
        ])

    @staticmethod
    def admin_army_menu():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 كل الإحالات", callback_data="admin_army_invites")],
            [InlineKeyboardButton("🔎 بحث إحالة", callback_data="admin_army_search")],
            [InlineKeyboardButton("⏳ عمولات معلقة", callback_data="admin_army_pending_comm")],
            [InlineKeyboardButton("🎖️ تعديل رتب/نسب", callback_data="admin_army_ranks")],
            [InlineKeyboardButton("⏱ مدة المراجعة (أيام)", callback_data="admin_army_hold")],
            [InlineKeyboardButton("💵 حد أدنى سحب عمولة", callback_data="admin_army_min_withdraw")],
            [InlineKeyboardButton("📈 حد نشاط مؤهل ($)", callback_data="admin_army_min_activity")],
            [InlineKeyboardButton("✅ اعتماد إحالة نشطة", callback_data="admin_army_activate")],
            [InlineKeyboardButton("🔴 رفض إحالة", callback_data="admin_army_reject")],
            [InlineKeyboardButton("➕ تسجيل عمولة يدوية", callback_data="admin_army_accrue")],
            [InlineKeyboardButton("✏️ تعديل عمولة", callback_data="admin_army_adjust")],
            [InlineKeyboardButton("👤 رتبة يدوية لمستخدم", callback_data="admin_army_rank_override")],
            [InlineKeyboardButton("📜 سجل التعديلات", callback_data="admin_army_audit")],
            [InlineKeyboardButton("🔙 لوحة الإدمن", callback_data="admin_panel")],
        ])

    @staticmethod
    def payment_methods(operation_type="deposit"):
        """لوحة مفاتيح طرق الدفع"""
        if operation_type == "deposit":
            return Keyboards.wallet_deposit_menu()

        keyboard = []
        methods = Config.get_payment_methods_buttons()
        for method in methods:
            keyboard.append([InlineKeyboardButton(
                text=method["text"],
                callback_data=f"{operation_type}_{method['method_id']}",
            )])
        keyboard.append([Keyboards.home_btn()])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def cancel_operation(back_callback: str = "cancel_operation"):
        """إلغاء والعودة"""
        keyboard = [
            [InlineKeyboardButton("❌ إلغاء والرجوع", callback_data=back_callback)],
            [Keyboards.home_btn()],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def stage_markup(stage: str):
        """لوحة حسب مرحلة المستخدم"""
        if stage == "ichancy" or stage == "deposit":
            return Keyboards.ichancy_required_menu()
        return Keyboards.start_menu()

    @staticmethod
    def contact_menu():
        return Keyboards.support_menu()

    @staticmethod
    def transaction_history_menu():
        return Keyboards.ledger_menu()

    
    @staticmethod
    def confirm_transaction(transaction_id):
        """لوحة تأكيد المعاملة"""
        keyboard = [
            [
                InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_{transaction_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_{transaction_id}")
            ],
            [Keyboards.home_btn()],
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def admin_panel():
        """لوحة تحكم الإدمن — تحكم كامل"""
        keyboard = [
            [
                InlineKeyboardButton("💰 إضافة رصيد", callback_data="admin_add_balance"),
                InlineKeyboardButton("💸 خصم رصيد", callback_data="admin_deduct_balance"),
            ],
            [
                InlineKeyboardButton("⏳ المعاملات المعلقة", callback_data="admin_view_pending"),
                InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats"),
            ],
            [
                InlineKeyboardButton("✅ موافقة معاملة", callback_data="admin_approve_transaction"),
                InlineKeyboardButton("❌ رفض معاملة", callback_data="admin_reject_transaction"),
            ],
            [
                InlineKeyboardButton("👥 إدارة المستخدمين", callback_data="admin_users"),
                InlineKeyboardButton("ℹ️ معلومات مستخدم", callback_data="admin_user_info"),
            ],
            [
                InlineKeyboardButton("🏆 إنشاء كود جائزة", callback_data="admin_create_gift_code"),
                InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin_broadcast"),
            ],
            [
                InlineKeyboardButton("📩 رسائل الدعم", callback_data="admin_messages"),
                InlineKeyboardButton("💱 أسعار الصرف", callback_data="admin_settings"),
            ],
            [InlineKeyboardButton("🌐 بروكسي Ichancy", callback_data="admin_proxy")],
            [InlineKeyboardButton("👑 جيش نابليون", callback_data="admin_army")],
            [InlineKeyboardButton("🎭 ترفيه المقر", callback_data="admin_fun")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def admin_proxy_menu(enabled: bool = False):
        """إدارة بروكسي Ichancy"""
        keyboard = [
            [InlineKeyboardButton("✏️ تعيين / تغيير البروكسي", callback_data="admin_proxy_set")],
            [InlineKeyboardButton("🧪 اختبار البروكسي الحالي", callback_data="admin_proxy_test")],
        ]
        if enabled:
            keyboard.append(
                [InlineKeyboardButton("🛑 تعطيل البروكسي", callback_data="admin_proxy_disable")]
            )
        keyboard.append(
            [InlineKeyboardButton("🔙 لوحة الإدمن", callback_data="admin_panel")]
        )
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def admin_exchange_rates():
        """أزرار تعديل أسعار الصرف"""
        keyboard = [
            [InlineKeyboardButton("💵 سعر شام كاش (دولار→ل.س)", callback_data="admin_rate_shamcash")],
            [InlineKeyboardButton("🟢 سعر USDT (USDT→ل.س)", callback_data="admin_rate_usdt")],
            [InlineKeyboardButton("🔙 لوحة الإدمن", callback_data="admin_panel")],
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def pagination(current_page, total_pages, callback_prefix):
        """أزرار التنقل بين الصفحات"""
        keyboard = []
        
        if total_pages > 1:
            nav_buttons = []
            
            if current_page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ السابق", 
                                                      callback_data=f"{callback_prefix}_page_{current_page-1}"))
            
            nav_buttons.append(InlineKeyboardButton(f"{current_page}/{total_pages}", 
                                                  callback_data="page_info"))
            
            if current_page < total_pages:
                nav_buttons.append(InlineKeyboardButton("➡️ التالي", 
                                                      callback_data=f"{callback_prefix}_page_{current_page+1}"))
            
            keyboard.append(nav_buttons)
        
        keyboard.append([Keyboards.home_btn()])
        return InlineKeyboardMarkup(keyboard)

    
    @staticmethod
    def jackpot_menu():
        """قائمة الجاكبوت"""
        keyboard = [
            [InlineKeyboardButton("🎲 معلومات الجاكبوت", callback_data="jackpot_info")],
            [InlineKeyboardButton("🏆 آخر الفائزين", callback_data="jackpot_winners")],
            [InlineKeyboardButton("🌐 العب على ichancy.com", callback_data="open_ichancy")],
            [Keyboards.home_btn()],
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def betting_history_menu():
        """قائمة سجل الرهانات"""
        keyboard = [
            [
                InlineKeyboardButton("🎰 رهانات الكازينو", callback_data="casino_bets_history"),
                InlineKeyboardButton("⚽ الرهانات الرياضية", callback_data="sports_bets_history")
            ],
            [
                InlineKeyboardButton("🏆 الأرباح", callback_data="wins_history"),
                InlineKeyboardButton("❌ الخسائر", callback_data="losses_history")
            ],
            [InlineKeyboardButton("📊 إحصائيات شاملة", callback_data="betting_stats")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def casino_games_menu():
        """قائمة ألعاب الكازينو"""
        keyboard = [
            [
                InlineKeyboardButton("🎲 الألعاب السريعة", callback_data="fast_games"),
                InlineKeyboardButton("🃏 ألعاب الطاولة", callback_data="table_games")
            ],
            [
                InlineKeyboardButton("🎰 ماكينات القمار", callback_data="slot_games"),
                InlineKeyboardButton("🎪 الكازينو المباشر", callback_data="live_casino")
            ],
            [InlineKeyboardButton("🌐 العب على ichancy.com", callback_data="open_ichancy")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def sports_betting_menu():
        """قائمة الرهانات الرياضية"""
        keyboard = [
            [
                InlineKeyboardButton("⚽ كرة القدم", callback_data="football_betting"),
                InlineKeyboardButton("🏀 كرة السلة", callback_data="basketball_betting")
            ],
            [
                InlineKeyboardButton("🎾 التنس", callback_data="tennis_betting"),
                InlineKeyboardButton("🏈 رياضات أخرى", callback_data="other_sports")
            ],
            [InlineKeyboardButton("📊 الرهانات المباشرة", callback_data="live_betting")],
            [InlineKeyboardButton("🌐 راهن على ichancy.com", callback_data="open_ichancy")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def promotions_menu():
        """قائمة العروض والمكافآت"""
        keyboard = [
            [
                InlineKeyboardButton("🎰 مكافآت الكازينو", callback_data="casino_bonuses"),
                InlineKeyboardButton("⚽ مكافآت الرياضة", callback_data="sports_bonuses")
            ],
            [
                InlineKeyboardButton("💰 مكافأة الترحيب", callback_data="welcome_bonus"),
                InlineKeyboardButton("🔄 مكافآت يومية", callback_data="daily_bonuses")
            ],
            [InlineKeyboardButton("👑 برنامج VIP", callback_data="vip_program")],
            [InlineKeyboardButton("🌐 احصل على مكافآتك", callback_data="open_ichancy")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def vip_program_menu():
        """قائمة برنامج VIP"""
        keyboard = [
            [InlineKeyboardButton("📊 مستواي الحالي", callback_data="my_vip_level")],
            [InlineKeyboardButton("🎁 مزايا VIP", callback_data="vip_benefits")],
            [InlineKeyboardButton("📈 كيفية الترقية", callback_data="vip_upgrade")],
            [InlineKeyboardButton("🌐 ارتقِ بمستواك", callback_data="open_ichancy")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def support_menu():
        """قائمة الدعم"""
        keyboard = [
            [InlineKeyboardButton("💬 الدردشة المباشرة", callback_data="live_chat")],
            [InlineKeyboardButton("📧 البريد الإلكتروني", callback_data="email_support")],
            [InlineKeyboardButton("❓ الأسئلة الشائعة", callback_data="faq_support")],
            [InlineKeyboardButton("🌐 الدعم على الموقع", callback_data="open_ichancy")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def website_menu():
        """قائمة الموقع"""
        keyboard = [
            [InlineKeyboardButton("🌐 فتح ichancy.com", url="https://www.ichancy.com/")],
            [InlineKeyboardButton("📱 تطبيق الجوال", callback_data="mobile_app")],
            [InlineKeyboardButton("🎁 العروض الحصرية", callback_data="exclusive_offers")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def user_management_menu():
        """قائمة إدارة المستخدمين للإدمن"""
        keyboard = [
            [
                InlineKeyboardButton("💰 إضافة رصيد", callback_data="admin_add_balance"),
                InlineKeyboardButton("💸 خصم رصيد", callback_data="admin_deduct_balance"),
            ],
            [
                InlineKeyboardButton("ℹ️ معلومات مستخدم", callback_data="admin_user_info"),
                InlineKeyboardButton("📊 إحصائيات المستخدمين", callback_data="admin_user_stats"),
            ],
            [
                InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban_user"),
                InlineKeyboardButton("✅ فك حظر مستخدم", callback_data="admin_unban_user"),
            ],
            [InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔙 العودة للوحة الإدمن", callback_data="admin_panel")],
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def pending_transactions_menu():
        """قائمة المعاملات المعلقة للإدمن"""
        keyboard = [
            [
                InlineKeyboardButton("✅ الموافقة على معاملة", callback_data="admin_approve_transaction"),
                InlineKeyboardButton("❌ رفض معاملة", callback_data="admin_reject_transaction")
            ],
            [InlineKeyboardButton("📊 عرض جميع المعاملات المعلقة", callback_data="admin_view_pending")],
            [InlineKeyboardButton("🔙 العودة للوحة الإدمن", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def admin_back_menu():
        """زر العودة للوحة الإدمن"""
        keyboard = [[InlineKeyboardButton("🔙 العودة للوحة الإدمن", callback_data="admin_panel")]]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def cancel_admin_operation():
        """زر إلغاء عملية الإدمن"""
        keyboard = [
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_admin_operation")],
            [InlineKeyboardButton("🔙 العودة للوحة الإدمن", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def syriatel_deposit_menu(has_previous: bool = False):
        """قائمة شحن سيريتل كاش"""
        keyboard = [
            [InlineKeyboardButton("تحويل يدوي (AUTO)", callback_data="syriatel_manual_auto")],
        ]
        if has_previous:
            keyboard.append([
                InlineKeyboardButton("🔄 رقم التاجر السابق", callback_data="syriatel_prev_code")
            ])
        keyboard.append([InlineKeyboardButton("↩️ رجوع", callback_data="deposit")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def syriatel_continue():
        keyboard = [
            [InlineKeyboardButton("متابعة الشحن", callback_data="syriatel_continue")],
            [InlineKeyboardButton("↩️ رجوع", callback_data="deposit_syriatel_cash")],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def syriatel_codes_keyboard(codes):
        keyboard = [[InlineKeyboardButton(code, callback_data=f"syriatel_pick_{code}")] for code in codes]
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_operation")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def saved_accounts_menu():
        """قائمة أنواع الحسابات المحفوظة"""
        keyboard = [
            [InlineKeyboardButton("📱 سيريتل كاش", callback_data="saved_acc_list_syriatel_cash")],
            [InlineKeyboardButton("💳 شام كاش", callback_data="saved_acc_list_shamcash")],
            [InlineKeyboardButton("🔙 العودة", callback_data="full_menu")],
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def saved_accounts_list(account_type: str, accounts, max_n: int):
        """قائمة حسابات محفوظة مع حذف وإضافة"""
        keyboard = []
        for acc in accounts:
            display = acc.account_value
            if len(display) > 22:
                display = display[:10] + "…" + display[-8:]
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 {display}",
                    callback_data=f"saved_acc_del_{acc.id}",
                )
            ])
        if len(accounts) < max_n:
            keyboard.append([
                InlineKeyboardButton(
                    "➕ إضافة جديد",
                    callback_data=f"saved_acc_add_{account_type}",
                )
            ])
        keyboard.append([
            InlineKeyboardButton("🔙 رجوع", callback_data="saved_accounts")
        ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def withdraw_destination_choices(accounts, method: str):
        """اختيار وجهة السحب من المحفوظ أو إدخال يدوي"""
        keyboard = []
        for acc in accounts:
            display = acc.account_value
            if len(display) > 22:
                display = display[:10] + "…" + display[-8:]
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ {display}",
                    callback_data=f"withdraw_use_acc_{acc.id}",
                )
            ])
        keyboard.append([
            InlineKeyboardButton(
                "✍️ إدخال رقم/حساب جديد",
                callback_data=f"withdraw_manual_dest_{method}",
            )
        ])
        keyboard.append([
            InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel_operation")
        ])
        keyboard.append([Keyboards.home_btn()])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def contact_back_menu():
        """زر العودة لقائمة التواصل"""
        keyboard = [[InlineKeyboardButton("🔙 العودة لقائمة التواصل", callback_data="contact")]]
        return InlineKeyboardMarkup(keyboard)

