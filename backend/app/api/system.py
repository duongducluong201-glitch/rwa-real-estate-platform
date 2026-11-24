from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import settings, load_deployed_contracts
from ..models import User, RealEstate
from ..services.auth import get_current_user
from ..services.signer import get_w3, get_contract_instance, is_contract_deployed_on_anvil
from ..services.w3_compat import Web3

router = APIRouter(prefix="/system", tags=["Giám sát Đồng bộ Chain-DB (System Sync)"])


def inspect_chain_db_sync(db: Session) -> dict:
    """Đối chiếu trạng thái thực tế giữa SQLite DB và Blockchain Anvil để phát hiện lệch dữ liệu (drift)."""
    w3 = get_w3()
    rpc_connected = False
    block_number = 0
    try:
        rpc_connected = bool(w3.is_connected())
        if rpc_connected:
            block_number = int(w3.eth.block_number)
    except Exception:
        rpc_connected = False

    deployed = load_deployed_contracts()
    core_contracts = {}
    for name in ["IdentityRegistry", "MockUSDC", "AssetFactory", "PrimarySale", "Marketplace"]:
        addr = deployed.get(name)
        core_contracts[name] = {
            "address": addr,
            "deployed": is_contract_deployed_on_anvil(addr) if rpc_connected else False,
        }

    drifts = []
    if rpc_connected and core_contracts["IdentityRegistry"]["deployed"]:
        try:
            registry = get_contract_instance("IdentityRegistry")
            for u in db.query(User).all():
                cs = Web3.to_checksum_address(u.address)
                onchain_verified = bool(registry.functions.isVerified(cs).call())
                if bool(u.is_whitelisted) != onchain_verified:
                    drifts.append(
                        {
                            "type": "whitelist_mismatch",
                            "entity": f"{u.display_name} ({u.address[:10]}...)",
                            "address": u.address,
                            "db_value": bool(u.is_whitelisted),
                            "onchain_value": onchain_verified,
                        }
                    )
        except Exception:
            pass

        # Kiểm tra các tài sản đã token hóa trong DB có bytecode trên chain không
        tokenized_assets = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
        for est in tokenized_assets:
            if not is_contract_deployed_on_anvil(est.token_address):
                drifts.append(
                    {
                        "type": "missing_onchain_token",
                        "entity": f"{est.symbol} — {est.name}",
                        "real_estate_id": est.id,
                        "token_address": est.token_address,
                        "db_value": est.status,
                        "onchain_value": "NO_BYTECODE",
                    }
                )
            else:
                try:
                    tok = get_contract_instance("AssetToken", est.token_address)
                    for u in db.query(User).filter(User.role_label == "investor").all():
                        cs = Web3.to_checksum_address(u.address)
                        onchain_frozen = bool(tok.functions.isFrozen(cs).call())
                        if bool(u.is_frozen) != onchain_frozen:
                            drifts.append(
                                {
                                    "type": "frozen_mismatch",
                                    "entity": f"{u.display_name} ({est.symbol})",
                                    "address": u.address,
                                    "db_value": bool(u.is_frozen),
                                    "onchain_value": onchain_frozen,
                                }
                            )
                except Exception:
                    pass

    all_core_ok = all(c["deployed"] for c in core_contracts.values())
    status = "SYNCED" if (rpc_connected and all_core_ok and len(drifts) == 0) else ("OFFLINE" if not rpc_connected else "DRIFT_DETECTED")

    return {
        "status": status,
        "rpc_url": settings.RPC_URL,
        "chain_id": settings.CHAIN_ID,
        "rpc_connected": rpc_connected,
        "block_number": block_number,
        "core_contracts": core_contracts,
        "drift_count": len(drifts),
        "drifts": drifts,
    }


@router.get("/sync-status")
def get_system_sync_status(db: Session = Depends(get_db)):
    return inspect_chain_db_sync(db)


@router.post("/reconcile")
def reconcile_db_with_chain(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Đồng bộ lại các cờ trạng thái DB (is_whitelisted, is_frozen) theo trạng thái chuẩn trên Blockchain Anvil."""
    if current_user.role_label not in ("admin", "compliance", "issuer"):
        raise HTTPException(
            status_code=403,
            detail="Chỉ Admin, Compliance hoặc Issuer mới được quyền chạy đồng bộ Chain-DB!",
        )

    before = inspect_chain_db_sync(db)
    if not before["rpc_connected"]:
        raise HTTPException(status_code=503, detail="Không thể kết nối tới node Blockchain Anvil (:8545)")

    fixed_count = 0
    if before["core_contracts"]["IdentityRegistry"]["deployed"]:
        registry = get_contract_instance("IdentityRegistry")
        for u in db.query(User).all():
            cs = Web3.to_checksum_address(u.address)
            try:
                onchain_verified = bool(registry.functions.isVerified(cs).call())
                if bool(u.is_whitelisted) != onchain_verified:
                    u.is_whitelisted = onchain_verified
                    fixed_count += 1
            except Exception:
                pass

    first_deployed_tok = None
    for est in db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all():
        if is_contract_deployed_on_anvil(est.token_address):
            first_deployed_tok = est.token_address
            break

    if first_deployed_tok:
        tok = get_contract_instance("AssetToken", first_deployed_tok)
        for u in db.query(User).filter(User.role_label == "investor").all():
            cs = Web3.to_checksum_address(u.address)
            try:
                onchain_frozen = bool(tok.functions.isFrozen(cs).call())
                if bool(u.is_frozen) != onchain_frozen:
                    u.is_frozen = onchain_frozen
                    fixed_count += 1
            except Exception:
                pass

    db.commit()
    after = inspect_chain_db_sync(db)
    return {
        "reconciled_records": fixed_count,
        "sync_report": after,
    }
