import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.base import UserRole
from app.models.user import User, Merchant


def get_or_create_merchant_by_whatsapp_id(db: Session, wa_id: str) -> Merchant:
    """
    A merchant's first contact with TaskAm is a WhatsApp message, not a
    signup form. On first message from an unrecognized WhatsApp ID, we
    auto-provision a minimal User+Merchant pair (unverified, with an
    unusable random password) so a Task can be attached to someone. The
    merchant can later set a real password via /auth to get dashboard
    access, or an admin can verify them.
    """
    merchant = db.query(Merchant).filter(Merchant.whatsapp_id == wa_id).first()
    if merchant:
        return merchant

    user = User(
        phone_number=f"+{wa_id}" if not wa_id.startswith("+") else wa_id,
        password_hash=hash_password(str(uuid.uuid4())),  # unusable placeholder
        full_name="WhatsApp Merchant",
        role=UserRole.MERCHANT,
        is_verified=False,
    )
    db.add(user)
    try:
        db.flush()
        merchant = Merchant(user_id=user.id, whatsapp_id=wa_id)
        db.add(merchant)
        db.flush()
        return merchant
    except IntegrityError:
        # Lost a race with a concurrent webhook delivery for the same
        # sender — roll back our attempt and use the row that won.
        db.rollback()
        merchant = db.query(Merchant).filter(Merchant.whatsapp_id == wa_id).first()
        if merchant is None:
            raise
        return merchant
