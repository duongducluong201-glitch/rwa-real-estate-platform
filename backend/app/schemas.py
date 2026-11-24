import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel


# 1. Auth & Session Lab Schemas (UC-01)
class LabAccountResponse(BaseModel):
    id: int
    username: Optional[str] = None
    email: Optional[str] = None
    address: str
    role_label: str
    display_name: str
    is_whitelisted: bool
    is_frozen: bool

    class Config:
        from_attributes = True


class SessionLoginRequest(BaseModel):
    address: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class RegisterAccountRequest(BaseModel):
    username: str
    email: str
    password: str
    display_name: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SessionLoginResponse(BaseModel):
    session_token: str
    user: LabAccountResponse


# 2. KYC Schemas (UC-02, UC-03)
class KYCApplicationCreate(BaseModel):
    full_name: str
    id_number: str
    email: Optional[str] = "investor@rwa-lab.vn"
    phone: Optional[str] = "0901234567"
    document_type: Optional[str] = "National ID"
    subject_type: Optional[str] = "Investor"
    doc_cid: Optional[str] = None
    doc_name: Optional[str] = None
    front_image_cid: Optional[str] = None
    back_image_cid: Optional[str] = None
    front_doc_name: Optional[str] = None
    back_doc_name: Optional[str] = None
    front_preview_data_url: Optional[str] = None
    back_preview_data_url: Optional[str] = None
    notes: Optional[str] = None


class KYCDecisionRequest(BaseModel):
    reason: Optional[str] = None
    notes: Optional[str] = None
    checklist: Optional[Dict[str, bool]] = None


class KYCDocumentAccessRequest(BaseModel):
    access_type: str = "VIEW"  # VIEW | DOWNLOAD
    doc_side: str = "front"    # front | back | full
    purpose: Optional[str] = "Thẩm định tài liệu KYC theo phân quyền COMPLIANCE_ROLE"


class KYCHistoryItem(BaseModel):
    id: int
    status: str
    document_type: str
    submitted_at: Optional[datetime.datetime] = None
    reviewed_at: Optional[datetime.datetime] = None
    reviewed_by: Optional[int] = None
    reviewer_name: Optional[str] = None
    reject_reason: Optional[str] = None
    tx_hash: Optional[str] = None


class KYCApplicationResponse(BaseModel):
    id: int
    user_id: int
    investor_address: str
    investor_name: str
    status: str
    payload_json: Dict[str, Any]
    reviewed_by: Optional[int] = None
    reviewer_name: Optional[str] = None
    tx_hash: Optional[str] = None
    reviewed_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    attempt_count: int = 1
    is_latest: bool = True


class KYCApplicationDetailResponse(KYCApplicationResponse):
    history: List[KYCHistoryItem] = []


# 3. Real Estate & Tokenization Schemas (UC-04, UC-05, UC-06, UC-07, UC-14)
class RealEstateCreateRequest(BaseModel):
    name: str
    symbol: str
    address_text: str
    area_m2: float
    property_kind: str = "apartment"  # apartment | land | building
    build_year: int = 2024
    description: Optional[str] = None
    valuation: float
    total_shares: float
    doc_cid: Optional[str] = None
    doc_hash: Optional[str] = None
    doc_name: Optional[str] = None
    doc_type: Optional[str] = None
    doc_size_bytes: Optional[int] = None
    image_url: Optional[str] = None
    gallery_urls: Optional[List[str]] = None
    auto_tokenize: bool = False


class ValuationUpdateRequest(BaseModel):
    new_valuation: float
    notes: Optional[str] = None
    basis: Optional[str] = None


class PrimarySaleOpenRequest(BaseModel):
    real_estate_id: Optional[int] = None
    token_address: Optional[str] = None
    price_per_share: float
    amount: float
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    notes: Optional[str] = None


class PrimarySaleBuyRequest(BaseModel):
    real_estate_id: Optional[int] = None
    token_address: Optional[str] = None
    amount: float
    confirm_email: Optional[str] = None


# 4. Secondary Marketplace & P2P Schemas (UC-10, UC-11)
class P2PTransferRequest(BaseModel):
    token_address: str
    to_address: str
    amount: float


class MarketplaceListRequest(BaseModel):
    token_address: str
    amount: float
    price_per_share: float


class MarketplaceBuyRequest(BaseModel):
    listing_id: int
    amount: float
    confirm_email: Optional[str] = None


class MarketplaceCancelRequest(BaseModel):
    listing_id: int


# 5. Compliance & Admin Emergency Schemas (UC-12, UC-13)
class FreezeAccountRequest(BaseModel):
    token_address: Optional[str] = None
    account_address: str
    frozen: bool
    reason: Optional[str] = None
    case_code: Optional[str] = None
    notes: Optional[str] = None


class PauseTokenRequest(BaseModel):
    token_address: str
    paused: bool
    reason: Optional[str] = None


class ForcedTransferRequest(BaseModel):
    token_address: str
    from_address: str
    to_address: str
    amount: float
    reason: Optional[str] = None
    case_code: Optional[str] = None


class RoleManageRequest(BaseModel):
    contract_name: str = "AssetToken"  # IdentityRegistry | AssetFactory | AssetToken | PrimarySale
    token_address: Optional[str] = None
    role_name: str  # ISSUER_ROLE | COMPLIANCE_ROLE | DEFAULT_ADMIN_ROLE
    account_address: str
    grant: bool = True
    reason: Optional[str] = None


class UserRoleAssignRequest(BaseModel):
    user_id: Optional[int] = None
    account_address: Optional[str] = None
    new_role: str  # admin | issuer | compliance | investor
    sync_onchain: bool = True
    reason: Optional[str] = None


# 6. Payment Gmail OTP Verification Schemas
class PaymentOtpRequest(BaseModel):
    tx_type: str  # PRIMARY_BUY | MARKET_BUY
    target_id: int  # real_estate_id (PRIMARY_BUY) hoặc listing_id (MARKET_BUY)
    amount: float
    email: str


class PaymentOtpConfirmRequest(BaseModel):
    otp_id: str
    otp_code: str
