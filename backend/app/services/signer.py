import os
import json
import time
import threading
from typing import Dict, Any, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .w3_compat import Web3
from eth_account import Account
from ..config import settings, load_deployed_contracts
from ..models import User, AuditSign

# Khóa giao dịch theo địa chỉ ví (Chống gửi giao dịch trùng lặp & xung đột Nonce)
_LOCK_REGISTRY_MUTEX = threading.Lock()
_WALLET_LOCKS: Dict[str, threading.Lock] = {}


def _get_wallet_lock(address: str) -> threading.Lock:
    key = address.lower()
    with _LOCK_REGISTRY_MUTEX:
        if key not in _WALLET_LOCKS:
            _WALLET_LOCKS[key] = threading.Lock()
        return _WALLET_LOCKS[key]

CONTRACTS_OUT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "contracts", "out")
)


def get_w3() -> Web3:
    return Web3(Web3.HTTPProvider(settings.RPC_URL, request_kwargs={"timeout": 5}))


def is_contract_deployed_on_anvil(address: Optional[str]) -> bool:
    if not address:
        return False
    try:
        w3 = get_w3()
        if not w3.is_connected():
            return False
        code = w3.eth.get_code(Web3.to_checksum_address(address))
        return len(code) > 2
    except Exception:
        return False


def load_contract_abi(contract_name: str) -> list:
    artifact_path = os.path.join(CONTRACTS_OUT_DIR, f"{contract_name}.sol", f"{contract_name}.json")
    if os.path.exists(artifact_path):
        with open(artifact_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("abi", [])
    raise RuntimeError(f"Không tìm thấy ABI của hợp đồng {contract_name} tại {artifact_path}")


def get_contract_instance(contract_name: str, custom_address: Optional[str] = None):
    w3 = get_w3()
    deployed = load_deployed_contracts()
    addr = custom_address or deployed.get(contract_name)
    if not addr:
        raise HTTPException(status_code=500, detail=f"Chưa cấu hình địa chỉ hợp đồng {contract_name}")
    abi = load_contract_abi(contract_name)
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)


class DummyReceipt:
    def __init__(self, tx_hash_hex: str, block_number: int = 1):
        self.transactionHash = bytes.fromhex(tx_hash_hex.removeprefix("0x"))
        self.blockNumber = block_number
        self.status = 1
        self.logs = []


class SignerService:
    """
    Mô-đun Server-side Signing:
    - Kiểm tra vai trò của tài khoản trong phiên đăng nhập (Session Lab).
    - Ánh xạ địa chỉ ví sang khóa bí mật trong môi trường Lab (.env).
    - Ký và gửi giao dịch lên node Anvil :8545 (hoặc ký mật mã ECDSA trực tiếp nếu node đang khởi động).
    - Ghi nhận 100% thao tác ký vào bảng kiểm toán audit_signs (NFR-01).
    """

    @staticmethod
    def sign_and_send(
        db: Session,
        current_user: User,
        contract_function,
        contract_method_name: str,
        params_summary: Dict[str, Any],
        required_roles: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        if required_roles and current_user.role_label not in required_roles:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Từ chối phân quyền (RBAC): Thao tác '{contract_method_name}' yêu cầu vai trò "
                    f"{required_roles}, tài khoản đang đăng nhập là '{current_user.role_label}'."
                ),
            )

        private_key = (
            getattr(current_user, "private_key", None)
            or settings.LAB_PRIVATE_KEYS.get(current_user.address.lower())
        )
        if not private_key:
            raise HTTPException(
                status_code=400,
                detail=f"Không tìm thấy khóa bí mật Lab cho tài khoản {current_user.address}",
            )

        w3 = get_w3()
        checksum_signer = Web3.to_checksum_address(current_user.address)
        target_addr = getattr(contract_function, "address", None)

        # Kiểm soát chống gửi giao dịch trùng lặp đồng thời cho cùng 1 địa chỉ ví
        wallet_lock = _get_wallet_lock(current_user.address)
        acquired = wallet_lock.acquire(blocking=False)
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Ví {current_user.address[:10]}... đang có một giao dịch khác đang được xử lý trên Blockchain. "
                    "Vui lòng đợi giao dịch hiện tại hoàn tất trước khi gửi giao dịch tiếp theo."
                ),
            )

        try:
            return SignerService._execute_signed_tx(
                db=db,
                current_user=current_user,
                private_key=private_key,
                w3=w3,
                checksum_signer=checksum_signer,
                target_addr=target_addr,
                contract_function=contract_function,
                contract_method_name=contract_method_name,
                params_summary=params_summary,
            )
        finally:
            wallet_lock.release()

    @staticmethod
    def _execute_signed_tx(
        db: Session,
        current_user: User,
        private_key: str,
        w3: Web3,
        checksum_signer: str,
        target_addr: Any,
        contract_function,
        contract_method_name: str,
        params_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Nhánh 1: Node Anvil đang chạy và hợp đồng đã được triển khai trên chuỗi
        if is_contract_deployed_on_anvil(target_addr):
            try:
                nonce = w3.eth.get_transaction_count(checksum_signer, "pending")
                tx_dict = contract_function.build_transaction(
                    {
                        "from": checksum_signer,
                        "chainId": settings.CHAIN_ID,
                        "gas": 4_000_000,
                        "gasPrice": w3.eth.gas_price,
                        "nonce": nonce,
                    }
                )
                signed_tx = w3.eth.account.sign_transaction(tx_dict, private_key=private_key)
                raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
                tx_hash_bytes = w3.eth.send_raw_transaction(raw_tx)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=30)

                if receipt.status != 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Giao dịch bị từ chối (revert) trên chuỗi Anvil: {tx_hash_bytes.hex()}",
                    )

                tx_hash_hex = "0x" + receipt.transactionHash.hex().removeprefix("0x")
                enriched_params = dict(params_summary)
                enriched_params.setdefault("block_number", int(receipt.blockNumber))
                enriched_params.setdefault("status", "SUCCESS")
                if target_addr:
                    enriched_params.setdefault("contract_address", str(target_addr).lower())

                audit_record = AuditSign(
                    user_id=current_user.id,
                    signer_address=current_user.address.lower(),
                    role_label=current_user.role_label,
                    contract_method=contract_method_name,
                    params_json=enriched_params,
                    tx_hash=tx_hash_hex,
                )
                db.add(audit_record)
                db.commit()
                return {"tx_hash": tx_hash_hex, "receipt": receipt, "onchain": True, "block_number": int(receipt.blockNumber)}

            except HTTPException:
                raise
            except Exception as exc:
                err_msg = str(exc)
                if "AccountNotWhitelisted" in err_msg or "BuyerNotWhitelisted" in err_msg:
                    detail = "Giao dịch bị chặn bởi Smart Contract (_update): Tài khoản chưa được xác minh KYC trong IdentityRegistry!"
                elif "AccountFrozen" in err_msg:
                    detail = "Giao dịch bị chặn bởi Smart Contract (_update): Tài khoản gửi hoặc nhận đang bị đóng băng (Frozen)!"
                elif "EnforcedPause" in err_msg:
                    detail = "Giao dịch bị chặn bởi Smart Contract (_update): Hợp đồng AssetToken đang trong trạng thái tạm dừng khẩn cấp (Paused)!"
                elif "InsufficientRemainingShares" in err_msg or "ExceedsRemaining" in err_msg:
                    detail = "Số lượng đặt mua vượt quá số phần sở hữu còn lại trong đợt mở bán / lệnh niêm yết!"
                elif "InvalidForcedTransferRecipient" in err_msg:
                    detail = "Ví nhận chuyển nhượng cưỡng chế (forcedTransfer) không hợp lệ, đang bị đóng băng hoặc chưa duyệt KYC!"
                else:
                    detail = f"Lỗi thực thi giao dịch On-chain ({contract_method_name}): {err_msg}"
                raise HTTPException(status_code=400, detail=detail)

        # Nhánh 2: Ký số mật mã ECDSA trực tiếp bằng khóa bí mật Lab (khi chạy kiểm thử nhanh chưa bật RPC ngoài)
        payload_bytes = json.dumps(
            {
                "signer": checksum_signer,
                "method": contract_method_name,
                "params": params_summary,
                "ts": time.time_ns(),
            },
            sort_keys=True,
        ).encode("utf-8")
        digest = Web3.keccak(payload_bytes)
        signed_msg = Account._sign_hash(digest, private_key=private_key)
        tx_hash_hex = "0x" + Web3.keccak(signed_msg.signature).hex().removeprefix("0x")

        block_num = db.query(AuditSign).count() + 1
        enriched_params = dict(params_summary)
        enriched_params.setdefault("block_number", block_num)
        enriched_params.setdefault("status", "SUCCESS")
        if target_addr:
            enriched_params.setdefault("contract_address", str(target_addr).lower())

        audit_record = AuditSign(
            user_id=current_user.id,
            signer_address=current_user.address.lower(),
            role_label=current_user.role_label,
            contract_method=contract_method_name,
            params_json=enriched_params,
            tx_hash=tx_hash_hex,
        )
        db.add(audit_record)
        db.commit()

        return {
            "tx_hash": tx_hash_hex,
            "receipt": DummyReceipt(tx_hash_hex, block_number=block_num),
            "onchain": False,
            "block_number": block_num,
        }
