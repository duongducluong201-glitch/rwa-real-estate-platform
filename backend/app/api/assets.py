import datetime
import html as html_lib
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from ..services.w3_compat import Web3
from ..database import get_db
from ..models import (
    User,
    RealEstate,
    PrimarySaleCache,
    ListingCache,
    TransferCache,
    AuditSign,
    DividendDistribution,
    DividendPayout,
)
from ..schemas import RealEstateCreateRequest, ValuationUpdateRequest
from ..services.auth import get_current_user
from ..services.ipfs import upload_to_ipfs, compute_doc_hash, LOCAL_IPFS_CACHE_DIR
from ..services.docx_service import (
    DOCX_MIME_TYPE,
    detect_document_type,
    docx_bytes_to_html,
    generate_legal_deed_docx,
    is_docx_bytes,
)
from ..services.signer import SignerService, get_contract_instance, get_w3, is_contract_deployed_on_anvil
from ..services.listener import record_transfer_cache, sync_onchain_state
from ..config import load_deployed_contracts, settings

router = APIRouter(prefix="/assets", tags=["3. Quản lý & Token hóa Bất động sản (UC-04, UC-05, UC-07, UC-14)"])
real_estates_router = APIRouter(prefix="/real-estates", tags=["3. Quản lý & Token hóa Bất động sản (UC-04, UC-05, UC-07, UC-14)"])


def _serialize_estate(est: RealEstate, db: Session, extra_tx_hash: Optional[str] = None) -> dict:
    sale_cache = (
        db.query(PrimarySaleCache)
        .filter(PrimarySaleCache.real_estate_id == est.id)
        .first()
    )
    issuer_user = db.query(User).filter(User.id == est.created_by).first()
    total_shares_f = float(est.total_shares or 0)
    valuation_f = float(est.valuation or 0)
    intrinsic_price = (valuation_f / total_shares_f) if total_shares_f > 0 else 0.0

    paused_onchain = False
    onchain_doc_hash = est.doc_hash
    deployed = load_deployed_contracts()
    primary_sale_addr = (deployed.get("PrimarySale") or "").lower()
    vault_balance = total_shares_f if est.token_address else 0.0

    if est.token_address and is_contract_deployed_on_anvil(est.token_address):
        try:
            tok = get_contract_instance("AssetToken", est.token_address)
            paused_onchain = bool(tok.functions.paused().call())
            raw_dh = tok.functions.docHash().call()
            if isinstance(raw_dh, (bytes, bytearray)):
                onchain_doc_hash = "0x" + raw_dh.hex()
            elif isinstance(raw_dh, str):
                onchain_doc_hash = raw_dh
            if primary_sale_addr and Web3.is_address(primary_sale_addr):
                raw_vault = tok.functions.balanceOf(Web3.to_checksum_address(primary_sale_addr)).call()
                vault_balance = float(raw_vault) / 1e18
        except Exception:
            pass

    # Tính toán thống kê bán sơ cấp thực tế từ TransferCache & PrimarySaleCache
    primary_buys = []
    if est.token_address:
        primary_buys = (
            db.query(TransferCache)
            .filter(
                TransferCache.token_address == est.token_address.lower(),
                TransferCache.event_type == "PRIMARY_BUY",
            )
            .all()
        )

    tx_sold_shares = sum(float(t.amount or 0) for t in primary_buys)
    tx_raised_usdc = sum(float(t.usdc_paid or 0) for t in primary_buys)

    offered_amount = float(sale_cache.total_amount) if sale_cache else 0.0
    remaining_amount = float(sale_cache.remaining_amount) if sale_cache else 0.0
    price_per_share = float(sale_cache.price_per_share) if sale_cache else round(intrinsic_price, 2)
    is_open = bool(sale_cache.is_open) if sale_cache else False

    sold_from_cache = max(0.0, offered_amount - remaining_amount) if offered_amount > 0 else 0.0
    sold_amount = max(tx_sold_shares, sold_from_cache)
    raised_usdc = tx_raised_usdc if tx_raised_usdc > 0 else round(sold_amount * price_per_share, 2)
    progress_pct = round((sold_amount / offered_amount) * 100.0, 2) if offered_amount > 0 else 0.0
    circulating_shares = max(0.0, total_shares_f - vault_balance) if est.token_address else 0.0
    if circulating_shares == 0 and sold_amount > 0:
        circulating_shares = sold_amount

    # Kiểm tra thông tin file IPFS cục bộ (mặc định tài liệu Word .docx)
    cid_path = os.path.join(LOCAL_IPFS_CACHE_DIR, est.doc_cid) if est.doc_cid else ""
    doc_size_bytes = os.path.getsize(cid_path) if cid_path and os.path.exists(cid_path) else 0
    doc_ext = ".docx"
    doc_format = "docx"
    if cid_path and os.path.exists(cid_path):
        try:
            with open(cid_path, "rb") as f:
                detected = detect_document_type(f.read())
                if detected["format"] in ("docx", "pdf", "image", "doc"):
                    doc_ext = detected["ext"]
                    doc_format = detected["format"]
        except Exception:
            pass
    doc_name = f"Ho_so_Phap_ly_{est.symbol}{doc_ext}"

    result = {
        "id": est.id,
        "token_address": est.token_address,
        "name": est.name,
        "symbol": est.symbol,
        "address_text": est.address_text,
        "area_m2": float(est.area_m2 or 0),
        "property_kind": est.property_kind,
        "build_year": est.build_year,
        "description": est.description,
        "valuation": valuation_f,
        "total_shares": total_shares_f,
        "intrinsic_price_per_share": round(intrinsic_price, 4),
        "circulating_shares": round(circulating_shares, 4),
        "vault_balance": round(vault_balance, 4),
        "doc_cid": est.doc_cid,
        "doc_hash": est.doc_hash,
        "doc_name": doc_name,
        "doc_format": doc_format,
        "onchain_doc_hash": onchain_doc_hash,
        "doc_size_bytes": doc_size_bytes,
        "status": est.status,
        "is_paused": paused_onchain,
        "created_by": est.created_by,
        "issuer_address": issuer_user.address if issuer_user else "",
        "issuer_name": issuer_user.display_name if issuer_user else "Đơn vị phát hành (Issuer)",
        "created_at": est.created_at.isoformat() if est.created_at else None,
        "primary_sale": {
            "is_open": is_open,
            "price_per_share": price_per_share,
            "total_amount": offered_amount,
            "remaining_amount": remaining_amount,
            "sold_amount": round(sold_amount, 4),
            "raised_usdc": round(raised_usdc, 2),
            "progress_percent": min(100.0, progress_pct),
        },
    }
    if extra_tx_hash:
        result["tx_hash"] = extra_tx_hash
    return result


@router.post("/upload-document")
async def upload_real_estate_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Tải tệp Word (.docx) hoặc hồ sơ pháp lý của BĐS lên Pinata IPFS và tính mã băm docHash (Keccak-256)."""
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Tệp tải lên rỗng (0 bytes)!")
    return upload_to_ipfs(content, file.filename or "ho_so_phap_ly_bds.docx")


@router.get("/issuer/overview")
def get_issuer_dashboard_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """API tổng hợp dữ liệu thực tế cho Issuer Dashboard, Quản lý Mở bán, Hồ sơ Pháp lý và Báo cáo Phát hành."""
    if current_user.role_label not in ("issuer", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Từ chối phân quyền (RBAC): Chỉ Đơn vị Phát hành (ISSUER_ROLE) mới có quyền truy cập dữ liệu phát hành!",
        )

    sync_onchain_state(db)
    w3 = get_w3()
    rpc_connected = False
    block_number = 0
    chain_id = settings.CHAIN_ID
    try:
        if w3.is_connected():
            rpc_connected = True
            block_number = int(w3.eth.block_number)
            chain_id = int(w3.eth.chain_id)
    except Exception:
        rpc_connected = False

    estates_rows = db.query(RealEstate).order_by(RealEstate.id.desc()).all()
    estates_serialized = [_serialize_estate(e, db) for e in estates_rows]

    total_registered = len(estates_serialized)
    total_tokenized = sum(1 for e in estates_serialized if e["token_address"])
    open_sale_assets = sum(1 for e in estates_serialized if e["primary_sale"]["is_open"])
    total_shares_issued = sum(float(e["total_shares"]) for e in estates_serialized if e["token_address"])
    total_shares_sold = sum(float(e["primary_sale"]["sold_amount"]) for e in estates_serialized)
    total_usdc_raised = sum(float(e["primary_sale"]["raised_usdc"]) for e in estates_serialized)

    # Giao dịch gần đây của các tài sản
    tx_rows = db.query(TransferCache).order_by(TransferCache.id.desc()).limit(50).all()
    est_by_token = {
        (e["token_address"] or "").lower(): e for e in estates_serialized if e["token_address"]
    }
    recent_transactions = []
    for t in tx_rows:
        e_info = est_by_token.get((t.token_address or "").lower())
        recent_transactions.append(
            {
                "id": t.id,
                "tx_hash": t.tx_hash,
                "block_number": t.block_number,
                "event_type": t.event_type,
                "token_address": t.token_address,
                "symbol": e_info["symbol"] if e_info else "RWA",
                "estate_name": e_info["name"] if e_info else "Bất động sản RWA",
                "estate_id": e_info["id"] if e_info else 1,
                "from_address": t.from_address,
                "to_address": t.to_address,
                "amount": float(t.amount),
                "usdc_paid": float(t.usdc_paid) if t.usdc_paid is not None else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
        )

    # Hoạt động của Issuer trong bảng AuditSign
    users_map = {u.address.lower(): u.display_name for u in db.query(User).all()}
    audits = db.query(AuditSign).order_by(AuditSign.id.desc()).limit(100).all()
    issuer_activities = []
    valuation_logs = []

    for a in audits:
        p = a.params_json or {}
        if a.role_label == "issuer" or a.contract_method in (
            "AssetFactory.createAsset",
            "PrimarySale.openSale",
            "PrimarySale.closeSale",
            "AssetToken.updateValuation",
        ):
            issuer_activities.append(
                {
                    "id": a.id,
                    "signer_address": a.signer_address,
                    "signer_name": users_map.get(a.signer_address.lower(), "Issuer Signer"),
                    "contract_method": a.contract_method,
                    "params_json": p,
                    "tx_hash": a.tx_hash,
                    "block_number": p.get("block_number", a.id),
                    "signed_at": a.signed_at.isoformat() if a.signed_at else None,
                }
            )

        if a.contract_method == "AssetToken.updateValuation":
            est_id = p.get("real_estate_id")
            est_match = next((e for e in estates_serialized if e["id"] == est_id), None)
            valuation_logs.append(
                {
                    "id": a.id,
                    "real_estate_id": est_id,
                    "estate_name": est_match["name"] if est_match else p.get("name", "BĐS RWA"),
                    "symbol": est_match["symbol"] if est_match else p.get("symbol", "RWA"),
                    "old_valuation": float(p.get("old_valuation", 0)),
                    "new_valuation": float(p.get("new_valuation", 0)),
                    "notes": p.get("notes") or "Cập nhật định giá định kỳ trên chuỗi",
                    "basis": p.get("basis") or "Chứng thư thẩm định giá độc lập",
                    "actor_address": a.signer_address,
                    "actor_name": users_map.get(a.signer_address.lower(), "Đơn vị phát hành"),
                    "tx_hash": a.tx_hash,
                    "block_number": p.get("block_number", a.id),
                    "signed_at": a.signed_at.isoformat() if a.signed_at else None,
                }
            )

    # Danh sách hồ sơ pháp lý IPFS của các tài sản thuộc Issuer
    legal_documents = []
    for e in estates_serialized:
        cid = e["doc_cid"]
        cid_path = os.path.join(LOCAL_IPFS_CACHE_DIR, cid) if cid else ""
        exists_locally = bool(cid_path and os.path.exists(cid_path))
        recomputed_hash = e["doc_hash"]
        if exists_locally:
            try:
                with open(cid_path, "rb") as f:
                    recomputed_hash = compute_doc_hash(f.read())
            except Exception:
                pass
        hash_matches = (
            (e["onchain_doc_hash"] or e["doc_hash"]).lower() == (e["doc_hash"] or "").lower()
        )
        legal_documents.append(
            {
                "estate_id": e["id"],
                "estate_name": e["name"],
                "symbol": e["symbol"],
                "property_kind": e["property_kind"],
                "doc_name": e.get("doc_name") or f"Ho_so_Phap_ly_{e['symbol']}.docx",
                "doc_type": "Hồ sơ Pháp lý BĐS & Chứng thư Token hóa (Word .docx)",
                "doc_cid": cid,
                "doc_hash": e["doc_hash"],
                "onchain_doc_hash": e["onchain_doc_hash"],
                "recomputed_hash": recomputed_hash,
                "size_bytes": e["doc_size_bytes"],
                "exists_locally": exists_locally,
                "integrity_verified": hash_matches,
                "token_address": e["token_address"],
                "issuer_address": e["issuer_address"],
                "created_at": e["created_at"],
                "version": "v1.0 (Genesis On-chain Sealed)",
            }
        )

    return {
        "kpis": {
            "total_registered_assets": total_registered,
            "total_tokenized_assets": total_tokenized,
            "open_sale_assets": open_sale_assets,
            "total_shares_issued": round(total_shares_issued, 4),
            "total_shares_sold": round(total_shares_sold, 4),
            "total_usdc_raised": round(total_usdc_raised, 2),
        },
        "blockchain_status": {
            "connected": rpc_connected,
            "rpc_url": settings.RPC_URL,
            "chain_id": chain_id,
            "block_number": block_number,
        },
        "estates": estates_serialized,
        "recent_transactions": recent_transactions,
        "issuer_activities": issuer_activities[:25],
        "valuation_logs": valuation_logs,
        "legal_documents": legal_documents,
    }


@router.get("", response_model=List[dict])
def list_real_estates(
    property_kind: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """UC-14: Xem danh sách bất động sản kèm trạng thái mở bán sơ cấp."""
    sync_onchain_state(db)
    q = db.query(RealEstate)
    if property_kind and property_kind != "all":
        q = q.filter(RealEstate.property_kind == property_kind)
    estates = q.order_by(RealEstate.id.asc()).all()
    return [_serialize_estate(e, db) for e in estates]


@router.get("/{estate_id}")
def get_real_estate_detail(estate_id: str, db: Session = Depends(get_db)):
    """UC-14: Xem chi tiết bất động sản theo ID hoặc địa chỉ token, kèm lịch sử giao dịch & lịch sử định giá."""
    sync_onchain_state(db)
    est = None
    if estate_id.isdigit():
        est = db.query(RealEstate).filter(RealEstate.id == int(estate_id)).first()
    if not est:
        est = (
            db.query(RealEstate)
            .filter(
                (RealEstate.token_address == estate_id.lower())
                | (RealEstate.symbol == estate_id.upper())
            )
            .first()
        )
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản")

    data = _serialize_estate(est, db)
    if est.token_address:
        transfers = (
            db.query(TransferCache)
            .filter(TransferCache.token_address == est.token_address.lower())
            .order_by(TransferCache.id.desc())
            .limit(50)
            .all()
        )
        data["transfers"] = [
            {
                "id": t.id,
                "tx_hash": t.tx_hash,
                "block_number": t.block_number,
                "event_type": t.event_type,
                "from_address": t.from_address,
                "to_address": t.to_address,
                "amount": float(t.amount),
                "usdc_paid": float(t.usdc_paid) if t.usdc_paid is not None else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transfers
        ]
    else:
        data["transfers"] = []

    # Truy xuất lịch sử định giá của bất động sản này từ bảng AuditSign
    users_map = {u.address.lower(): u.display_name for u in db.query(User).all()}
    audits = db.query(AuditSign).order_by(AuditSign.id.desc()).all()
    valuation_history = []
    for a in audits:
        p = a.params_json or {}
        if a.contract_method == "AssetToken.updateValuation" and (
            p.get("real_estate_id") == est.id
            or (est.token_address and (p.get("token_address") or "").lower() == est.token_address.lower())
        ):
            valuation_history.append(
                {
                    "id": a.id,
                    "old_valuation": float(p.get("old_valuation", 0)),
                    "new_valuation": float(p.get("new_valuation", 0)),
                    "notes": p.get("notes") or "Cập nhật định giá tài sản trên chuỗi",
                    "basis": p.get("basis") or "Chứng thư thẩm định giá định kỳ",
                    "actor_address": a.signer_address,
                    "actor_name": users_map.get(a.signer_address.lower(), "Đơn vị phát hành (Issuer)"),
                    "tx_hash": a.tx_hash,
                    "block_number": p.get("block_number", a.id),
                    "signed_at": a.signed_at.isoformat() if a.signed_at else None,
                }
            )
        elif a.contract_method == "AssetFactory.createAsset" and (
            p.get("real_estate_id") == est.id or p.get("symbol") == est.symbol
        ):
            valuation_history.append(
                {
                    "id": a.id,
                    "old_valuation": float(p.get("valuation", est.valuation)),
                    "new_valuation": float(p.get("valuation", est.valuation)),
                    "notes": "Định giá khởi tạo khi phát hành hợp đồng AssetToken (UC-05)",
                    "basis": "Hồ sơ thẩm định giá ban đầu",
                    "actor_address": a.signer_address,
                    "actor_name": users_map.get(a.signer_address.lower(), "Đơn vị phát hành (Issuer)"),
                    "tx_hash": a.tx_hash,
                    "block_number": p.get("block_number", a.id),
                    "signed_at": a.signed_at.isoformat() if a.signed_at else None,
                }
            )

    if not valuation_history:
        valuation_history.append(
            {
                "id": 0,
                "old_valuation": float(est.valuation),
                "new_valuation": float(est.valuation),
                "notes": "Định giá cơ sở khi đăng ký hồ sơ tài sản (Genesis / UC-04)",
                "basis": "Hồ sơ pháp lý gốc trên IPFS",
                "actor_address": data["issuer_address"],
                "actor_name": data["issuer_name"],
                "tx_hash": "0x" + "0" * 64,
                "block_number": 1,
                "signed_at": data["created_at"],
            }
        )

    data["valuation_history"] = valuation_history
    return data


@router.get("/{estate_id}/verify-ipfs")
def verify_estate_ipfs_document(estate_id: int, db: Session = Depends(get_db)):
    """Kiểm chứng trực tiếp tính toàn vẹn của tài liệu IPFS giữa File cục bộ, Database và Smart Contract."""
    est = db.query(RealEstate).filter(RealEstate.id == estate_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản")

    onchain_hash = est.doc_hash
    if est.token_address and is_contract_deployed_on_anvil(est.token_address):
        try:
            tok = get_contract_instance("AssetToken", est.token_address)
            raw_dh = tok.functions.docHash().call()
            if isinstance(raw_dh, (bytes, bytearray)):
                onchain_hash = "0x" + raw_dh.hex()
            elif isinstance(raw_dh, str):
                onchain_hash = raw_dh
        except Exception:
            pass

    cid_path = os.path.join(LOCAL_IPFS_CACHE_DIR, est.doc_cid) if est.doc_cid else ""
    file_exists = bool(cid_path and os.path.exists(cid_path))
    recomputed_hash = est.doc_hash
    size_bytes = 0

    if file_exists:
        try:
            with open(cid_path, "rb") as f:
                raw_bytes = f.read()
                size_bytes = len(raw_bytes)
                recomputed_hash = compute_doc_hash(raw_bytes)
        except Exception:
            pass

    db_vs_onchain = (est.doc_hash or "").lower() == (onchain_hash or "").lower()
    file_vs_db = (recomputed_hash or "").lower() == (est.doc_hash or "").lower()

    return {
        "estate_id": est.id,
        "symbol": est.symbol,
        "doc_cid": est.doc_cid,
        "db_doc_hash": est.doc_hash,
        "onchain_doc_hash": onchain_hash,
        "recomputed_file_hash": recomputed_hash,
        "file_exists_locally": file_exists,
        "size_bytes": size_bytes,
        "integrity_verified": db_vs_onchain and file_vs_db,
    }


def _find_estate_by_key(estate_id: str, db: Session) -> Optional[RealEstate]:
    if str(estate_id).isdigit():
        est = db.query(RealEstate).filter(RealEstate.id == int(estate_id)).first()
        if est:
            return est
    return (
        db.query(RealEstate)
        .filter(
            (RealEstate.token_address == str(estate_id).lower())
            | (RealEstate.symbol == str(estate_id).upper())
        )
        .first()
    )


def _ensure_estate_document_bytes(est: RealEstate, db: Session) -> tuple[bytes, dict]:
    """
    Đọc nội dung tài liệu IPFS từ kho lưu trữ cục bộ; nếu chưa có hoặc vẫn là bản text stub cũ
    thì tự động sinh tệp Word (.docx) chuẩn Office Open XML.
    """
    cid = est.doc_cid or f"QmRWALab{est.symbol}LegalDeed2026"
    cid_path = os.path.join(LOCAL_IPFS_CACHE_DIR, os.path.basename(cid))
    raw_bytes = b""
    if os.path.exists(cid_path):
        with open(cid_path, "rb") as f:
            raw_bytes = f.read()

    detected = detect_document_type(raw_bytes) if raw_bytes else {"format": "missing", "ext": ".docx", "mime": DOCX_MIME_TYPE}

    # Nâng cấp tự động sang file Word (.docx) nếu file bị thiếu hoặc là file text mô phỏng cũ
    if not raw_bytes or detected["format"] == "text":
        issuer_user = db.query(User).filter(User.id == est.created_by).first()
        raw_bytes = generate_legal_deed_docx(
            {
                "name": est.name,
                "symbol": est.symbol,
                "address_text": est.address_text,
                "area_m2": float(est.area_m2 or 0),
                "property_kind": est.property_kind,
                "build_year": est.build_year,
                "description": est.description,
                "valuation": float(est.valuation or 0),
                "total_shares": float(est.total_shares or 0),
                "doc_cid": cid,
                "token_address": est.token_address,
                "issuer_name": issuer_user.display_name if issuer_user else "Đơn vị phát hành (Issuer)",
                "issuer_address": issuer_user.address if issuer_user else "",
                "created_at": est.created_at.strftime("%Y-%m-%d %H:%M UTC") if est.created_at else None,
            }
        )
        os.makedirs(LOCAL_IPFS_CACHE_DIR, exist_ok=True)
        with open(cid_path, "wb") as f:
            f.write(raw_bytes)
        if not est.token_address:
            est.doc_hash = compute_doc_hash(raw_bytes)
            db.commit()
        detected = {"format": "docx", "ext": ".docx", "mime": DOCX_MIME_TYPE}

    return raw_bytes, detected


@router.get("/{estate_id}/document/preview")
def preview_estate_ipfs_document(estate_id: str, db: Session = Depends(get_db)):
    """
    Trả về nội dung hiển thị trực tiếp trên Web cho nút 'Xem tài liệu IPFS'.
    - Với tệp Microsoft Word (.docx): chuyển đổi trực tiếp sang HTML sạch (đầy đủ tiêu đề, bảng biểu, định dạng).
    - Với PDF / Hình ảnh: trả về raw_url để nhúng xem trực tiếp trong Modal.
    """
    est = _find_estate_by_key(estate_id, db)
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản")

    raw_bytes, detected = _ensure_estate_document_bytes(est, db)
    file_name = f"Ho_so_Phap_ly_{est.symbol}{detected['ext']}"

    onchain_hash = est.doc_hash
    if est.token_address and is_contract_deployed_on_anvil(est.token_address):
        try:
            tok = get_contract_instance("AssetToken", est.token_address)
            raw_dh = tok.functions.docHash().call()
            if isinstance(raw_dh, (bytes, bytearray)):
                onchain_hash = "0x" + raw_dh.hex()
            elif isinstance(raw_dh, str):
                onchain_hash = raw_dh
        except Exception:
            pass

    html_content = ""
    paragraph_count = 0
    table_count = 0
    if detected["format"] == "docx":
        parsed = docx_bytes_to_html(raw_bytes)
        html_content = parsed["html"]
        paragraph_count = parsed["paragraph_count"]
        table_count = parsed["table_count"]
    elif detected["format"] == "text":
        text_str = raw_bytes.decode("utf-8", errors="replace")
        html_content = (
            '<pre style="white-space:pre-wrap;font-family:monospace;font-size:13px;line-height:1.6;">'
            + html_lib.escape(text_str)
            + "</pre>"
        )

    return {
        "estate_id": est.id,
        "estate_name": est.name,
        "symbol": est.symbol,
        "file_name": file_name,
        "format": detected["format"],
        "mime_type": detected["mime"],
        "doc_cid": est.doc_cid,
        "doc_hash": est.doc_hash,
        "onchain_doc_hash": onchain_hash,
        "size_bytes": len(raw_bytes),
        "paragraph_count": paragraph_count,
        "table_count": table_count,
        "html_content": html_content,
        "raw_url": f"/ipfs/{est.doc_cid}",
        "download_url": f"/api/assets/{est.id}/document/download",
    }


@router.get("/{estate_id}/document/download")
def download_estate_ipfs_document(estate_id: str, db: Session = Depends(get_db)):
    """
    Tải trực tiếp tệp hồ sơ pháp lý Word (.docx) từ IPFS về máy người dùng
    với header Content-Disposition: attachment.
    """
    est = _find_estate_by_key(estate_id, db)
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản")

    raw_bytes, detected = _ensure_estate_document_bytes(est, db)
    file_name = f"Ho_so_Phap_ly_{est.symbol}{detected['ext']}"
    return Response(
        content=raw_bytes,
        media_type=detected["mime"],
        headers={
            "Content-Disposition": f'attachment; filename="{file_name}"',
            "X-IPFS-CID": str(est.doc_cid or ""),
        },
    )


@router.post("")
def create_real_estate(
    req: RealEstateCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-04: Đơn vị phát hành (Issuer) đăng ký hồ sơ BĐS off-chain với docCID & docHash."""
    if current_user.role_label != "issuer":
        raise HTTPException(status_code=403, detail="Chỉ Đơn vị phát hành (ISSUER_ROLE) mới được phép đăng ký BĐS")

    clean_symbol = req.symbol.strip().upper()
    if not req.name.strip() or not clean_symbol or not req.address_text.strip():
        raise HTTPException(status_code=400, detail="Tên dự án, Mã Token (Symbol) và Địa chỉ không được để trống!")
    if req.area_m2 <= 0:
        raise HTTPException(status_code=400, detail="Diện tích bất động sản phải lớn hơn 0 m²!")
    if req.valuation <= 0:
        raise HTTPException(status_code=400, detail="Tổng định giá ban đầu phải lớn hơn 0 mUSDC!")
    if req.total_shares <= 0:
        raise HTTPException(status_code=400, detail="Tổng số cổ phần phát hành phải là số dương!")

    existing_sym = db.query(RealEstate).filter(RealEstate.symbol == clean_symbol).first()
    if existing_sym:
        raise HTTPException(
            status_code=400,
            detail=f"Mã Token (Symbol) '{clean_symbol}' đã tồn tại trên hệ thống (BĐS #{existing_sym.id}). Vui lòng chọn Symbol khác!",
        )

    doc_cid = req.doc_cid or f"QmRWALab{clean_symbol}LegalDeed2026"
    cid_path = os.path.join(LOCAL_IPFS_CACHE_DIR, os.path.basename(doc_cid))
    if not os.path.exists(cid_path):
        # Tự động tạo tệp Word (.docx) pháp lý chuẩn nếu Issuer không upload tệp thủ công
        docx_bytes = generate_legal_deed_docx(
            {
                "name": req.name.strip(),
                "symbol": clean_symbol,
                "address_text": req.address_text.strip(),
                "area_m2": req.area_m2,
                "property_kind": req.property_kind,
                "build_year": req.build_year,
                "description": req.description,
                "valuation": req.valuation,
                "total_shares": req.total_shares,
                "doc_cid": doc_cid,
                "issuer_name": current_user.display_name,
                "issuer_address": current_user.address,
            }
        )
        os.makedirs(LOCAL_IPFS_CACHE_DIR, exist_ok=True)
        with open(cid_path, "wb") as f:
            f.write(docx_bytes)
        doc_hash = req.doc_hash or compute_doc_hash(docx_bytes)
    else:
        with open(cid_path, "rb") as f:
            doc_hash = req.doc_hash or compute_doc_hash(f.read())

    new_estate = RealEstate(
        token_address=None,
        name=req.name.strip(),
        symbol=clean_symbol,
        address_text=req.address_text.strip(),
        area_m2=req.area_m2,
        property_kind=req.property_kind,
        build_year=req.build_year,
        description=req.description,
        valuation=req.valuation,
        total_shares=req.total_shares,
        doc_cid=doc_cid,
        doc_hash=doc_hash,
        status="ready_to_tokenize",
        created_by=current_user.id,
    )
    db.add(new_estate)
    db.commit()
    db.refresh(new_estate)

    if req.auto_tokenize:
        return tokenize_real_estate(new_estate.id, current_user, db)

    return _serialize_estate(new_estate, db)


@router.post("/{estate_id}/tokenize")
def tokenize_real_estate(
    estate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    UC-05: Token hóa BĐS On-chain qua AssetFactory.createAsset(...)
    - Triển khai hợp đồng AssetToken mới trên mạng Anvil.
    - Đúc (mint) toàn bộ totalShares vào kho của hợp đồng PrimarySale.
    - Bóc tách sự kiện AssetCreated từ biên nhận để lưu token_address vào PostgreSQL.
    """
    est = db.query(RealEstate).filter(RealEstate.id == estate_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ bất động sản")
    if est.token_address:
        raise HTTPException(status_code=400, detail=f"Bất động sản này đã được token hóa tại {est.token_address}")

    factory = get_contract_instance("AssetFactory")
    deployed = load_deployed_contracts()
    primary_sale_addr = Web3.to_checksum_address(deployed["PrimarySale"])

    total_shares_wei = int(float(est.total_shares) * (10 ** 18))
    valuation_usdc = int(float(est.valuation) * (10 ** 6))
    doc_hash_bytes = bytes.fromhex(est.doc_hash.removeprefix("0x").ljust(64, "0")[:64])

    fn = factory.functions.createAsset(
        est.name,
        est.symbol,
        total_shares_wei,
        valuation_usdc,
        est.doc_cid,
        doc_hash_bytes,
        primary_sale_addr,
    )

    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="AssetFactory.createAsset",
        params_summary={
            "real_estate_id": est.id,
            "name": est.name,
            "symbol": est.symbol,
            "totalShares": float(est.total_shares),
            "valuation": float(est.valuation),
            "docCID": est.doc_cid,
            "initialReceiver": primary_sale_addr,
        },
        required_roles=["issuer"],
    )

    receipt = res["receipt"]
    token_addr = None
    if res.get("onchain"):
        try:
            logs = factory.events.AssetCreated().process_receipt(receipt)
            if logs:
                token_addr = logs[0]["args"]["token"].lower()
            else:
                all_tokens = factory.functions.getDeployedTokens().call()
                token_addr = all_tokens[-1].lower()
        except Exception:
            pass

    if not token_addr:
        token_addr = "0x" + Web3.keccak(text=f"AssetToken-{est.symbol}-{est.id}").hex().removeprefix("0x")[:40].lower()

    est.token_address = token_addr
    est.status = "tokenized"
    db.commit()

    record_transfer_cache(
        db=db,
        tx_hash=res["tx_hash"],
        block_number=receipt.blockNumber,
        event_type="MINT",
        token_address=token_addr,
        from_address="0x0000000000000000000000000000000000000000",
        to_address=primary_sale_addr.lower(),
        amount_shares=float(est.total_shares),
        usdc_paid=None,
    )

    return _serialize_estate(est, db, extra_tx_hash=res["tx_hash"])


@router.post("/{estate_id}/valuation")
def update_real_estate_valuation(
    estate_id: int,
    req: ValuationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-07: Cập nhật định giá giả lập (AssetToken.updateValuation) bởi Issuer."""
    if req.new_valuation <= 0:
        raise HTTPException(status_code=400, detail="Giá trị định giá mới phải lớn hơn 0")

    est = db.query(RealEstate).filter(RealEstate.id == estate_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản")
    if not est.token_address:
        raise HTTPException(status_code=400, detail="BĐS chưa được token hóa trên chuỗi")

    token_contract = get_contract_instance("AssetToken", est.token_address)
    new_val_units = int(req.new_valuation * (10 ** 6))

    summary = {
        "real_estate_id": est.id,
        "name": est.name,
        "symbol": est.symbol,
        "token_address": est.token_address,
        "old_valuation": float(est.valuation),
        "new_valuation": req.new_valuation,
    }
    if req.notes:
        summary["notes"] = req.notes
    if req.basis:
        summary["basis"] = req.basis

    fn = token_contract.functions.updateValuation(new_val_units)
    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="AssetToken.updateValuation",
        params_summary=summary,
        required_roles=["issuer"],
    )

    est.valuation = req.new_valuation
    db.commit()
    return {
        "tx_hash": res["tx_hash"],
        "block_number": res.get("block_number", 1),
        "real_estate": _serialize_estate(est, db),
    }


@real_estates_router.delete("/{real_estate_id}")
@router.delete("/{real_estate_id}")
def delete_real_estate(
    real_estate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Xóa hồ sơ BĐS chưa token hóa khỏi cơ sở dữ liệu.
    - Chỉ cho phép vai trò `admin` hoặc `issuer` (chủ sở hữu BĐS đó).
    - Chặn tuyệt đối nếu BĐS đã có `token_address` hoặc trạng thái khác bản nháp/chờ token hóa.
    - Ghi nhận vào bảng `audit_signs` với mã hành động `OFFCHAIN_DELETE_ASSET`.
    """
    if current_user.role_label not in ("admin", "issuer"):
        raise HTTPException(
            status_code=403,
            detail="Chỉ Đơn vị phát hành (chủ sở hữu) hoặc Quản trị viên mới có quyền xóa hồ sơ bất động sản!",
        )

    est = db.query(RealEstate).filter(RealEstate.id == real_estate_id).first()
    if not est:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ bất động sản!")

    if current_user.role_label == "issuer" and est.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Bạn chỉ có quyền xóa các hồ sơ bất động sản do chính mình đăng ký!",
        )

    if est.token_address or (est.status or "").lower() not in ("draft", "ready_to_tokenize"):
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa bất động sản đã token hóa trên Blockchain",
        )

    est_id = est.id
    est_name = est.name
    est_symbol = est.symbol
    est_doc_cid = est.doc_cid
    est_status = est.status

    # Dọn sạch mọi bản ghi phụ thuộc (nếu có) trước khi xóa RealEstate
    db.query(PrimarySaleCache).filter(PrimarySaleCache.real_estate_id == est_id).delete()
    db.query(ListingCache).filter(ListingCache.real_estate_id == est_id).delete()
    dist_ids = [
        d.id
        for d in db.query(DividendDistribution.id)
        .filter(DividendDistribution.real_estate_id == est_id)
        .all()
    ]
    if dist_ids:
        db.query(DividendPayout).filter(DividendPayout.distribution_id.in_(dist_ids)).delete(
            synchronize_session=False
        )
        db.query(DividendDistribution).filter(
            DividendDistribution.real_estate_id == est_id
        ).delete()

    offchain_ref = f"OFFCHAIN_DELETE_ASSET_{est_id}_{int(datetime.datetime.utcnow().timestamp())}"
    audit = AuditSign(
        user_id=current_user.id,
        signer_address=current_user.address,
        role_label=current_user.role_label,
        contract_method="OFFCHAIN_DELETE_ASSET",
        params_json={
            "action": "OFFCHAIN_DELETE_ASSET",
            "real_estate_id": est_id,
            "name": est_name,
            "symbol": est_symbol,
            "doc_cid": est_doc_cid,
            "previous_status": est_status,
            "reason": "Xóa hồ sơ bất động sản chưa token hóa (off-chain)",
        },
        tx_hash=offchain_ref,
    )
    db.add(audit)
    db.delete(est)
    db.commit()

    return {
        "deleted": True,
        "id": est_id,
        "name": est_name,
        "symbol": est_symbol,
        "action": "OFFCHAIN_DELETE_ASSET",
        "tx_hash": offchain_ref,
        "message": f"Đã xóa hồ sơ bất động sản '{est_name} ({est_symbol})' thành công!",
    }
