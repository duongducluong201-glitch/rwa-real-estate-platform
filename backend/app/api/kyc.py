import csv
import io
import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..services.w3_compat import Web3
from ..database import get_db
from ..models import User, KYCApplication, AuditSign, RealEstate
from ..schemas import (
    KYCApplicationCreate,
    KYCApplicationResponse,
    KYCApplicationDetailResponse,
    KYCHistoryItem,
    KYCDecisionRequest,
    KYCDocumentAccessRequest,
)
from ..services.auth import get_current_user
from ..services.ipfs import upload_to_ipfs, store_encrypted_kyc_document, read_encrypted_kyc_document
from ..services.signer import SignerService, get_contract_instance
from .notifications import create_notification

router = APIRouter(prefix="/kyc", tags=["2. Quản lý KYC & Whitelist (UC-02, UC-03)"])


def _get_latest_kyc_for_user(db: Session, user_id: int) -> Optional[KYCApplication]:
    """Lấy đúng 01 bản ghi KYC mới nhất (theo id DESC) của user_id (bỏ qua bản ghi placeholder 'none')."""
    return (
        db.query(KYCApplication)
        .filter(KYCApplication.user_id == user_id, KYCApplication.status != "none")
        .order_by(KYCApplication.id.desc())
        .first()
    )


def _get_user_attempt_stats(db: Session, user_id: int) -> tuple[int, Optional[int]]:
    """Trả về (attempt_count, latest_id) của user_id."""
    row = (
        db.query(
            func.count(KYCApplication.id),
            func.max(KYCApplication.id),
        )
        .filter(KYCApplication.user_id == user_id, KYCApplication.status != "none")
        .first()
    )
    if not row:
        return 0, None
    return int(row[0] or 0), (int(row[1]) if row[1] is not None else None)


def _format_kyc_app(
    app_obj: KYCApplication,
    db: Session,
    attempt_count: Optional[int] = None,
    is_latest: Optional[bool] = None,
) -> KYCApplicationResponse:
    investor = db.query(User).filter(User.id == app_obj.user_id).first()
    reviewer = db.query(User).filter(User.id == app_obj.reviewed_by).first() if app_obj.reviewed_by else None
    if attempt_count is None or is_latest is None:
        cnt, latest_id = _get_user_attempt_stats(db, app_obj.user_id)
        if attempt_count is None:
            attempt_count = max(1, cnt)
        if is_latest is None:
            is_latest = (latest_id == app_obj.id) if latest_id is not None else True

    return KYCApplicationResponse(
        id=app_obj.id,
        user_id=app_obj.user_id,
        investor_address=investor.address if investor else "",
        investor_name=investor.display_name if investor else "",
        status=app_obj.status,
        payload_json=app_obj.payload_json or {},
        reviewed_by=app_obj.reviewed_by,
        reviewer_name=reviewer.display_name if reviewer else None,
        tx_hash=app_obj.tx_hash,
        reviewed_at=app_obj.reviewed_at,
        created_at=app_obj.created_at,
        attempt_count=attempt_count,
        is_latest=is_latest,
    )


def _append_kyc_history_log(
    payload: Dict[str, Any],
    action: str,
    previous_status: str,
    new_status: str,
    operator: User,
    reason: str = "",
    notes: str = "",
    tx_hash: Optional[str] = None,
) -> Dict[str, Any]:
    updated = dict(payload or {})
    logs = list(updated.get("history_logs") or [])
    logs.insert(
        0,
        {
            "id": f"HIST-{len(logs) + 1}-{int(datetime.datetime.utcnow().timestamp())}",
            "action": action,
            "previous_status": previous_status,
            "new_status": new_status,
            "reason": reason,
            "notes": notes,
            "operator_name": operator.display_name,
            "operator_address": operator.address,
            "tx_hash": tx_hash,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        },
    )
    updated["history_logs"] = logs
    return updated


ALLOWED_KYC_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
MAX_KYC_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/upload-document")
async def upload_kyc_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Mã hóa AES-256-GCM và lưu tài liệu KYC vào kho KYC Vault bảo mật (không phơi bày ra /ipfs công khai)."""
    filename = (file.filename or "kyc_document.png").strip()
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext and ext not in ALLOWED_KYC_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng tệp '{ext}' không được hỗ trợ! Chỉ chấp nhận ảnh PNG, JPG, JPEG, WEBP hoặc tài liệu PDF.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Tệp tải lên bị rỗng (0 byte). Vui lòng chọn tệp hợp lệ!")
    if len(content) > MAX_KYC_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Dung lượng tệp vượt quá giới hạn tối đa 10 MB! Vui lòng nén ảnh hoặc chọn tệp nhỏ hơn.",
        )
    return store_encrypted_kyc_document(content, filename)


@router.post("", response_model=KYCApplicationResponse)
@router.post("/submit", response_model=KYCApplicationResponse)
def submit_kyc_application(
    req: KYCApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-02: Nhà đầu tư nộp hồ sơ KYC giả lập (chỉ lưu off-chain trong PostgreSQL/SQLite)."""
    if current_user.role_label != "investor":
        raise HTTPException(
            status_code=403,
            detail="Chỉ tài khoản Nhà đầu tư (Investor) mới thực hiện nộp hồ sơ KYC cá nhân (UC-02).",
        )

    full_name_clean = (req.full_name or "").strip()
    id_number_clean = (req.id_number or "").strip()
    if len(full_name_clean) < 2:
        raise HTTPException(status_code=400, detail="Vui lòng nhập đầy đủ Họ và tên hợp lệ (tối thiểu 2 ký tự).")
    if len(id_number_clean) < 6 or len(id_number_clean) > 30:
        raise HTTPException(status_code=400, detail="Số CCCD / Hộ chiếu phải có độ dài từ 6 đến 30 ký tự.")
    if req.email and ("@" not in req.email or "." not in req.email):
        raise HTTPException(status_code=400, detail="Địa chỉ Email trong hồ sơ KYC không hợp lệ.")

    # Siết chặt State Machine khi Nhà đầu tư nộp hồ sơ (POST /kyc):
    # Kiểm tra bản ghi mới nhất của user_id: nếu đang pending (hoặc under_review) hoặc approved thì chặn HTTP 400.
    # Chỉ cho phép tạo bản ghi mới khi chưa từng nộp hoặc bản ghi mới nhất đang là rejected / revoked.
    latest_app = _get_latest_kyc_for_user(db, current_user.id)
    if latest_app:
        if latest_app.status in ("pending", "under_review"):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Hồ sơ KYC mới nhất (#{latest_app.id}) của bạn đang ở trạng thái chờ xét duyệt "
                    f"('{latest_app.status}'). Vui lòng đợi Cán bộ Tuân thủ phản hồi trước khi nộp lại!"
                ),
            )
        if latest_app.status == "approved":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Hồ sơ KYC mới nhất (#{latest_app.id}) đã được phê duyệt ('approved'). "
                    "Chỉ được phép nộp lại hồ sơ mới khi trạng thái hiện tại là 'rejected' hoặc 'revoked'!"
                ),
            )
        if latest_app.status not in ("rejected", "revoked"):
            raise HTTPException(
                status_code=400,
                detail=f"Không thể nộp hồ sơ mới từ trạng thái hiện tại ('{latest_app.status}').",
            )
    elif current_user.is_whitelisted:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản đã nằm trong danh sách trắng KYC (Approved). Không cho phép nộp lại trừ khi bị thu hồi trước!",
        )

    doc_cid_val = req.doc_cid or req.front_image_cid or "QmKYCDefaultMockDocument2026"
    doc_name_val = req.doc_name or req.front_doc_name or "cccd_mat_truoc.png"
    front_cid_val = req.front_image_cid or doc_cid_val
    back_cid_val = req.back_image_cid or f"{doc_cid_val}_back"
    front_doc_name_val = req.front_doc_name or doc_name_val
    back_doc_name_val = req.back_doc_name or f"mat_sau_{doc_name_val}"
    now_iso = datetime.datetime.utcnow().isoformat()

    base_payload = {
        "full_name": full_name_clean,
        "id_number": id_number_clean,
        "email": req.email,
        "phone": req.phone,
        "document_type": req.document_type or "CCCD / Căn cước công dân",
        "subject_type": req.subject_type or "Investor",
        "doc_cid": doc_cid_val,
        "doc_name": doc_name_val,
        "front_image_cid": front_cid_val,
        "back_image_cid": back_cid_val,
        "front_doc_name": front_doc_name_val,
        "back_doc_name": back_doc_name_val,
        "front_preview_data_url": req.front_preview_data_url,
        "back_preview_data_url": req.back_preview_data_url,
        "encryption_algo": "AES-256-GCM (Controlled Vault)",
        "uploaded_at": now_iso,
        "notes": req.notes or "",
    }

    prev_status_for_new = latest_app.status if latest_app else "none"
    action_label = "Resubmission" if latest_app else "Submit"
    base_payload = _append_kyc_history_log(
        base_payload,
        action=action_label,
        previous_status=prev_status_for_new,
        new_status="pending",
        operator=current_user,
        reason="Nộp lại hồ sơ mới sau khi bị từ chối / thu hồi" if latest_app else "Nộp hồ sơ xác minh danh tính lần đầu",
        notes=req.notes or "",
    )

    new_app = KYCApplication(
        user_id=current_user.id,
        status="pending",
        payload_json=base_payload,
    )
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    return _format_kyc_app(new_app, db)


@router.get("", response_model=List[KYCApplicationResponse])
def list_kyc_applications(
    status: Optional[str] = None,
    document_type: Optional[str] = None,
    time_range: Optional[str] = None,
    search: Optional[str] = Query(default=None, alias="search"),
    q: Optional[str] = None,
    sort: str = "desc",
    db: Session = Depends(get_db),
):
    """
    Liệt kê danh sách hồ sơ KYC:
    - Giữ nguyên toàn bộ bản ghi lịch sử trong bảng kyc_applications để phục vụ kiểm toán.
    - Mặc định chỉ lấy đúng 01 bản ghi mới nhất (MAX(id) theo user_id) cho mỗi nhà đầu tư,
      kèm attempt_count (tổng số lần nộp) và is_latest=True.
    - Sau khi gom 1 bản ghi mới nhất/nhà đầu tư mới áp dụng các bộ lọc status, loại giấy tờ, thời gian, tìm kiếm.
    """
    latest_subq = (
        db.query(
            KYCApplication.user_id.label("user_id"),
            func.max(KYCApplication.id).label("max_id"),
            func.count(KYCApplication.id).label("attempt_count"),
        )
        .filter(KYCApplication.status != "none")
        .group_by(KYCApplication.user_id)
        .subquery()
    )

    query = (
        db.query(KYCApplication, latest_subq.c.attempt_count, User)
        .join(latest_subq, KYCApplication.id == latest_subq.c.max_id)
        .outerjoin(User, User.id == KYCApplication.user_id)
    )

    if status and status.lower() != "all":
        query = query.filter(KYCApplication.status == status.lower())

    if time_range and time_range.lower() != "all":
        tr = time_range.lower()
        now_utc = datetime.datetime.utcnow()
        if tr == "today":
            query = query.filter(KYCApplication.created_at >= now_utc - datetime.timedelta(days=1))
        elif tr == "7d":
            query = query.filter(KYCApplication.created_at >= now_utc - datetime.timedelta(days=7))
        elif tr == "30d":
            query = query.filter(KYCApplication.created_at >= now_utc - datetime.timedelta(days=30))

    if sort.lower() == "asc":
        query = query.order_by(KYCApplication.created_at.asc(), KYCApplication.id.asc())
    else:
        query = query.order_by(KYCApplication.created_at.desc(), KYCApplication.id.desc())

    rows = query.all()
    keyword = (search or q or "").strip().lower()
    doc_filter = (document_type or "").strip().lower()

    results: List[KYCApplicationResponse] = []
    for app_obj, attempt_cnt, inv_user in rows:
        payload = app_obj.payload_json or {}
        if doc_filter and doc_filter != "all":
            doc_val = str(payload.get("document_type") or "").lower()
            if doc_filter not in doc_val:
                continue
        if keyword:
            full_name = str(payload.get("full_name") or (inv_user.display_name if inv_user else "")).lower()
            addr = str(inv_user.address if inv_user else "").lower()
            id_str = str(app_obj.id)
            if keyword not in full_name and keyword not in addr and keyword not in id_str:
                continue

        results.append(
            _format_kyc_app(
                app_obj,
                db,
                attempt_count=int(attempt_cnt or 1),
                is_latest=True,
            )
        )
    return results


@router.get("/my", response_model=Optional[KYCApplicationResponse])
def get_my_kyc(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app_obj = _get_latest_kyc_for_user(db, current_user.id)
    if not app_obj:
        return None
    return _format_kyc_app(app_obj, db)


@router.get("/{kyc_id}", response_model=KYCApplicationDetailResponse)
def get_kyc_application_detail(
    kyc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Xem chi tiết hồ sơ KYC kèm mảng `history` (toàn bộ các lần nộp trước đó của cùng user_id,
    sắp xếp mới nhất trước — chế độ Read-only phục vụ đối chiếu thẩm định).
    """
    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    if current_user.role_label not in ("compliance", "admin") and current_user.id != app_obj.user_id:
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (403 RBAC): Bạn không có quyền xem chi tiết hồ sơ KYC của tài khoản khác!",
        )

    all_user_apps = (
        db.query(KYCApplication)
        .filter(KYCApplication.user_id == app_obj.user_id, KYCApplication.status != "none")
        .order_by(KYCApplication.id.desc())
        .all()
    )
    attempt_count = max(1, len(all_user_apps))
    latest_id = all_user_apps[0].id if all_user_apps else app_obj.id
    is_latest = (app_obj.id == latest_id)

    reviewer_ids = {a.reviewed_by for a in all_user_apps if a.reviewed_by}
    reviewers_map = (
        {u.id: u.display_name for u in db.query(User).filter(User.id.in_(reviewer_ids)).all()}
        if reviewer_ids
        else {}
    )

    history_items: List[KYCHistoryItem] = []
    for prev_app in all_user_apps:
        if prev_app.id == app_obj.id:
            continue
        p = prev_app.payload_json or {}
        rej_reason = (
            p.get("rejection_reason")
            or p.get("revocation_reason")
            or None
        )
        clean_tx = prev_app.tx_hash if (prev_app.tx_hash and str(prev_app.tx_hash).startswith("0x")) else None
        history_items.append(
            KYCHistoryItem(
                id=prev_app.id,
                status=prev_app.status,
                document_type=str(p.get("document_type") or "CCCD / Căn cước công dân"),
                submitted_at=prev_app.created_at,
                reviewed_at=prev_app.reviewed_at,
                reviewed_by=prev_app.reviewed_by,
                reviewer_name=reviewers_map.get(prev_app.reviewed_by) if prev_app.reviewed_by else None,
                reject_reason=rej_reason,
                tx_hash=clean_tx,
            )
        )

    base_resp = _format_kyc_app(app_obj, db, attempt_count=attempt_count, is_latest=is_latest)
    return KYCApplicationDetailResponse(
        **base_resp.model_dump(),
        history=history_items,
    )


@router.post("/{kyc_id}/access-document")
def access_kyc_document(
    kyc_id: int,
    req: Optional[KYCDocumentAccessRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Phần IX & XII: Kiểm soát quyền truy cập và tải xuống tài liệu KYC bảo mật.
    Chỉ duy nhất COMPLIANCE_ROLE được phép giải mã xem/tải tài liệu KYC; mọi lượt truy cập đều ghi vào Audit Log.
    """
    if current_user.role_label != "compliance":
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (403 RBAC): Chỉ Cán bộ Tuân thủ (COMPLIANCE_ROLE) mới có quyền truy cập tài liệu định danh KYC bảo mật!",
        )

    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    investor = db.query(User).filter(User.id == app_obj.user_id).first()
    access_type = (req.access_type.upper() if req and req.access_type else "VIEW")
    doc_side = (req.doc_side if req and req.doc_side else "front")
    purpose = (req.purpose if req and req.purpose else "Kiểm tra tính hợp lệ của giấy tờ định danh KYC")
    now_iso = datetime.datetime.utcnow().isoformat()

    payload = dict(app_obj.payload_json or {})
    doc_logs = list(payload.get("document_access_logs") or [])
    access_entry = {
        "id": f"DOC-ACC-{kyc_id}-{len(doc_logs) + 1}",
        "kyc_id": kyc_id,
        "access_type": access_type,
        "doc_side": doc_side,
        "operator_name": current_user.display_name,
        "operator_address": current_user.address,
        "purpose": purpose,
        "timestamp": now_iso,
        "result_status": "Success",
    }
    doc_logs.insert(0, access_entry)
    payload["document_access_logs"] = doc_logs
    app_obj.payload_json = payload

    audit = AuditSign(
        user_id=current_user.id,
        signer_address=current_user.address,
        role_label="compliance",
        contract_method="KYCDocumentVault.accessDocument",
        params_json={
            "kyc_id": kyc_id,
            "investor": investor.address if investor else "",
            "investor_name": payload.get("full_name") or (investor.display_name if investor else ""),
            "action": "Download KYC Document" if access_type == "DOWNLOAD" else "View KYC Document",
            "doc_side": doc_side,
            "reason": f"{access_type} ({doc_side}): {purpose}",
            "result_status": "Success",
        },
        tx_hash=f"OFFCHAIN_DOC_{access_type}_{kyc_id}_{int(datetime.datetime.utcnow().timestamp())}",
        signed_at=datetime.datetime.utcnow(),
    )
    db.add(audit)
    db.commit()

    return {
        "status": "granted",
        "kyc_id": kyc_id,
        "access_type": access_type,
        "doc_side": doc_side,
        "encryption_mode": "AES-256-GCM Protected Vault (No public IPFS gateway URL)",
        "envelope_cid_masked": f"enc://{payload.get('doc_cid', 'QmKYCDefaultMockDocument2026')[:12]}...protected",
        "access_entry": access_entry,
    }


@router.post("/{kyc_id}/under-review", response_model=KYCApplicationResponse)
def mark_kyc_under_review(
    kyc_id: int,
    req: Optional[KYCDecisionRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compliance chuyển trạng thái hồ sơ sang 'under_review' (đang thẩm định chi tiết)."""
    if current_user.role_label != "compliance":
        raise HTTPException(status_code=403, detail="Chỉ vai trò Compliance (COMPLIANCE_ROLE) mới được cập nhật trạng thái thẩm định")

    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    latest_app = _get_latest_kyc_for_user(db, app_obj.user_id)
    if not latest_app or app_obj.id != latest_app.id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Hồ sơ KYC #{kyc_id} là bản ghi cũ (bản mới nhất là #{latest_app.id if latest_app else 'N/A'}). "
                "Không thể chuyển trạng thái trên bản ghi cũ!"
            ),
        )
    if app_obj.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Chỉ có thể tiếp nhận hồ sơ đang ở trạng thái 'pending' (trạng thái hiện tại: '{app_obj.status}')!",
        )

    investor = db.query(User).filter(User.id == app_obj.user_id).first()
    prev_status = app_obj.status
    payload = dict(app_obj.payload_json or {})
    if req and req.checklist:
        payload["checklist"] = req.checklist
    if req and req.notes:
        payload["review_notes"] = req.notes

    notes_str = req.notes if req and req.notes else "Đang kiểm tra chi tiết hồ sơ KYC"
    payload = _append_kyc_history_log(
        payload,
        action="Under Review",
        previous_status=prev_status,
        new_status="under_review",
        operator=current_user,
        reason="Tiếp nhận kiểm tra hồ sơ chi tiết",
        notes=notes_str,
    )

    app_obj.payload_json = payload
    app_obj.status = "under_review"

    audit = AuditSign(
        user_id=current_user.id,
        signer_address=current_user.address,
        role_label="compliance",
        contract_method="IdentityRegistry.underReviewKYC",
        params_json={
            "kyc_id": kyc_id,
            "investor": investor.address if investor else "",
            "investor_name": payload.get("full_name") or (investor.display_name if investor else ""),
            "previous_status": prev_status,
            "new_status": "under_review",
            "action": "Under Review KYC",
            "reason": notes_str,
            "result_status": "Success",
        },
        tx_hash=f"OFFCHAIN_REVIEW_{kyc_id}_{int(datetime.datetime.utcnow().timestamp())}",
        signed_at=datetime.datetime.utcnow(),
    )
    db.add(audit)

    db.commit()
    db.refresh(app_obj)
    if investor:
        create_notification(
            db=db,
            user_id=investor.id,
            category="kyc",
            title="Hồ sơ KYC đang được thẩm định (Under Review)",
            message=f"Cán bộ tuân thủ đã tiếp nhận hồ sơ KYC #{kyc_id} của bạn để tiến hành xác minh.",
            tx_hash=None,
        )
    return _format_kyc_app(app_obj, db)


@router.post("/{kyc_id}/approve", response_model=KYCApplicationResponse)
def approve_kyc_application(
    kyc_id: int,
    req: Optional[KYCDecisionRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    UC-03 (Nhánh Duyệt):
    Compliance duyệt hồ sơ KYC -> SignerService dùng khóa ví Compliance gọi IdentityRegistry.addToWhitelist(investor).
    """
    if current_user.role_label != "compliance":
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (403 RBAC): Chỉ vai trò COMPLIANCE_ROLE mới được phép phê duyệt KYC!",
        )

    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    latest_app = _get_latest_kyc_for_user(db, app_obj.user_id)
    if not latest_app or app_obj.id != latest_app.id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Từ chối thao tác: Hồ sơ KYC #{kyc_id} là bản ghi cũ "
                f"(hồ sơ mới nhất là #{latest_app.id if latest_app else 'N/A'}). "
                "Không được phép phê duyệt trên bản ghi cũ!"
            ),
        )
    if app_obj.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Từ chối thao tác (State Machine): Không thể phê duyệt hồ sơ đang ở trạng thái '{app_obj.status}'. "
                "Chỉ hồ sơ mới nhất có trạng thái 'pending' mới được phép Approve!"
            ),
        )

    investor = db.query(User).filter(User.id == app_obj.user_id).first()
    if not investor:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhà đầu tư")

    prev_status = app_obj.status
    registry = get_contract_instance("IdentityRegistry")
    checksum_investor = Web3.to_checksum_address(investor.address)

    try:
        already_verified = registry.functions.isVerified(checksum_investor).call()
    except Exception:
        already_verified = False

    tx_hash = app_obj.tx_hash or (f"0x{'d'*64}" if already_verified else None)
    notes_val = (req.notes if req and req.notes else "Hồ sơ hợp lệ, đạt đủ 5/5 tiêu chí thẩm định KYC")
    reason_val = (req.reason if req and req.reason else "Đạt đầy đủ tiêu chuẩn xác minh danh tính KYC")
    if not already_verified:
        fn = registry.functions.addToWhitelist(checksum_investor)
        summary = {
            "investor": investor.address,
            "kyc_id": kyc_id,
            "investor_name": (app_obj.payload_json or {}).get("full_name") or investor.display_name,
            "previous_status": prev_status,
            "new_status": "approved",
            "action": "Approve KYC",
            "reason": reason_val,
            "notes": notes_val,
            "result_status": "Success",
        }
        res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=fn,
            contract_method_name="IdentityRegistry.addToWhitelist",
            params_summary=summary,
            required_roles=["compliance"],
        )
        if getattr(res.get("receipt"), "status", 1) != 1:
            raise HTTPException(
                status_code=400,
                detail="Giao dịch IdentityRegistry.addToWhitelist không thành công trên chuỗi!",
            )
        tx_hash = res["tx_hash"]

    payload = dict(app_obj.payload_json or {})
    if req:
        if req.checklist:
            payload["checklist"] = req.checklist
        if req.notes:
            payload["approval_notes"] = req.notes

    payload = _append_kyc_history_log(
        payload,
        action="Approve",
        previous_status=prev_status,
        new_status="approved",
        operator=current_user,
        reason=reason_val,
        notes=notes_val,
        tx_hash=tx_hash,
    )

    app_obj.payload_json = payload
    app_obj.status = "approved"
    app_obj.reviewed_by = current_user.id
    app_obj.tx_hash = tx_hash
    app_obj.reviewed_at = datetime.datetime.utcnow()
    investor.is_whitelisted = True
    db.commit()
    db.refresh(app_obj)
    create_notification(
        db=db,
        user_id=investor.id,
        category="kyc",
        title="Hồ sơ KYC đã được phê duyệt (Whitelisted)",
        message="Chúc mừng! Hồ sơ KYC của bạn đã được Cán bộ tuân thủ phê duyệt và ghi nhận trên IdentityRegistry. Bạn đã có thể giao dịch cổ phần BĐS.",
        tx_hash=tx_hash,
    )
    return _format_kyc_app(app_obj, db)


@router.post("/{kyc_id}/reject", response_model=KYCApplicationResponse)
def reject_kyc_application(
    kyc_id: int,
    req: Optional[KYCDecisionRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-03 (Nhánh Từ chối): Cập nhật trạng thái off-chain thành rejected kèm lý do từ chối chi tiết."""
    if current_user.role_label != "compliance":
        raise HTTPException(status_code=403, detail="Chỉ vai trò Compliance (COMPLIANCE_ROLE) được phép từ chối hồ sơ KYC")

    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    latest_app = _get_latest_kyc_for_user(db, app_obj.user_id)
    if not latest_app or app_obj.id != latest_app.id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Từ chối thao tác: Hồ sơ KYC #{kyc_id} là bản ghi cũ "
                f"(hồ sơ mới nhất là #{latest_app.id if latest_app else 'N/A'}). "
                "Không được phép từ chối trên bản ghi cũ!"
            ),
        )
    if app_obj.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Từ chối thao tác (State Machine): Không thể từ chối hồ sơ đang ở trạng thái '{app_obj.status}'. "
                "Chỉ hồ sơ mới nhất có trạng thái 'pending' mới được phép Reject!"
            ),
        )

    investor = db.query(User).filter(User.id == app_obj.user_id).first()
    prev_status = app_obj.status

    reason = (req.reason if req and req.reason else "Ảnh giấy tờ không rõ")
    notes = (req.notes if req and req.notes else "")
    offchain_ref = f"OFFCHAIN_REJECT_{kyc_id}_{int(datetime.datetime.utcnow().timestamp())}"

    payload = dict(app_obj.payload_json or {})
    payload["rejection_reason"] = reason
    payload["rejection_notes"] = notes
    if req and req.checklist:
        payload["checklist"] = req.checklist

    payload = _append_kyc_history_log(
        payload,
        action="Reject",
        previous_status=prev_status,
        new_status="rejected",
        operator=current_user,
        reason=reason,
        notes=notes,
        tx_hash=None,
    )

    app_obj.payload_json = payload
    app_obj.status = "rejected"
    app_obj.reviewed_by = current_user.id
    app_obj.reviewed_at = datetime.datetime.utcnow()

    audit = AuditSign(
        user_id=current_user.id,
        signer_address=current_user.address,
        role_label="compliance",
        contract_method="IdentityRegistry.rejectKYC",
        params_json={
            "kyc_id": kyc_id,
            "investor": investor.address if investor else "",
            "investor_name": payload.get("full_name") or (investor.display_name if investor else ""),
            "previous_status": prev_status,
            "new_status": "rejected",
            "action": "Reject KYC",
            "reason": reason,
            "notes": notes,
            "result_status": "Success",
        },
        tx_hash=offchain_ref,
        signed_at=datetime.datetime.utcnow(),
    )
    db.add(audit)

    db.commit()
    db.refresh(app_obj)
    if investor:
        create_notification(
            db=db,
            user_id=investor.id,
            category="kyc",
            title="Hồ sơ KYC bị từ chối — Cần bổ sung thông tin",
            message=f"Lý do từ chối: {reason}." + (f" Ghi chú: {notes}" if notes else ""),
            tx_hash=None,
        )
    return _format_kyc_app(app_obj, db)


@router.post("/{kyc_id}/revoke", response_model=KYCApplicationResponse)
def revoke_kyc_application(
    kyc_id: int,
    req: Optional[KYCDecisionRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-03 (Nhánh Thu hồi): Gọi IdentityRegistry.removeFromWhitelist(investor). Không tự động Freeze ví."""
    if current_user.role_label != "compliance":
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (403 RBAC): Chỉ vai trò COMPLIANCE_ROLE mới được phép thu hồi KYC!",
        )

    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    latest_app = _get_latest_kyc_for_user(db, app_obj.user_id)
    if not latest_app or app_obj.id != latest_app.id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Từ chối thao tác: Hồ sơ KYC #{kyc_id} là bản ghi cũ "
                f"(hồ sơ mới nhất là #{latest_app.id if latest_app else 'N/A'}). "
                "Không được phép thu hồi trên bản ghi cũ!"
            ),
        )
    if app_obj.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Từ chối thao tác (State Machine): Chỉ được phép thu hồi (Revoke) khi hồ sơ mới nhất đang ở trạng thái 'approved' "
                f"(trạng thái hiện tại: '{app_obj.status}')!"
            ),
        )

    investor = db.query(User).filter(User.id == app_obj.user_id).first()
    if not investor:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhà đầu tư")

    prev_status = app_obj.status
    registry = get_contract_instance("IdentityRegistry")
    checksum_investor = Web3.to_checksum_address(investor.address)

    reason = (req.reason if req and req.reason else "Thu hồi quyền theo quyết định bộ phận tuân thủ")
    notes = (req.notes if req and req.notes else "")

    currently_verified = bool(registry.functions.isVerified(checksum_investor).call())
    if currently_verified:
        fn = registry.functions.removeFromWhitelist(checksum_investor)
        res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=fn,
            contract_method_name="IdentityRegistry.removeFromWhitelist",
            params_summary={
                "investor": investor.address,
                "investor_name": (app_obj.payload_json or {}).get("full_name") or investor.display_name,
                "kyc_id": kyc_id,
                "previous_status": prev_status,
                "new_status": "revoked",
                "action": "Revoke KYC",
                "reason": reason,
                "notes": notes,
                "result_status": "Success",
            },
            required_roles=["compliance"],
        )
        if getattr(res.get("receipt"), "status", 1) != 1:
            raise HTTPException(
                status_code=400,
                detail="Giao dịch IdentityRegistry.removeFromWhitelist thất bại trên chuỗi! Trạng thái cơ sở dữ liệu được giữ nguyên.",
            )
        tx_hash_val = res["tx_hash"]
    else:
        tx_hash_val = f"0x{'e'*64}"
        audit = AuditSign(
            user_id=current_user.id,
            signer_address=current_user.address,
            role_label="compliance",
            contract_method="IdentityRegistry.removeFromWhitelist",
            params_json={
                "investor": investor.address,
                "investor_name": (app_obj.payload_json or {}).get("full_name") or investor.display_name,
                "kyc_id": kyc_id,
                "previous_status": prev_status,
                "new_status": "revoked",
                "action": "Revoke KYC",
                "reason": reason,
                "notes": notes,
                "result_status": "Success",
            },
            tx_hash=tx_hash_val,
            signed_at=datetime.datetime.utcnow(),
        )
        db.add(audit)

    app_obj.tx_hash = tx_hash_val

    payload = dict(app_obj.payload_json or {})
    payload["revocation_reason"] = reason
    payload["revocation_notes"] = notes
    payload = _append_kyc_history_log(
        payload,
        action="Revoke",
        previous_status=prev_status,
        new_status="revoked",
        operator=current_user,
        reason=reason,
        notes=notes,
        tx_hash=tx_hash_val,
    )

    app_obj.payload_json = payload
    app_obj.status = "revoked"
    app_obj.reviewed_by = current_user.id
    app_obj.reviewed_at = datetime.datetime.utcnow()
    investor.is_whitelisted = False
    db.commit()
    db.refresh(app_obj)
    create_notification(
        db=db,
        user_id=investor.id,
        category="kyc",
        title="Trạng thái KYC đã bị thu hồi (Revoked)",
        message=f"Quyền giao dịch (Whitelist) của ví bạn vừa bị thu hồi trên IdentityRegistry. Lý do: {reason}.",
        tx_hash=tx_hash_val,
    )
    return _format_kyc_app(app_obj, db)


@router.get("/compliance/overview")
def get_compliance_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phần II..IX: Dữ liệu Dashboard & Tổng quan phân hệ Compliance.
    Kiểm tra quyền tại Backend: Chỉ cho phép COMPLIANCE_ROLE hoặc DEFAULT_ADMIN_ROLE truy cập.
    """
    if current_user.role_label not in ["compliance", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (403 RBAC): Chỉ tài khoản COMPLIANCE_ROLE mới có quyền truy cập dữ liệu Compliance Portal!",
        )

    all_apps = (
        db.query(KYCApplication)
        .filter(KYCApplication.status != "none")
        .order_by(KYCApplication.id.desc())
        .all()
    )
    all_users = db.query(User).all()
    users_by_id = {u.id: u for u in all_users}
    users_by_addr = {u.address.lower(): u for u in all_users}

    # Gom 01 bản ghi mới nhất theo từng user_id cho KPI & Queue (tránh đếm trùng bản ghi cũ)
    latest_by_user: Dict[int, KYCApplication] = {}
    attempts_by_user: Dict[int, int] = {}
    for a in all_apps:
        attempts_by_user[a.user_id] = attempts_by_user.get(a.user_id, 0) + 1
        if a.user_id not in latest_by_user:
            latest_by_user[a.user_id] = a
    latest_apps = list(latest_by_user.values())

    total_kyc = len(latest_apps)
    pending_count = sum(1 for a in latest_apps if a.status == "pending")
    under_review_count = sum(1 for a in latest_apps if a.status == "under_review")
    approved_count = sum(1 for a in latest_apps if a.status == "approved")
    rejected_count = sum(1 for a in latest_apps if a.status == "rejected")
    revoked_count = sum(1 for a in latest_apps if a.status == "revoked")
    frozen_wallets = sum(1 for u in all_users if u.is_frozen)

    completed_reviews = approved_count + rejected_count
    approval_rate = round((approved_count / completed_reviews * 100), 1) if completed_reviews > 0 else 0.0
    rejection_rate = round((rejected_count / completed_reviews * 100), 1) if completed_reviews > 0 else 0.0

    # 1. Freeze history from AuditSign (AssetToken.setFrozen) — Never overwritten!
    freeze_signs = (
        db.query(AuditSign)
        .filter(AuditSign.contract_method == "AssetToken.setFrozen")
        .order_by(AuditSign.signed_at.desc())
        .limit(100)
        .all()
    )
    freeze_history = []
    latest_freeze_by_addr: Dict[str, Dict[str, Any]] = {}
    for s in freeze_signs:
        p = s.params_json or {}
        acct_addr = (p.get("account") or "").lower()
        acct_user = users_by_addr.get(acct_addr)
        reviewer = users_by_id.get(s.user_id)
        is_frz = bool(p.get("frozen", False))
        f_item = {
            "id": s.id,
            "account_address": acct_addr,
            "investor_name": acct_user.display_name if acct_user else "Nhà đầu tư",
            "action": "Freeze" if is_frz else "Unfreeze",
            "frozen": is_frz,
            "reason": p.get("reason", "Nghi vấn vi phạm quy chế tuân thủ" if is_frz else "Đã xác minh an toàn, mở khóa tài khoản"),
            "case_code": p.get("case_code", ""),
            "notes": p.get("notes", ""),
            "token_address": p.get("token", ""),
            "tx_hash": s.tx_hash,
            "tx_status": "Success",
            "signer_address": s.signer_address,
            "operator_name": reviewer.display_name if reviewer else "Compliance Officer",
            "signed_at": s.signed_at.isoformat() if s.signed_at else None,
        }
        freeze_history.append(f_item)
        if acct_addr and acct_addr not in latest_freeze_by_addr:
            latest_freeze_by_addr[acct_addr] = f_item

    # 2. Review queue & Review history (with previous_status -> new_status)
    queue = []
    review_history = []
    for a in all_apps:
        inv = users_by_id.get(a.user_id)
        reviewer = users_by_id.get(a.reviewed_by) if a.reviewed_by else None
        payload = a.payload_json or {}
        item = {
            "id": a.id,
            "user_id": a.user_id,
            "investor_name": payload.get("full_name") or (inv.display_name if inv else "N/A"),
            "investor_address": inv.address if inv else "",
            "is_frozen": inv.is_frozen if inv else False,
            "is_whitelisted": inv.is_whitelisted if inv else False,
            "status": a.status,
            "payload": payload,
            "tx_hash": a.tx_hash,
            "reviewer_name": reviewer.display_name if reviewer else "Compliance Officer",
            "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        is_user_latest = latest_by_user.get(a.user_id) and latest_by_user[a.user_id].id == a.id
        if is_user_latest and a.status in ["pending", "under_review"]:
            item["attempt_count"] = attempts_by_user.get(a.user_id, 1)
            item["is_latest"] = True
            queue.append(item)

        hist_logs = payload.get("history_logs") or []
        if hist_logs:
            for h_idx, h in enumerate(hist_logs):
                if h.get("action") in ["Approve", "Reject", "Revoke", "Resubmission", "Under Review"]:
                    raw_tx = h.get("tx_hash") or (a.tx_hash if h.get("action") in ["Approve", "Revoke"] else None)
                    clean_tx = raw_tx if (raw_tx and str(raw_tx).startswith("0x")) else None
                    review_history.append({
                        "record_id": h.get("id") or f"{a.id}-{h_idx}",
                        "id": a.id,
                        "investor_name": payload.get("full_name") or (inv.display_name if inv else "Nhà đầu tư"),
                        "investor_address": inv.address if inv else "",
                        "action": h.get("action"),
                        "previous_status": h.get("previous_status", "pending"),
                        "new_status": h.get("new_status", a.status),
                        "status": h.get("new_status", a.status),
                        "reason": h.get("reason", ""),
                        "notes": h.get("notes", ""),
                        "reviewer_name": h.get("operator_name") or (reviewer.display_name if reviewer else "Compliance Officer"),
                        "reviewer_address": h.get("operator_address") or "",
                        "tx_hash": clean_tx,
                        "reviewed_at": h.get("timestamp") or (a.reviewed_at.isoformat() if a.reviewed_at else a.created_at.isoformat()),
                        "payload": payload,
                    })
        elif a.status in ["approved", "rejected", "revoked"]:
            act_map = {"approved": "Approve", "rejected": "Reject", "revoked": "Revoke"}
            prev_map = {"approved": "pending", "rejected": "pending", "revoked": "approved"}
            reason_str = (
                payload.get("rejection_reason")
                if a.status == "rejected"
                else payload.get("revocation_reason")
                if a.status == "revoked"
                else payload.get("approval_notes") or "Hồ sơ hợp lệ, đạt tiêu chuẩn KYC"
            )
            notes_str = (
                payload.get("rejection_notes")
                if a.status == "rejected"
                else payload.get("revocation_notes")
                if a.status == "revoked"
                else payload.get("notes") or ""
            )
            clean_tx = a.tx_hash if (a.tx_hash and str(a.tx_hash).startswith("0x")) else None
            review_history.append({
                "record_id": f"{a.id}-0",
                "id": a.id,
                "investor_name": payload.get("full_name") or (inv.display_name if inv else "Nhà đầu tư"),
                "investor_address": inv.address if inv else "",
                "action": act_map.get(a.status, "Approve"),
                "previous_status": prev_map.get(a.status, "pending"),
                "new_status": a.status,
                "status": a.status,
                "reason": reason_str,
                "notes": notes_str,
                "reviewer_name": reviewer.display_name if reviewer else "Compliance Officer",
                "reviewer_address": reviewer.address if reviewer else "",
                "tx_hash": clean_tx,
                "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else (a.created_at.isoformat() if a.created_at else None),
                "payload": payload,
            })

    review_history.sort(key=lambda x: x.get("reviewed_at") or "", reverse=True)

    # 3. Compliance Audit Logs (Phần VIII — Đủ 8 trường chuẩn: Người thực hiện, Địa chỉ ví, Hành động, Đối tượng, Lý do, Thời gian, TxHash, Kết quả)
    comp_signs = (
        db.query(AuditSign)
        .filter(
            (AuditSign.role_label == "compliance")
            | (AuditSign.contract_method.like("IdentityRegistry.%"))
            | (AuditSign.contract_method == "AssetToken.setFrozen")
            | (AuditSign.contract_method.like("KYCDocumentVault.%"))
        )
        .order_by(AuditSign.signed_at.desc())
        .limit(100)
        .all()
    )
    compliance_audit_logs = []
    for s in comp_signs:
        op = users_by_id.get(s.user_id)
        p = s.params_json or {}
        m = s.contract_method or ""

        if m == "IdentityRegistry.addToWhitelist":
            action_label = "Approve KYC"
        elif m == "IdentityRegistry.rejectKYC":
            action_label = "Reject KYC"
        elif m == "IdentityRegistry.removeFromWhitelist":
            action_label = "Revoke KYC"
        elif m == "IdentityRegistry.underReviewKYC":
            action_label = "Under Review KYC"
        elif m == "AssetToken.setFrozen":
            action_label = "Freeze Account" if p.get("frozen") else "Unfreeze Account"
        elif m == "KYCDocumentVault.accessDocument":
            action_label = p.get("action") or "View KYC Document"
        else:
            action_label = p.get("action") or m

        target_addr = (p.get("investor") or p.get("account") or "").lower()
        target_user = users_by_addr.get(target_addr)
        target_name = p.get("investor_name") or (target_user.display_name if target_user else "Nhà đầu tư")
        kyc_id_ref = p.get("kyc_id")
        target_subject = f"{target_name} (KYC #{kyc_id_ref})" if kyc_id_ref else target_name

        reason_val = (
            p.get("reason")
            or p.get("notes")
            or (
                "Phê duyệt KYC & đưa ví vào Whitelist"
                if action_label == "Approve KYC"
                else "Thu hồi trạng thái KYC khỏi Whitelist"
                if action_label == "Revoke KYC"
                else "Khóa tài khoản trên AssetToken"
                if action_label == "Freeze Account"
                else "Mở khóa tài khoản trên AssetToken"
            )
        )

        is_onchain_tx = bool(s.tx_hash and str(s.tx_hash).startswith("0x"))
        result_status = p.get("result_status") or "Success"

        compliance_audit_logs.append({
            "id": s.id,
            "operator_name": op.display_name if op else "Compliance Officer",
            "signer_address": s.signer_address,
            "role_label": s.role_label,
            "action_label": action_label,
            "contract_method": m,
            "target_subject": target_subject,
            "target_address": target_addr,
            "reason": reason_val,
            "params": p,
            "tx_hash": s.tx_hash if is_onchain_tx else None,
            "offchain_ref": None if is_onchain_tx else s.tx_hash,
            "result_status": result_status,
            "status": result_status,
            "signed_at": s.signed_at.isoformat() if s.signed_at else None,
        })

    # 4. Query tokenized estates for live on-chain balance calculation
    tokenized_estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()

    investor_accounts = []
    for u in all_users:
        if u.role_label in ["investor", "issuer", "admin", "compliance"]:
            latest_kyc = (
                db.query(KYCApplication)
                .filter(KYCApplication.user_id == u.id)
                .order_by(KYCApplication.created_at.desc())
                .first()
            )
            total_token_balance = 0.0
            holdings_detail = []
            try:
                checksum_u = Web3.to_checksum_address(u.address)
                for est in tokenized_estates:
                    tok = get_contract_instance("AssetToken", est.token_address)
                    raw_bal = tok.functions.balanceOf(checksum_u).call()
                    bal_val = float(raw_bal) / (10 ** 18)
                    if bal_val > 0:
                        total_token_balance += bal_val
                        holdings_detail.append({"symbol": est.symbol, "amount": bal_val})
            except Exception:
                pass

            last_frz = latest_freeze_by_addr.get(u.address.lower())
            investor_accounts.append({
                "id": u.id,
                "address": u.address,
                "display_name": u.display_name,
                "role_label": u.role_label,
                "is_whitelisted": u.is_whitelisted,
                "is_frozen": u.is_frozen,
                "kyc_status": latest_kyc.status if latest_kyc else ("approved" if u.is_whitelisted else "none"),
                "kyc_id": latest_kyc.id if latest_kyc else None,
                "token_balance": round(total_token_balance, 4),
                "holdings_detail": holdings_detail,
                "last_frozen_at": last_frz["signed_at"] if last_frz else None,
                "last_freeze_reason": last_frz["reason"] if last_frz else None,
                "last_freeze_case_code": last_frz["case_code"] if last_frz else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            })

    # 5. Timeline
    timeline = []
    for a in sorted(all_apps, key=lambda x: x.created_at):
        day_str = a.created_at.strftime("%d/%m/%Y") if a.created_at else "Hôm nay"
        found = next((t for t in timeline if t["date"] == day_str), None)
        if not found:
            timeline.append({
                "date": day_str,
                "total": 1,
                "approved": 1 if a.status == "approved" else 0,
                "rejected": 1 if a.status == "rejected" else 0,
                "pending": 1 if a.status in ["pending", "under_review"] else 0,
            })
        else:
            found["total"] += 1
            if a.status == "approved":
                found["approved"] += 1
            elif a.status == "rejected":
                found["rejected"] += 1
            elif a.status in ["pending", "under_review"]:
                found["pending"] += 1

    return {
        "kpis": {
            "total_kyc": total_kyc,
            "pending": pending_count,
            "under_review": under_review_count,
            "approved": approved_count,
            "rejected": rejected_count,
            "revoked": revoked_count,
            "frozen_wallets": frozen_wallets,
            "approval_rate": approval_rate,
            "rejection_rate": rejection_rate,
        },
        "newly_submitted": [
            {
                "id": a.id,
                "attempt_count": attempts_by_user.get(a.user_id, 1),
                "is_latest": True,
                "investor_name": (a.payload_json or {}).get("full_name") or (users_by_id.get(a.user_id).display_name if users_by_id.get(a.user_id) else "Nhà đầu tư"),
                "investor_address": users_by_id.get(a.user_id).address if users_by_id.get(a.user_id) else "",
                "document_type": (a.payload_json or {}).get("document_type", "CCCD / National ID"),
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "payload_json": a.payload_json or {},
            }
            for a in latest_apps[:6]
        ],
        "queue": queue,
        "review_history": review_history,
        "freeze_history": freeze_history,
        "compliance_audit_logs": compliance_audit_logs,
        "investor_accounts": investor_accounts,
        "timeline": timeline,
    }


@router.get("/{kyc_id}/document-content")
def download_decrypted_kyc_document(
    kyc_id: int,
    side: str = "front",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Giải mã AES-256-GCM và trả tệp tài liệu KYC bảo mật (chỉ dành riêng cho COMPLIANCE_ROLE)."""
    if current_user.role_label != "compliance":
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (403 RBAC): Chỉ COMPLIANCE_ROLE được phép giải mã và tải tài liệu KYC!",
        )

    app_obj = db.query(KYCApplication).filter(KYCApplication.id == kyc_id).first()
    if not app_obj:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ KYC")

    payload = app_obj.payload_json or {}
    if side == "back":
        cid = payload.get("back_image_cid") or f"{payload.get('doc_cid', f'kyc_{kyc_id}')}_back"
        filename = payload.get("back_doc_name") or f"mat_sau_{payload.get('doc_name', f'kyc_{kyc_id}.png')}"
    else:
        cid = payload.get("front_image_cid") or payload.get("doc_cid") or f"kyc_{kyc_id}"
        filename = payload.get("front_doc_name") or payload.get("doc_name") or f"mat_truoc_{kyc_id}.png"

    content_bytes, was_encrypted = read_encrypted_kyc_document(cid)

    return Response(
        content=content_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-KYC-Vault-Encrypted": "AES-256-GCM" if was_encrypted else "LEGACY",
        },
    )


@router.get("/compliance/export/kyc-history")
def export_kyc_history_csv(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Xuất báo cáo Lịch sử xét duyệt KYC ra định dạng CSV (UTF-8 BOM tương thích Excel)."""
    if current_user.role_label not in ("compliance", "admin"):
        raise HTTPException(status_code=403, detail="Chỉ Compliance hoặc Admin mới được xuất báo cáo CSV!")

    overview = get_compliance_overview(db=db, current_user=current_user)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Mã hồ sơ",
            "Nhà đầu tư",
            "Địa chỉ ví",
            "Hành động",
            "Trạng thái trước",
            "Trạng thái sau",
            "Người thực hiện",
            "Lý do",
            "Ghi chú",
            "Thời gian",
            "TxHash / Mã tham chiếu",
        ]
    )
    for row in overview.get("review_history", []):
        writer.writerow(
            [
                f"KYC-{row.get('kyc_id', '')}",
                row.get("investor_name", ""),
                row.get("investor_address", ""),
                row.get("action", ""),
                row.get("previous_status", ""),
                row.get("new_status", ""),
                row.get("operator_name", ""),
                row.get("reason", ""),
                row.get("notes", ""),
                row.get("timestamp", ""),
                row.get("tx_hash", ""),
            ]
        )

    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kyc_review_history.csv"'},
    )


@router.get("/compliance/export/audit-logs")
def export_compliance_audit_logs_csv(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Xuất báo cáo Nhật ký kiểm toán Compliance (Audit Logs) ra định dạng CSV (UTF-8 BOM)."""
    if current_user.role_label not in ("compliance", "admin"):
        raise HTTPException(status_code=403, detail="Chỉ Compliance hoặc Admin mới được xuất Audit Logs CSV!")

    overview = get_compliance_overview(db=db, current_user=current_user)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "ID",
            "Người thực hiện",
            "Địa chỉ ví thực hiện",
            "Hành động",
            "Đối tượng",
            "Lý do",
            "Trạng thái kết quả",
            "Thời gian",
            "Transaction Hash",
        ]
    )
    for row in overview.get("compliance_audit_logs", []):
        writer.writerow(
            [
                row.get("id", ""),
                row.get("operator_name", ""),
                row.get("operator_address", ""),
                row.get("action", ""),
                row.get("target", ""),
                row.get("reason", ""),
                row.get("result_status", ""),
                row.get("timestamp", ""),
                row.get("tx_hash", ""),
            ]
        )

    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="compliance_audit_logs.csv"'},
    )
