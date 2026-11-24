import os
import json
from pydantic import BaseModel


def _load_dotenv_file() -> None:
    """Tải tự động biến môi trường từ tệp .env (không phụ thuộc python-dotenv)."""
    candidates = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")),
    ]
    for env_path in candidates:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass


_load_dotenv_file()

CONTRACTS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "contracts_config.json")

# 5 tài khoản Lab cố định trên mạng cục bộ Anvil (Chain ID 31337)
LAB_SEED_ACCOUNTS = [
    {
        "address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        "private_key": os.getenv(
            "ADMIN_PRIVATE_KEY",
            "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
        ),
        "username": "admin",
        "email": "admin@rwa.vn",
        "role_label": "admin",
        "display_name": "Quản trị hệ thống (Admin #0)",
        "is_whitelisted": True,
    },
    {
        "address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        "private_key": os.getenv(
            "ISSUER_PRIVATE_KEY",
            "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
        ),
        "username": "issuer",
        "email": "issuer@rwa.vn",
        "role_label": "issuer",
        "display_name": "Đơn vị phát hành BĐS (Issuer #1)",
        "is_whitelisted": True,
    },
    {
        "address": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
        "private_key": os.getenv(
            "COMPLIANCE_PRIVATE_KEY",
            "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
        ),
        "username": "compliance",
        "email": "compliance@rwa.vn",
        "role_label": "compliance",
        "display_name": "Cán bộ tuân thủ KYC (Compliance #2)",
        "is_whitelisted": True,
    },
    {
        "address": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "private_key": os.getenv(
            "INVESTOR_A_PRIVATE_KEY",
            "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
        ),
        "username": "investora",
        "email": "an.nguyen@rwa.vn",
        "role_label": "investor",
        "display_name": "Nhà đầu tư A — Nguyễn Văn An (#3)",
        "is_whitelisted": True,
    },
    {
        "address": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
        "private_key": os.getenv(
            "INVESTOR_B_PRIVATE_KEY",
            "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
        ),
        "username": "investorb",
        "email": "binh.tran@rwa.vn",
        "role_label": "investor",
        "display_name": "Nhà đầu tư B — Trần Thị Bình (#4)",
        "is_whitelisted": False,
    },
]

# Các ví Anvil có sẵn 10,000 ETH (#5 -> #9) dành cấp phát tự động khi người dùng Đăng ký tài khoản mới
ANVIL_EXTRA_ACCOUNTS = [
    {
        "address": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
        "private_key": "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba",
    },
    {
        "address": "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
        "private_key": "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",
    },
    {
        "address": "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
        "private_key": "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356",
    },
    {
        "address": "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f",
        "private_key": "0xdbda1821b80551c9d65939329250298aa3472ba22feea921c0cf5d620ea67b97",
    },
    {
        "address": "0xa0Ee7A142d267C1f36714E4a8F75612F20a79720",
        "private_key": "0x2a871d0798f97d79848a013d4936a73bf4cc922c825d33c1cf7073dff6d409c6",
    },
]


def load_deployed_contracts() -> dict:
    default_contracts = {
        "IdentityRegistry": os.getenv("IDENTITY_REGISTRY_ADDRESS", "0x5FbDB2315678afecb367f032d93F642f64180aa3"),
        "MockUSDC": os.getenv("MOCK_USDC_ADDRESS", "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512"),
        "AssetFactory": os.getenv("ASSET_FACTORY_ADDRESS", "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0"),
        "PrimarySale": os.getenv("PRIMARY_SALE_ADDRESS", "0xCf7Ed3AccA5a467e9e704C703E8D87F634fB0Fc9"),
        "Marketplace": os.getenv("MARKETPLACE_ADDRESS", "0xDc64a140Aa3E981100a9becA4E685f962f0cF6C9"),
        "SampleAssetToken": os.getenv("SAMPLE_ASSET_TOKEN_ADDRESS", "0x75537828f2ce51be7289709686A69CbFDbB714F1"),
    }
    if os.path.exists(CONTRACTS_CONFIG_PATH):
        try:
            with open(CONTRACTS_CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_contracts.update(loaded)
        except Exception:
            pass
    return default_contracts


class Settings(BaseModel):
    APP_NAME: str = "Hệ thống Token hóa Bất động sản (RWA) — Lab Backend"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./rwa_platform.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "rwa-real-estate-session-secret-2026")
    KYC_VAULT_SECRET: str = os.getenv("KYC_VAULT_SECRET", "rwa-kyc-vault-aes256-gcm-secret-2026")
    SESSION_EXPIRATION_HOURS: int = 24

    # Node EVM cục bộ Anvil
    RPC_URL: str = os.getenv("RPC_URL", "http://127.0.0.1:8545")
    CHAIN_ID: int = int(os.getenv("CHAIN_ID", "31337"))

    # Pinata IPFS (nếu cấu hình sẽ gọi API Pinata, nếu trống sẽ lưu IPFSLab Cache cục bộ)
    PINATA_API_KEY: str = os.getenv("PINATA_API_KEY", "")
    PINATA_SECRET_KEY: str = os.getenv("PINATA_SECRET_KEY", "")
    PINATA_JWT: str = os.getenv("PINATA_JWT", "")

    # Gửi Email qua Google Apps Script Webhook (Không cần cấu hình SMTP hay OAuth)
    GOOGLE_SCRIPT_EMAIL_URL: str = os.getenv("GOOGLE_SCRIPT_EMAIL_URL", "")
    GOOGLE_SCRIPT_SECRET: str = os.getenv("GOOGLE_SCRIPT_SECRET", "RWA_DEMO_SECRET_2026")
    EMAIL_FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "RWA Real Estate Tokenization Lab")

    # (Tùy chọn fallback) Gmail SMTP
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_APP_PASSWORD: str = os.getenv("SMTP_APP_PASSWORD", "")

    @property
    def LAB_PRIVATE_KEYS(self) -> dict[str, str]:
        return {acc["address"].lower(): acc["private_key"] for acc in LAB_SEED_ACCOUNTS}


settings = Settings()
