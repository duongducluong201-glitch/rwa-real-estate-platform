import datetime
import uuid
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
    Numeric,
    Boolean,
    ForeignKey,
    JSON,
)
from .database import Base


class User(Base):
    """Bảng 1: USERS — Lưu trữ tài khoản người dùng (Đăng ký/Đăng nhập + địa chỉ ví EOA trên Anvil)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(60), unique=True, index=True, nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(256), nullable=True)
    private_key = Column(String(128), nullable=True)
    address = Column(String(42), unique=True, index=True, nullable=False)
    role_label = Column(String(30), nullable=False, default="investor")  # admin | issuer | compliance | investor
    display_name = Column(String(100), nullable=False)
    is_whitelisted = Column(Boolean, default=False, nullable=False)
    is_frozen = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class SessionModel(Base):
    """Bảng 2: SESSIONS — Quản lý phiên đăng nhập thực nghiệm (Session Lab)."""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(128), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KYCApplication(Base):
    """Bảng 3: KYC_APPLICATIONS — Hồ sơ đăng ký KYC off-chain của Nhà đầu tư."""
    __tablename__ = "kyc_applications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)  # pending | approved | rejected | revoked
    payload_json = Column(JSON, nullable=False)  # full_name, id_number, email, doc_cid, doc_name...
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    tx_hash = Column(String(66), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RealEstate(Base):
    """Bảng 4: REAL_ESTATES — Thông tin bất động sản, tài liệu IPFS và địa chỉ AssetToken."""
    __tablename__ = "real_estates"

    id = Column(Integer, primary_key=True, index=True)
    token_address = Column(String(42), unique=True, index=True, nullable=True)
    name = Column(String(120), nullable=False)
    symbol = Column(String(20), nullable=False)
    address_text = Column(Text, nullable=False)
    area_m2 = Column(Numeric(12, 2), nullable=False, default=100.0)
    property_kind = Column(String(40), nullable=False, default="apartment")  # apartment | land | building
    build_year = Column(Integer, nullable=True, default=2024)
    description = Column(Text, nullable=True)
    valuation = Column(Numeric(36, 6), nullable=False)
    total_shares = Column(Numeric(36, 18), nullable=False)
    doc_cid = Column(String(100), nullable=False)
    doc_hash = Column(String(66), nullable=False)
    status = Column(String(30), default="ready_to_tokenize", nullable=False)  # draft | ready_to_tokenize | tokenized | open_sale
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AuditSign(Base):
    """Bảng 5: AUDIT_SIGNS — Nhật ký kiểm toán 100% giao dịch ký phía máy chủ (Server-side Signing)."""
    __tablename__ = "audit_signs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    signer_address = Column(String(42), nullable=False)
    role_label = Column(String(30), nullable=False)
    contract_method = Column(String(60), nullable=False)
    params_json = Column(JSON, nullable=False)
    tx_hash = Column(String(66), nullable=False)
    signed_at = Column(DateTime, default=datetime.datetime.utcnow)


class PrimarySaleCache(Base):
    """Bảng 6: PRIMARY_SALES_CACHE — Bộ nhớ đệm trạng thái đợt bán sơ cấp."""
    __tablename__ = "primary_sales_cache"

    id = Column(Integer, primary_key=True, index=True)
    real_estate_id = Column(Integer, ForeignKey("real_estates.id"), nullable=False, index=True)
    token_address = Column(String(42), nullable=False, index=True)
    price_per_share = Column(Numeric(36, 6), nullable=False)
    total_amount = Column(Numeric(36, 18), nullable=False)
    remaining_amount = Column(Numeric(36, 18), nullable=False)
    is_open = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ListingCache(Base):
    """Bảng 7: LISTINGS_CACHE — Bộ nhớ đệm các lệnh niêm yết ký quỹ trên Marketplace."""
    __tablename__ = "listings_cache"

    listing_id = Column(Integer, primary_key=True, autoincrement=False)
    real_estate_id = Column(Integer, ForeignKey("real_estates.id"), nullable=False)
    token_address = Column(String(42), nullable=False, index=True)
    seller_address = Column(String(42), nullable=False)
    initial_amount = Column(Numeric(36, 18), nullable=False)
    remaining_amount = Column(Numeric(36, 18), nullable=False)
    price_per_share = Column(Numeric(36, 6), nullable=False)
    status = Column(String(20), default="open", nullable=False)  # open | filled | cancelled
    tx_hash = Column(String(66), nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class TransferCache(Base):
    """Bảng 8: TRANSFERS_CACHE — Lịch sử biến động quyền sở hữu đồng bộ từ sự kiện on-chain."""
    __tablename__ = "transfers_cache"

    id = Column(Integer, primary_key=True, index=True)
    tx_hash = Column(String(66), index=True, nullable=False)
    block_number = Column(BigInteger, nullable=False, default=0)
    event_type = Column(String(30), nullable=False)  # MINT | PRIMARY_BUY | P2P | MARKET_BUY | FORCED_TRANSFER
    token_address = Column(String(42), index=True, nullable=False)
    from_address = Column(String(42), nullable=False)
    to_address = Column(String(42), nullable=False)
    amount = Column(Numeric(36, 18), nullable=False)
    usdc_paid = Column(Numeric(36, 6), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Notification(Base):
    """Bảng 9: NOTIFICATIONS — Thông báo thời gian thực cho Nhà đầu tư / Issuer / Compliance."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(30), nullable=False, default="system")  # kyc | freeze | dividend | system
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    tx_hash = Column(String(66), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DividendDistribution(Base):
    """Bảng 10: DIVIDEND_DISTRIBUTIONS — Đợt phân phối cổ tức / doanh thu cho thuê BĐS (mUSDC)."""
    __tablename__ = "dividend_distributions"

    id = Column(Integer, primary_key=True, index=True)
    real_estate_id = Column(Integer, ForeignKey("real_estates.id"), nullable=False, index=True)
    token_address = Column(String(42), nullable=False, index=True)
    asset_symbol = Column(String(20), nullable=False)
    period_label = Column(String(120), nullable=False)
    total_amount_usdc = Column(Numeric(36, 6), nullable=False)
    total_eligible_shares = Column(Numeric(36, 18), nullable=False)
    recipients_count = Column(Integer, nullable=False, default=0)
    distributed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DividendPayout(Base):
    """Bảng 11: DIVIDEND_PAYOUTS — Chi tiết từng giao dịch trả cổ tức mUSDC on-chain cho từng Nhà đầu tư."""
    __tablename__ = "dividend_payouts"

    id = Column(Integer, primary_key=True, index=True)
    distribution_id = Column(Integer, ForeignKey("dividend_distributions.id"), nullable=False, index=True)
    investor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    investor_address = Column(String(42), nullable=False, index=True)
    shares_held = Column(Numeric(36, 18), nullable=False)
    ownership_pct = Column(Numeric(12, 6), nullable=False)
    payout_usdc = Column(Numeric(36, 6), nullable=False)
    tx_hash = Column(String(66), nullable=False)
    status = Column(String(20), nullable=False, default="SUCCESS")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class EmailLog(Base):
    """Bảng 12: EMAIL_LOGS — Nhật ký kiểm toán gửi Email biên lai thanh toán MockUSDC qua Gmail SMTP."""
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    recipient_email = Column(String(255), nullable=False, index=True)
    tx_hash = Column(String(66), nullable=False, index=True)
    tx_type = Column(String(40), nullable=False, default="PRIMARY_BUY")  # PRIMARY_BUY | MARKET_BUY | MARKET_SELL
    subject = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="sent")  # sent | failed
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class PaymentOTP(Base):
    """Bảng 13: PAYMENT_OTPS — Mã OTP 6 số (băm SHA-256) xác thực thanh toán MockUSDC trước khi ký on-chain."""
    __tablename__ = "payment_otps"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    otp_hash = Column(String(64), nullable=False)  # SHA-256 hex digest (không lưu plaintext)
    tx_type = Column(String(20), nullable=False)  # PRIMARY_BUY | MARKET_BUY
    payload_json = Column(JSON, nullable=False)  # target_id, amount, expected_total_usdc, token_address...
    attempts = Column(Integer, nullable=False, default=0)  # Tối đa 5 lần nhập sai
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending | verified | expired | failed
    expires_at = Column(DateTime, nullable=False)  # Hết hạn sau 5 phút
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
