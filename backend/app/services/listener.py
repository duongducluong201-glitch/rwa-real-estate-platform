import logging
from typing import Optional
from sqlalchemy.orm import Session
from .w3_compat import Web3
from ..database import SessionLocal
from ..models import (
    User,
    RealEstate,
    PrimarySaleCache,
    ListingCache,
    TransferCache,
)
from .signer import get_w3, get_contract_instance

logger = logging.getLogger("rwa_indexer")
logging.basicConfig(level=logging.INFO)


def record_transfer_cache(
    db: Session,
    tx_hash: str,
    block_number: int,
    event_type: str,
    token_address: str,
    from_address: str,
    to_address: str,
    amount_shares: float,
    usdc_paid: Optional[float] = None,
):
    tx_norm = "0x" + tx_hash.removeprefix("0x")
    existing = (
        db.query(TransferCache)
        .filter(
            TransferCache.tx_hash == tx_norm,
            TransferCache.event_type == event_type,
        )
        .first()
    )
    if existing:
        return existing

    entry = TransferCache(
        tx_hash=tx_norm,
        block_number=block_number or 0,
        event_type=event_type,
        token_address=token_address.lower(),
        from_address=from_address.lower(),
        to_address=to_address.lower(),
        amount=amount_shares,
        usdc_paid=usdc_paid,
    )
    db.add(entry)
    db.commit()
    return entry


def sync_onchain_state(db: Optional[Session] = None):
    """
    Đồng bộ trạng thái từ node Anvil :8545 về các bảng cache trong PostgreSQL/SQLite:
    - Trạng thái is_whitelisted của các tài khoản từ IdentityRegistry.
    - Trạng thái đợt bán sơ cấp từ PrimarySale.
    - Trạng thái các lệnh niêm yết từ Marketplace.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        w3 = get_w3()
        if not w3.is_connected():
            return

        registry = get_contract_instance("IdentityRegistry")
        primary_sale = get_contract_instance("PrimarySale")
        marketplace = get_contract_instance("Marketplace")

        # 1. Đồng bộ trạng thái Whitelist của tất cả Users
        users = db.query(User).all()
        for u in users:
            try:
                verified = registry.functions.isVerified(Web3.to_checksum_address(u.address)).call()
                u.is_whitelisted = bool(verified)
            except Exception:
                pass

        # 2. Đồng bộ định giá & trạng thái PrimarySale của từng BĐS đã token hóa
        core_live = len(w3.eth.get_code(registry.address)) > 2
        estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
        for est in estates:
            try:
                token_checksum = Web3.to_checksum_address(est.token_address)
                if core_live and len(w3.eth.get_code(token_checksum)) <= 2:
                    est.token_address = None
                    est.status = "ready_to_tokenize"
                    continue
                token_contract = get_contract_instance("AssetToken", est.token_address)
                onchain_val = token_contract.functions.valuation().call()
                est.valuation = float(onchain_val) / 1e6

                # Đồng bộ trạng thái đóng băng cho các user trên token đầu tiên
                for u in users:
                    try:
                        frozen = token_contract.functions.isFrozen(Web3.to_checksum_address(u.address)).call()
                        u.is_frozen = bool(frozen)
                    except Exception:
                        pass

                sale_info = primary_sale.functions.getSaleInfo(token_checksum).call()
                # sale_info = (token, pricePerShare, totalAmount, remainingAmount, treasury, isOpen)
                if sale_info[2] > 0:
                    price_usdc = float(sale_info[1]) / 1e6
                    total_amt = float(sale_info[2]) / 1e18
                    rem_amt = float(sale_info[3]) / 1e18
                    is_open = bool(sale_info[5])

                    cache = (
                        db.query(PrimarySaleCache)
                        .filter(PrimarySaleCache.real_estate_id == est.id)
                        .first()
                    )
                    if not cache:
                        cache = PrimarySaleCache(
                            real_estate_id=est.id,
                            token_address=est.token_address.lower(),
                            price_per_share=price_usdc,
                            total_amount=total_amt,
                            remaining_amount=rem_amt,
                            is_open=is_open,
                        )
                        db.add(cache)
                    else:
                        cache.price_per_share = price_usdc
                        cache.total_amount = total_amt
                        cache.remaining_amount = rem_amt
                        cache.is_open = is_open

                    est.status = "open_sale" if is_open else "tokenized"
            except Exception as e:
                logger.debug(f"Sync estate {est.symbol} skipped: {e}")

        # 3. Đồng bộ danh sách lệnh trên Marketplace
        try:
            next_id = marketplace.functions.nextListingId().call()
            for lid in range(next_id):
                item = marketplace.functions.getListing(lid).call()
                # item = (listingId, token, seller, initialAmount, remainingAmount, pricePerShare, isOpen)
                token_addr = item[1].lower()
                seller_addr = item[2].lower()
                init_amt = float(item[3]) / 1e18
                rem_amt = float(item[4]) / 1e18
                price_usdc = float(item[5]) / 1e6
                is_open = bool(item[6])

                lcache = db.query(ListingCache).filter(ListingCache.listing_id == lid).first()
                if lcache:
                    lcache.remaining_amount = rem_amt
                    if not is_open and lcache.status == "open":
                        lcache.status = "filled" if rem_amt == 0 else "cancelled"
                else:
                    est = db.query(RealEstate).filter(RealEstate.token_address == token_addr).first()
                    if est:
                        lcache = ListingCache(
                            listing_id=lid,
                            real_estate_id=est.id,
                            token_address=token_addr,
                            seller_address=seller_addr,
                            initial_amount=init_amt,
                            remaining_amount=rem_amt,
                            price_per_share=price_usdc,
                            status="open" if is_open else ("filled" if rem_amt == 0 else "cancelled"),
                            tx_hash="0x" + "0" * 64,
                        )
                        db.add(lcache)
        except Exception as e:
            logger.debug(f"Sync marketplace skipped: {e}")

        db.commit()
    finally:
        if close_db:
            db.close()
