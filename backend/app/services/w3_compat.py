import time
import requests
from eth_utils import keccak, to_checksum_address, is_address
from eth_abi import encode as abi_encode, decode as abi_decode
from eth_account import Account


def _selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def _build_signature(fn_abi: dict) -> str:
    name = fn_abi["name"]
    in_types = [_canonical_type(inp) for inp in fn_abi.get("inputs", [])]
    return f"{name}({','.join(in_types)})"


def _canonical_type(param: dict) -> str:
    t = param["type"]
    if t.startswith("tuple"):
        comps = ",".join(_canonical_type(c) for c in param.get("components", []))
        suffix = t[5:]  # e.g. "[]" or ""
        return f"({comps}){suffix}"
    return t


class _BoundFunction:
    def __init__(self, w3, address: str, fn_abi: dict, args: tuple):
        self.w3 = w3
        self.address = to_checksum_address(address)
        self.fn_abi = fn_abi
        self.args = args

    def _encode_data(self) -> str:
        sig = _build_signature(self.fn_abi)
        in_types = [_canonical_type(inp) for inp in self.fn_abi.get("inputs", [])]
        encoded_args = abi_encode(in_types, list(self.args)) if in_types else b""
        return "0x" + (_selector(sig) + encoded_args).hex()

    def call(self):
        data = self._encode_data()
        raw_hex = self.w3.eth._rpc("eth_call", [{"to": self.address, "data": data}, "latest"])
        if not raw_hex or raw_hex == "0x":
            return None
        out_types = [_canonical_type(out) for out in self.fn_abi.get("outputs", [])]
        decoded = abi_decode(out_types, bytes.fromhex(raw_hex.removeprefix("0x")))
        return decoded[0] if len(decoded) == 1 else decoded

    def build_transaction(self, tx_params: dict) -> dict:
        tx = dict(tx_params)
        tx["to"] = self.address
        tx["data"] = self._encode_data()
        tx.setdefault("value", 0)
        return tx


class _ContractFunctions:
    def __init__(self, w3, address: str, abi: list):
        self._w3 = w3
        self._address = address
        self._abi = [item for item in abi if item.get("type") == "function"]

    def __getattr__(self, name: str):
        candidates = [f for f in self._abi if f.get("name") == name]
        if not candidates:
            raise AttributeError(f"Hợp đồng không có hàm {name}")

        def _caller(*args):
            chosen = candidates[0]
            for c in candidates:
                if len(c.get("inputs", [])) == len(args):
                    chosen = c
                    break
            return _BoundFunction(self._w3, self._address, chosen, args)

        return _caller


class _ContractEvents:
    def __init__(self, abi: list):
        self._abi = abi

    def __getattr__(self, name: str):
        class _Evt:
            @staticmethod
            def process_receipt(receipt):
                return []

        return _Evt


class _Contract:
    def __init__(self, w3, address: str, abi: list):
        self.address = to_checksum_address(address)
        self.abi = abi
        self.functions = _ContractFunctions(w3, self.address, abi)
        self.events = _ContractEvents(abi)


class _ReceiptObj:
    def __init__(self, data: dict):
        self.transactionHash = bytes.fromhex(data.get("transactionHash", "0x" + "0" * 64).removeprefix("0x"))
        self.blockNumber = int(data.get("blockNumber", "0x1"), 16)
        self.status = int(data.get("status", "0x1"), 16)
        self.logs = data.get("logs", [])


class _EthNamespace:
    def __init__(self, w3):
        self.w3 = w3
        self.account = Account

    def _rpc(self, method: str, params: list):
        res = requests.post(
            self.w3.provider.endpoint_uri,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=self.w3.provider.timeout,
        )
        body = res.json()
        if "error" in body and body["error"]:
            raise RuntimeError(body["error"].get("message", str(body["error"])))
        return body.get("result")

    @property
    def gas_price(self) -> int:
        val = self._rpc("eth_gasPrice", [])
        return int(val, 16) if val else 1_000_000_000

    @property
    def block_number(self) -> int:
        val = self._rpc("eth_blockNumber", [])
        return int(val, 16) if val else 0

    @property
    def chain_id(self) -> int:
        val = self._rpc("eth_chainId", [])
        return int(val, 16) if val else 31337

    def get_transaction_count(self, address: str, block: str = "latest") -> int:
        val = self._rpc("eth_getTransactionCount", [to_checksum_address(address), block])
        return int(val, 16) if val else 0

    def get_code(self, address: str) -> bytes:
        val = self._rpc("eth_getCode", [to_checksum_address(address), "latest"])
        if not val or val == "0x":
            return b""
        return bytes.fromhex(val.removeprefix("0x"))

    def send_raw_transaction(self, raw_tx: bytes) -> bytes:
        raw_hex = "0x" + raw_tx.hex().removeprefix("0x")
        tx_hash_hex = self._rpc("eth_sendRawTransaction", [raw_hex])
        return bytes.fromhex(tx_hash_hex.removeprefix("0x"))

    def wait_for_transaction_receipt(self, tx_hash: bytes, timeout: int = 30) -> _ReceiptObj:
        tx_hex = "0x" + tx_hash.hex().removeprefix("0x")
        deadline = time.time() + timeout
        while time.time() < deadline:
            rec = self._rpc("eth_getTransactionReceipt", [tx_hex])
            if rec is not None:
                return _ReceiptObj(rec)
            time.sleep(0.1)
        raise TimeoutError(f"Timeout waiting for receipt {tx_hex}")

    def contract(self, address: str, abi: list) -> _Contract:
        return _Contract(self.w3, address, abi)


class _HTTPProvider:
    def __init__(self, endpoint_uri: str, request_kwargs: dict | None = None):
        self.endpoint_uri = endpoint_uri
        self.timeout = (request_kwargs or {}).get("timeout", 5)


class _FallbackWeb3:
    HTTPProvider = _HTTPProvider

    def __init__(self, provider: _HTTPProvider):
        self.provider = provider
        self.eth = _EthNamespace(self)

    def is_connected(self) -> bool:
        try:
            chain_hex = self.eth._rpc("eth_chainId", [])
            return chain_hex is not None
        except Exception:
            return False

    @staticmethod
    def is_address(value: str) -> bool:
        try:
            return bool(is_address(value))
        except Exception:
            return False

    @staticmethod
    def to_checksum_address(value: str) -> str:
        return to_checksum_address(value)

    @staticmethod
    def keccak(primitive: bytes | None = None, text: str | None = None) -> bytes:
        if text is not None:
            return keccak(text=text)
        return keccak(primitive or b"")


try:
    from web3 import Web3  # type: ignore
except ImportError:
    Web3 = _FallbackWeb3
