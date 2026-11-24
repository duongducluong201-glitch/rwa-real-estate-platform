import os
import datetime
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .config import settings, LAB_SEED_ACCOUNTS, load_deployed_contracts
from .database import engine, Base, SessionLocal
from .models import (
    User,
    SessionModel,
    KYCApplication,
    RealEstate,
    AuditSign,
    PrimarySaleCache,
    ListingCache,
    TransferCache,
    Notification,
    DividendDistribution,
    DividendPayout,
    EmailLog,
    PaymentOTP,
)
from sqlalchemy import inspect as sa_inspect, text as sa_text
from .api import auth, kyc, assets, transactions, notifications, dividends, system, payments
from .services.auth import hash_password
from .services.ipfs import LOCAL_IPFS_CACHE_DIR, compute_doc_hash
from .services.docx_service import detect_document_type, generate_legal_deed_docx

# Khởi tạo toàn bộ bảng dữ liệu theo ERD Chương 2
Base.metadata.create_all(bind=engine)


def ensure_user_auth_columns():
    """Tự động bổ sung các cột xác thực (username, email, password_hash, private_key) nếu DB cũ chưa có."""
    try:
        inspector = sa_inspect(engine)
        if "users" not in inspector.get_table_names():
            return
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        alter_stmts = []
        if "username" not in existing_cols:
            alter_stmts.append("ALTER TABLE users ADD COLUMN username VARCHAR(60)")
        if "email" not in existing_cols:
            alter_stmts.append("ALTER TABLE users ADD COLUMN email VARCHAR(120)")
        if "password_hash" not in existing_cols:
            alter_stmts.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)")
        if "private_key" not in existing_cols:
            alter_stmts.append("ALTER TABLE users ADD COLUMN private_key VARCHAR(128)")
        if alter_stmts:
            with engine.begin() as conn:
                for stmt in alter_stmts:
                    conn.execute(sa_text(stmt))
    except Exception as exc:
        print(f"[DB Migration Notice] {exc}")


ensure_user_auth_columns()

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Hệ thống Backend mô phỏng Token hóa Bất động sản (RWA) trên mạng cục bộ Anvil (:8545) "
        "với cơ chế Session Lab, Server-side Signing (audit_signs), Pinata IPFS và Event Indexer."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    fields = []
    for err in errors[:3]:
        loc = " -> ".join(str(x) for x in err.get("loc", []) if x != "body")
        msg = err.get("msg", "không hợp lệ")
        fields.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Dữ liệu đầu vào không hợp lệ (" + "; ".join(fields) + ")",
            "errors": errors,
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(request: Request, exc: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Dữ liệu bị trùng lặp hoặc xung đột ràng buộc cơ sở dữ liệu. Vui lòng kiểm tra lại!",
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Lỗi truy vấn cơ sở dữ liệu tạm thời. Vui lòng thử lại sau!",
        },
    )

if os.path.exists(LOCAL_IPFS_CACHE_DIR):
    app.mount("/ipfs", StaticFiles(directory=LOCAL_IPFS_CACHE_DIR), name="ipfs")

# Đăng ký routers ở cả /api/* và /* để tương thích hoàn toàn với đặc tả Chương 2 và Frontend
for prefix in ["/api", ""]:
    app.include_router(auth.router, prefix=prefix)
    app.include_router(kyc.router, prefix=prefix)
    app.include_router(assets.router, prefix=prefix)
    app.include_router(transactions.router, prefix=prefix)
    app.include_router(notifications.router, prefix=prefix)
    app.include_router(dividends.router, prefix=prefix)
    app.include_router(system.router, prefix=prefix)
    app.include_router(payments.router, prefix=prefix)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": settings.APP_NAME,
        "rpc_url": settings.RPC_URL,
        "chain_id": settings.CHAIN_ID,
        "contracts": load_deployed_contracts(),
        "docs": "/docs",
    }


@app.get("/api/contracts")
@app.get("/contracts")
def get_deployed_contracts_api():
    return load_deployed_contracts()


def seed_initial_data():
    db = SessionLocal()
    try:
        # 1. Seed & đồng bộ 5 tài khoản Lab cố định theo vai trò (Admin, Issuer, Compliance, Investor A, Investor B)
        default_pw_hash = hash_password("123456")
        if db.query(User).count() == 0:
            for acc in LAB_SEED_ACCOUNTS:
                u = User(
                    username=acc.get("username"),
                    email=acc.get("email"),
                    password_hash=default_pw_hash,
                    private_key=acc.get("private_key"),
                    address=acc["address"].lower(),
                    role_label=acc["role_label"],
                    display_name=acc["display_name"],
                    is_whitelisted=acc["is_whitelisted"],
                    is_frozen=False,
                )
                db.add(u)
            db.commit()
        else:
            changed = False
            for acc in LAB_SEED_ACCOUNTS:
                u = db.query(User).filter(User.address == acc["address"].lower()).first()
                if u:
                    if not u.username and acc.get("username"):
                        u.username = acc["username"]
                        changed = True
                    if not u.email and acc.get("email"):
                        u.email = acc["email"]
                        changed = True
                    if not u.password_hash:
                        u.password_hash = default_pw_hash
                        changed = True
                    if not u.private_key and acc.get("private_key"):
                        u.private_key = acc["private_key"]
                        changed = True
            if changed:
                db.commit()

        issuer_user = db.query(User).filter(User.role_label == "issuer").first()
        compliance_user = db.query(User).filter(User.role_label == "compliance").first()
        investors = db.query(User).filter(User.role_label == "investor").order_by(User.id.asc()).all()

        # 2. Seed hồ sơ KYC chuẩn cho Nhà đầu tư A (approved) và Nhà đầu tư B (pending chờ Compliance duyệt)
        # Không gắn trùng địa chỉ ví của Investor B hoặc Issuer cho nhiều hồ sơ khác nhau (tránh mâu thuẫn UC-02 E2/E3)
        if db.query(KYCApplication).count() == 0 and len(investors) >= 2:
            inv_a, inv_b = investors[0], investors[1]
            sample_kyc_rows = [
                KYCApplication(
                    user_id=inv_a.id,
                    status="approved",
                    payload_json={
                        "full_name": "Nguyễn Văn An (Nhà đầu tư A)",
                        "subject_type": "Investor",
                        "document_type": "National ID",
                        "id_number": "001099012345",
                        "email": "nguyenvanan@rwa-lab.vn",
                        "phone": "0912345678",
                        "doc_cid": "QmKYCInvestorAVerifiedDoc2026",
                        "doc_name": "cccd_nguyen_van_an.pdf",
                        "notes": "Hồ sơ KYC hợp lệ đã được xác minh danh sách trắng khi khởi tạo Lab.",
                    },
                    reviewed_by=compliance_user.id if compliance_user else None,
                    tx_hash="0x" + "a1" * 32,
                    reviewed_at=datetime.datetime.utcnow(),
                ),
                KYCApplication(
                    user_id=inv_b.id,
                    status="pending",
                    payload_json={
                        "full_name": "Trần Thị Bình (Nhà đầu tư B)",
                        "subject_type": "Investor",
                        "document_type": "National ID",
                        "id_number": "079198054321",
                        "email": "tranthibinh@rwa-lab.vn",
                        "phone": "0987654321",
                        "doc_cid": "QmKYCInvestorBPendingDoc2026",
                        "doc_name": "cccd_tran_thi_binh.pdf",
                        "notes": "Hồ sơ đang chờ Cán bộ tuân thủ (Compliance) thẩm định và gọi addToWhitelist.",
                    },
                ),
            ]
            db.add_all(sample_kyc_rows)
            db.commit()

        # 3. Seed 3 hồ sơ Bất động sản mẫu (Căn hộ, Đất nền, Tòa nhà thương mại)
        if db.query(RealEstate).count() == 0 and issuer_user:
            deployed = load_deployed_contracts()
            sample_token_addr = deployed.get("SampleAssetToken", "").lower() or None

            # Tạo tệp hồ sơ pháp lý chuẩn Microsoft Word (.docx) trong thư mục IPFS cache cục bộ
            cid1 = "QmVinhomesPenthouseLegalDeed2026"
            doc1_content = generate_legal_deed_docx(
                {
                    "name": "Penthouse Vinhomes Central Park",
                    "symbol": "VINH01",
                    "address_text": "Tầng 42, Tòa Landmark 2, 208 Nguyễn Hữu Cảnh, Bình Thạnh, TP.HCM",
                    "area_m2": 250.0,
                    "property_kind": "apartment",
                    "build_year": 2023,
                    "description": "Căn hộ Penthouse thông tầng hướng sông Sài Gòn, diện tích 250m2, đã token hóa thành 10,000 phần sở hữu chuẩn ERC-20 có kiểm soát tuân thủ.",
                    "valuation": 1_000_000.0,
                    "total_shares": 10_000.0,
                    "doc_cid": cid1,
                    "token_address": sample_token_addr,
                    "issuer_name": issuer_user.display_name,
                    "issuer_address": issuer_user.address,
                }
            )
            with open(os.path.join(LOCAL_IPFS_CACHE_DIR, cid1), "wb") as f:
                f.write(doc1_content)
            hash1 = "0x" + Web3_keccak_text("Penthouse-Vinhomes-Central-Park-Legal-Deed-2026")

            est1 = RealEstate(
                token_address=sample_token_addr,
                name="Penthouse Vinhomes Central Park",
                symbol="VINH01",
                address_text="Tầng 42, Tòa Landmark 2, 208 Nguyễn Hữu Cảnh, Bình Thạnh, TP.HCM",
                area_m2=250.0,
                property_kind="apartment",
                build_year=2023,
                description="Căn hộ Penthouse thông tầng hướng sông Sài Gòn, diện tích 250m2, đã token hóa thành 10,000 phần sở hữu chuẩn ERC-20 có kiểm soát tuân thủ.",
                valuation=1_000_000.0,
                total_shares=10_000.0,
                doc_cid=cid1,
                doc_hash=hash1,
                status="open_sale" if sample_token_addr else "ready_to_tokenize",
                created_by=issuer_user.id,
            )

            cid2 = "QmThuThiemLandPlotLegalDeed2026"
            doc2_content = generate_legal_deed_docx(
                {
                    "name": "Lô Đất Nền Thương Mại Thủ Thiêm",
                    "symbol": "THUT02",
                    "address_text": "Lô 3-15, Đại lộ Vòng Cung, Khu đô thị mới Thủ Thiêm, TP. Thủ Đức",
                    "area_m2": 500.0,
                    "property_kind": "land",
                    "build_year": 2025,
                    "description": "Lô đất nền quy hoạch thương mại dịch vụ mặt tiền Đại lộ Vòng Cung, sẵn sàng kích hoạt AssetFactory.createAsset() để phát hành token.",
                    "valuation": 2_000_000.0,
                    "total_shares": 20_000.0,
                    "doc_cid": cid2,
                    "issuer_name": issuer_user.display_name,
                    "issuer_address": issuer_user.address,
                }
            )
            with open(os.path.join(LOCAL_IPFS_CACHE_DIR, cid2), "wb") as f:
                f.write(doc2_content)
            hash2 = compute_doc_hash(doc2_content)

            est2 = RealEstate(
                token_address=None,
                name="Lô Đất Nền Thương Mại Thủ Thiêm",
                symbol="THUT02",
                address_text="Lô 3-15, Đại lộ Vòng Cung, Khu đô thị mới Thủ Thiêm, TP. Thủ Đức",
                area_m2=500.0,
                property_kind="land",
                build_year=2025,
                description="Lô đất nền quy hoạch thương mại dịch vụ mặt tiền Đại lộ Vòng Cung, sẵn sàng kích hoạt AssetFactory.createAsset() để phát hành token.",
                valuation=2_000_000.0,
                total_shares=20_000.0,
                doc_cid=cid2,
                doc_hash=hash2,
                status="ready_to_tokenize",
                created_by=issuer_user.id,
            )

            cid3 = "QmTechnoParkCommercialFloor2026"
            doc3_content = generate_legal_deed_docx(
                {
                    "name": "Sàn Văn Phòng TechnoPark Tower Hạng A",
                    "symbol": "TECH03",
                    "address_text": "Tầng 18, Tòa nhà TechnoPark Tower, Vinhomes Ocean Park, Gia Lâm, Hà Nội",
                    "area_m2": 1200.0,
                    "property_kind": "building",
                    "build_year": 2022,
                    "description": "Sàn văn phòng thương mại hạng A tiêu chuẩn LEED Platinum, diện tích 1,200m2, minh họa phân mảnh bất động sản thương mại.",
                    "valuation": 3_600_000.0,
                    "total_shares": 30_000.0,
                    "doc_cid": cid3,
                    "issuer_name": issuer_user.display_name,
                    "issuer_address": issuer_user.address,
                }
            )
            with open(os.path.join(LOCAL_IPFS_CACHE_DIR, cid3), "wb") as f:
                f.write(doc3_content)
            hash3 = compute_doc_hash(doc3_content)

            est3 = RealEstate(
                token_address=None,
                name="Sàn Văn Phòng TechnoPark Tower Hạng A",
                symbol="TECH03",
                address_text="Tầng 18, Tòa nhà TechnoPark Tower, Vinhomes Ocean Park, Gia Lâm, Hà Nội",
                area_m2=1200.0,
                property_kind="building",
                build_year=2022,
                description="Sàn văn phòng thương mại hạng A tiêu chuẩn LEED Platinum, diện tích 1,200m2, minh họa phân mảnh bất động sản thương mại.",
                valuation=3_600_000.0,
                total_shares=30_000.0,
                doc_cid=cid3,
                doc_hash=hash3,
                status="ready_to_tokenize",
                created_by=issuer_user.id,
            )

            db.add_all([est1, est2, est3])
            db.commit()
            db.refresh(est1)

            if est1.token_address:
                ps_cache = PrimarySaleCache(
                    real_estate_id=est1.id,
                    token_address=est1.token_address,
                    price_per_share=100.0,
                    total_amount=5_000.0,
                    remaining_amount=5_000.0,
                    is_open=True,
                )
                db.add(ps_cache)
                db.commit()

    finally:
        db.close()


def Web3_keccak_text(text: str) -> str:
    from .services.w3_compat import Web3
    return Web3.keccak(text=text).hex()


def ensure_word_ipfs_documents(db):
    """Tự động nâng cấp các tệp IPFS dạng text mô phỏng cũ sang tệp Microsoft Word (.docx) thật."""
    os.makedirs(LOCAL_IPFS_CACHE_DIR, exist_ok=True)
    estates = db.query(RealEstate).all()
    changed = False
    for est in estates:
        if not est.doc_cid:
            continue
        cid_path = os.path.join(LOCAL_IPFS_CACHE_DIR, os.path.basename(est.doc_cid))
        needs_upgrade = True
        if os.path.exists(cid_path):
            try:
                with open(cid_path, "rb") as f:
                    raw = f.read()
                detected = detect_document_type(raw)
                if detected["format"] in ("docx", "pdf", "image", "doc"):
                    needs_upgrade = False
            except Exception:
                needs_upgrade = True

        if needs_upgrade:
            issuer_user = db.query(User).filter(User.id == est.created_by).first()
            docx_bytes = generate_legal_deed_docx(
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
                    "doc_cid": est.doc_cid,
                    "token_address": est.token_address,
                    "issuer_name": issuer_user.display_name if issuer_user else "Đơn vị phát hành (Issuer)",
                    "issuer_address": issuer_user.address if issuer_user else "",
                    "created_at": est.created_at.strftime("%Y-%m-%d %H:%M UTC") if est.created_at else None,
                }
            )
            with open(cid_path, "wb") as f:
                f.write(docx_bytes)
            if not est.token_address:
                est.doc_hash = compute_doc_hash(docx_bytes)
                changed = True
    if changed:
        db.commit()


@app.on_event("startup")
def on_startup():
    seed_initial_data()
    # Kiểm tra & nâng cấp tài liệu IPFS sang Word (.docx) + đồng bộ cờ whitelist/frozen với Anvil
    db = SessionLocal()
    try:
        ensure_word_ipfs_documents(db)
        report = system.inspect_chain_db_sync(db)
        if report["rpc_connected"] and report["drift_count"] > 0:
            admin_user = db.query(User).filter(User.role_label == "admin").first()
            if admin_user:
                system.reconcile_db_with_chain(current_user=admin_user, db=db)
    except Exception:
        pass
    finally:
        db.close()
