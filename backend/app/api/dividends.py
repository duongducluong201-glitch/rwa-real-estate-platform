from typing import Optional
from decimal import Decimal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, RealEstate, DividendDistribution, DividendPayout
from ..services.auth import get_current_user
from ..services.signer import SignerService, get_contract_instance, is_contract_deployed_on_anvil
from ..services.w3_compat import Web3
from .notifications import create_notification

router = APIRouter(prefix="/dividends", tags=["Phân phối Cổ tức / Lợi tức BĐS (Dividends)"])


class DividendDistributeRequest(BaseModel):
    real_estate_id: int
    total_amount_usdc: float = Field(..., gt=0, description="Tổng quỹ cổ tức mUSDC phân phối đợt này")
    period_label: str = Field(..., min_length=2, max_length=120, description="Kỳ phân phối, VD: Q4/2026 - Doanh thu cho thuê")
    notes: Optional[str] = None


@router.post("/distribute")
def distribute_dividend(
    req: DividendDistributeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Phân phối cổ tức / doanh thu cho thuê (mUSDC) theo tỷ lệ nắm giữ thực tế on-chain (Snapshot).
    - Chỉ ISSUER_ROLE hoặc DEFAULT_ADMIN_ROLE được phép thực hiện.
    - Chỉ phân phối cho các nhà đầu tư có số dư cổ phần > 0, đã duyệt KYC (isVerified) và không bị đóng băng (!isFrozen).
    - Tự động chuyển mUSDC on-chain từ ví đơn vị phát hành sang từng ví nhà đầu tư qua MockUSDC.transfer().
    """
    if current_user.role_label not in ("issuer", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Từ chối phân quyền (403 RBAC): Chỉ ISSUER_ROLE hoặc DEFAULT_ADMIN_ROLE mới được phép phân phối cổ tức!",
        )

    asset = db.query(RealEstate).filter(RealEstate.id == req.real_estate_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ bất động sản")
    if not asset.token_address:
        raise HTTPException(status_code=400, detail="Bất động sản này chưa được Token hóa trên Blockchain!")

    token_contract = get_contract_instance("AssetToken", asset.token_address)
    registry = get_contract_instance("IdentityRegistry")
    usdc = get_contract_instance("MockUSDC")

    # 1. Chụp snapshot tỷ lệ nắm giữ thực tế của tất cả Nhà đầu tư hợp lệ
    investors = db.query(User).filter(User.role_label == "investor").all()
    eligible_holders = []
    excluded_holders = []

    for inv in investors:
        cs_addr = Web3.to_checksum_address(inv.address)
        try:
            bal_wei = int(token_contract.functions.balanceOf(cs_addr).call())
        except Exception:
            bal_wei = 0

        if bal_wei <= 0:
            continue

        shares = bal_wei / 1e18
        try:
            verified = bool(registry.functions.isVerified(cs_addr).call())
        except Exception:
            verified = bool(inv.is_whitelisted)
        try:
            frozen = bool(token_contract.functions.isFrozen(cs_addr).call())
        except Exception:
            frozen = bool(inv.is_frozen)

        if not verified or frozen:
            excluded_holders.append(
                {
                    "address": inv.address,
                    "display_name": inv.display_name,
                    "shares": shares,
                    "reason": "Ví đang bị đóng băng (Frozen)" if frozen else "Chưa xác minh KYC (Not Whitelisted)",
                }
            )
            continue

        eligible_holders.append({"user": inv, "shares": shares, "shares_wei": bal_wei})

    if not eligible_holders:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Không có nhà đầu tư hợp lệ nào đang nắm giữ cổ phần {asset.symbol} (đã KYC & không bị đóng băng). "
                "Hãy thực hiện mua sơ cấp trước khi phân phối cổ tức."
            ),
        )

    total_eligible_shares = sum(h["shares"] for h in eligible_holders)
    total_usdc_raw = int(round(req.total_amount_usdc * 1_000_000))

    # 2. Kiểm tra số dư mUSDC của Issuer/Admin; nếu thiếu trên Lab Anvil thì tự động nạp từ Faucet MockUSDC
    cs_distributor = Web3.to_checksum_address(current_user.address)
    if is_contract_deployed_on_anvil(usdc.address):
        try:
            dist_usdc_bal = int(usdc.functions.balanceOf(cs_distributor).call())
            if dist_usdc_bal < total_usdc_raw:
                needed = min(total_usdc_raw - dist_usdc_bal + 10_000 * 1_000_000, 500_000 * 1_000_000)
                faucet_fn = usdc.functions.faucet(cs_distributor, needed)
                SignerService.sign_and_send(
                    db=db,
                    current_user=current_user,
                    contract_function=faucet_fn,
                    contract_method_name="MockUSDC.faucet",
                    params_summary={"reason": "Nạp quỹ cổ tức mUSDC (Lab)", "amount_usdc": needed / 1e6},
                    required_roles=["issuer", "admin"],
                )
        except HTTPException:
            raise
        except Exception:
            pass

    # 3. Tạo bản ghi đợt phân phối cổ tức
    dist = DividendDistribution(
        real_estate_id=asset.id,
        token_address=asset.token_address.lower(),
        asset_symbol=asset.symbol,
        period_label=req.period_label.strip(),
        total_amount_usdc=Decimal(str(round(req.total_amount_usdc, 6))),
        total_eligible_shares=Decimal(str(round(total_eligible_shares, 8))),
        recipients_count=len(eligible_holders),
        distributed_by=current_user.id,
        notes=req.notes or "",
    )
    db.add(dist)
    db.commit()
    db.refresh(dist)

    payout_results = []
    for h in eligible_holders:
        inv: User = h["user"]
        ownership_ratio = h["shares"] / total_eligible_shares
        payout_usdc_float = round(req.total_amount_usdc * ownership_ratio, 6)
        payout_usdc_raw = int(round(payout_usdc_float * 1_000_000))
        if payout_usdc_raw <= 0:
            continue

        cs_inv = Web3.to_checksum_address(inv.address)
        fn = usdc.functions.transfer(cs_inv, payout_usdc_raw)
        tx_res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=fn,
            contract_method_name="Dividend.distributeUSDC",
            params_summary={
                "distribution_id": dist.id,
                "asset_symbol": asset.symbol,
                "token_address": asset.token_address.lower(),
                "period_label": dist.period_label,
                "recipient": inv.address.lower(),
                "shares_held": round(h["shares"], 4),
                "ownership_pct": round(ownership_ratio * 100, 4),
                "payout_usdc": payout_usdc_float,
            },
            required_roles=["issuer", "admin"],
        )

        payout = DividendPayout(
            distribution_id=dist.id,
            investor_id=inv.id,
            investor_address=inv.address.lower(),
            shares_held=Decimal(str(round(h["shares"], 8))),
            ownership_pct=Decimal(str(round(ownership_ratio * 100, 6))),
            payout_usdc=Decimal(str(payout_usdc_float)),
            tx_hash=tx_res["tx_hash"],
            status="SUCCESS",
        )
        db.add(payout)
        db.commit()

        create_notification(
            db=db,
            user_id=inv.id,
            category="dividend",
            title=f"Nhận cổ tức {asset.symbol} ({dist.period_label})",
            message=(
                f"Bạn vừa nhận +{payout_usdc_float:,.2f} mUSDC cổ tức từ bất động sản {asset.name} "
                f"({asset.symbol}) tương ứng {round(ownership_ratio * 100, 2)}% cổ phần hợp lệ."
            ),
            tx_hash=tx_res["tx_hash"],
        )

        payout_results.append(
            {
                "investor_name": inv.display_name,
                "investor_address": inv.address,
                "shares_held": round(h["shares"], 4),
                "ownership_pct": round(ownership_ratio * 100, 4),
                "payout_usdc": payout_usdc_float,
                "tx_hash": tx_res["tx_hash"],
                "status": "SUCCESS",
            }
        )

    return {
        "distribution_id": dist.id,
        "asset_symbol": asset.symbol,
        "asset_name": asset.name,
        "period_label": dist.period_label,
        "total_amount_usdc": float(dist.total_amount_usdc),
        "total_eligible_shares": float(dist.total_eligible_shares),
        "recipients_count": len(payout_results),
        "payouts": payout_results,
        "excluded_holders": excluded_holders,
    }


@router.get("")
def list_dividend_distributions(
    real_estate_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(DividendDistribution).order_by(DividendDistribution.created_at.desc())
    if real_estate_id is not None:
        q = q.filter(DividendDistribution.real_estate_id == real_estate_id)
    dists = q.all()

    users_map = {u.id: u for u in db.query(User).all()}
    assets_map = {a.id: a for a in db.query(RealEstate).all()}

    results = []
    for d in dists:
        payouts = (
            db.query(DividendPayout)
            .filter(DividendPayout.distribution_id == d.id)
            .order_by(DividendPayout.payout_usdc.desc())
            .all()
        )
        asset = assets_map.get(d.real_estate_id)
        operator = users_map.get(d.distributed_by)
        results.append(
            {
                "id": d.id,
                "real_estate_id": d.real_estate_id,
                "asset_name": asset.name if asset else d.asset_symbol,
                "asset_symbol": d.asset_symbol,
                "token_address": d.token_address,
                "period_label": d.period_label,
                "total_amount_usdc": float(d.total_amount_usdc),
                "total_eligible_shares": float(d.total_eligible_shares),
                "recipients_count": d.recipients_count,
                "distributed_by_name": operator.display_name if operator else f"User #{d.distributed_by}",
                "notes": d.notes,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "payouts": [
                    {
                        "id": p.id,
                        "investor_address": p.investor_address,
                        "investor_name": (users_map.get(p.investor_id).display_name if users_map.get(p.investor_id) else p.investor_address),
                        "shares_held": float(p.shares_held),
                        "ownership_pct": float(p.ownership_pct),
                        "payout_usdc": float(p.payout_usdc),
                        "tx_hash": p.tx_hash,
                        "status": p.status,
                    }
                    for p in payouts
                ],
            }
        )
    return {"total_distributions": len(results), "items": results}


@router.get("/my")
def list_my_dividends(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payouts = (
        db.query(DividendPayout)
        .filter(DividendPayout.investor_id == current_user.id)
        .order_by(DividendPayout.created_at.desc())
        .all()
    )
    dists_map = {d.id: d for d in db.query(DividendDistribution).all()}
    assets_map = {a.id: a for a in db.query(RealEstate).all()}

    items = []
    total_received = 0.0
    for p in payouts:
        dist = dists_map.get(p.distribution_id)
        asset = assets_map.get(dist.real_estate_id) if dist else None
        amt = float(p.payout_usdc)
        total_received += amt
        items.append(
            {
                "id": p.id,
                "distribution_id": p.distribution_id,
                "asset_symbol": dist.asset_symbol if dist else "RWA",
                "asset_name": asset.name if asset else (dist.asset_symbol if dist else "Tài sản RWA"),
                "period_label": dist.period_label if dist else "",
                "shares_held": float(p.shares_held),
                "ownership_pct": float(p.ownership_pct),
                "payout_usdc": amt,
                "tx_hash": p.tx_hash,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )

    return {
        "total_received_usdc": round(total_received, 6),
        "payout_count": len(items),
        "items": items,
    }
