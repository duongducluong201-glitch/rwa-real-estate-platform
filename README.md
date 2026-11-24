# HỆ THỐNG TOKEN HÓA BẤT ĐỘNG SẢN (RWA) VỚI CƠ CHẾ QUẢN LÝ QUYỀN SỞ HỮU VÀ GIAO DỊCH TUÂN THỦ

**Đề tài Thực tập Cơ sở — Học viện Kỹ thuật Mật mã (KMA)**
- **Khoa**: Công nghệ thông tin
- **Nhóm sinh viên thực hiện**:
  - Dương Đức Lương – CT080234
  - Nguyễn Đức Dương – CT080211
  - Vũ Nguyễn Hà – CT080216
- **Giảng viên hướng dẫn**: TS. Phạm Văn Hưởng
- **Báo cáo chi tiết**:
  - **Chương 2**: Phân tích và Thiết kế Hệ thống (14 Use Cases `UC-01..UC-14`, 6 NFRs `NFR-01..NFR-06`, ERD 8 bảng, Kiến trúc 3 tầng Session Lab & Server-side Signing)
  - **Chương 3**: [CHUONG_3_TRIEN_KHAI_VA_THUC_NGHIEM.md](file:///c:/ttcs/CHUONG_3_TRIEN_KHAI_VA_THUC_NGHIEM.md) (Triển khai hệ thống, Cài đặt mã nguồn và Kết quả thực nghiệm)

---

## 1. Kiến trúc Tổng thể Hệ thống (3-Tier Architecture — Session Lab & Server-side Signing)

Hệ thống được thiết kế và cài đặt đồng bộ 100% với đặc tả tại **Chương 2** và **Chương 3**, vận hành trên mạng cục bộ **Anvil (`http://127.0.0.1:8545`, Chain ID `31337`)** kết hợp cơ chế **Đăng nhập Phiên thực nghiệm (Session Lab)** và **Ký giao dịch phía máy chủ (Server-side Signing)** có ghi vết kiểm toán đầy đủ vào bảng `audit_signs` (không phụ thuộc tiện ích ví trình duyệt MetaMask):

```text
          [ Giao diện Web Next.js 16 (7 Màn hình Session Lab — Không cần MetaMask) ]
             │  1. Đọc trực tiếp trạng thái On-chain (ethers.js JsonRpcProvider :8545)
             │  2. Gửi yêu cầu nghiệp vụ kèm X-Session-Token (REST API :8000)
             ▼
┌──────────────────────────────────────────────────────────┐
│            Backend FastAPI (Python / SQLAlchemy)         │
│ • Session Lab Auth (5 tài khoản Seed theo vai trò RBAC)  │
│ • Server-side SignerService (Ký ECDSA + Ghi audit_signs) │
│ • Pinata IPFS / Local IPFS Cache (docCID + docHash)      │
│ • Event Indexer đồng bộ sự kiện On-chain về 8 bảng CSDL  │
└────────────┬─────────────────────────────────┬───────────┘
             │ Ký & Phát tán Raw Tx (:8545)    │ Lưu trữ Off-chain & Cache
             ▼                                 ▼
┌────────────────────────────────────┐   ┌──────────────────────────────────┐
│   Mạng EVM Cục bộ Anvil (:8545)    │   │   CSDL Quan hệ (8 Bảng ERD)      │
│ 1. IdentityRegistry (Whitelist KYC)│   │ 1. users (5 tài khoản Lab)       │
│ 2. AssetFactory (Deploy AssetToken)│   │ 2. sessions (Phiên đăng nhập)    │
│ 3. AssetToken (ERC-20 Compliance)  │   │ 3. kyc_applications (Hồ sơ KYC)  │
│ 4. PrimarySale (Chào bán sơ cấp)   │   │ 4. real_estates (Hồ sơ BĐS)      │
│ 5. Marketplace (Sàn ký quỹ Escrow) │   │ 5. audit_signs (Nhật ký ký số)   │
│ 6. MockUSDC (Stablecoin 6 decimals)│   │ 6. primary_sale_cache            │
└────────────────────────────────────┘   │ 7. listing_cache                 │
                                         │ 8. transfer_cache                │
                                         └──────────────────────────────────┘
```

---

## 2. Danh sách 5 Tài khoản Seed trong Môi trường Thực nghiệm (Anvil Lab)

| # | Vai trò (`role_label`) | Tên hiển thị | Địa chỉ Ví (Anvil Deterministic) | Quyền hạn trên Smart Contract |
| :-: | :--- | :--- | :--- | :--- |
| **#0** | `admin` | Quản trị viên Hệ thống | `0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266` | `DEFAULT_ADMIN_ROLE` (`pause`, `unpause`, `forcedTransfer`, `grantRole`) |
| **#1** | `issuer` | Đơn vị Phát hành BĐS | `0x70997970C51812dc3A010C7d01b50e0d17dc79C8` | `ISSUER_ROLE` (`createAsset`, `updateValuation`, `openSale`, `closeSale`) |
| **#2** | `compliance` | Cán bộ Tuân thủ KYC | `0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC` | `COMPLIANCE_ROLE` (`addToWhitelist`, `removeFromWhitelist`, `setFrozen`) |
| **#3** | `investor` | Nhà đầu tư A (Đã KYC) | `0x90F79bf6EB2c4f870365E785982E1f101E93b906` | Đã ghi danh sẵn trong `IdentityRegistry` (`isVerified = true`) |
| **#4** | `investor` | Nhà đầu tư B (Chưa KYC) | `0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65` | Dùng để thực nghiệm nộp KYC (`UC-02`) & kiểm thử chặn giao dịch trái phép |

---

## 3. Cấu trúc Thư mục Dự án

- [`contracts/`](file:///c:/ttcs/contracts):
  - [`src/IdentityRegistry.sol`](file:///c:/ttcs/contracts/src/IdentityRegistry.sol): Quản lý danh sách trắng KYC (`addToWhitelist`, `batchAddToWhitelist`, `removeFromWhitelist`, `isVerified`).
  - [`src/AssetToken.sol`](file:///c:/ttcs/contracts/src/AssetToken.sol): Token cổ phần BĐS chuẩn ERC-20 (`CONSTANT_ASSET_TYPE = "RealEstate"`), tích hợp kiểm soát tuân thủ tại hook `_update`, đóng băng ví (`setFrozen`), tạm dừng (`pause`/`unpause`), cưỡng chế thu hồi (`forcedTransfer`) và cập nhật định giá (`updateValuation`).
  - [`src/AssetFactory.sol`](file:///c:/ttcs/contracts/src/AssetFactory.sol): Triển khai hợp đồng `AssetToken` mới (`createAsset`) và đúc toàn bộ cổ phần vào hợp đồng `PrimarySale`.
  - [`src/PrimarySale.sol`](file:///c:/ttcs/contracts/src/PrimarySale.sol): Chào bán cổ phần BĐS sơ cấp giá cố định bằng `MockUSDC` (`openSale`, `closeSale`, `buy`).
  - [`src/Marketplace.sol`](file:///c:/ttcs/contracts/src/Marketplace.sol): Sàn giao dịch thứ cấp ký quỹ (Escrow) hỗ trợ khớp lệnh một phần (`list`, `buy`, `cancel`).
  - [`src/MockUSDC.sol`](file:///c:/ttcs/contracts/src/MockUSDC.sol): Đồng tiền thanh toán thử nghiệm (`decimals() = 6`, `faucet()`).
  - [`script/Deploy.s.sol`](file:///c:/ttcs/contracts/script/Deploy.s.sol): Kịch bản triển khai tự động toàn bộ 6 hợp đồng và BĐS mẫu `VINH01`.
  - [`test/`](file:///c:/ttcs/contracts/test): Bộ 36 bài kiểm thử đơn vị (Unit Tests) đạt **100% PASS** và **>95% Line Coverage**.
- [`backend/`](file:///c:/ttcs/backend):
  - [`app/models.py`](file:///c:/ttcs/backend/app/models.py): Định nghĩa 8 bảng CSDL theo đúng ERD Chương 2.
  - [`app/services/signer.py`](file:///c:/ttcs/backend/app/services/signer.py): Dịch vụ ký giao dịch phía máy chủ (`SignerService`) và ghi nhật ký kiểm toán `audit_signs`.
  - [`app/services/ipfs.py`](file:///c:/ttcs/backend/app/services/ipfs.py): Tải hồ sơ pháp lý lên Pinata IPFS / Local Cache và băm mật mã `Keccak-256` (`docHash`).
  - [`app/services/listener.py`](file:///c:/ttcs/backend/app/services/listener.py): Bộ lắng nghe và đồng bộ sự kiện On-chain (`Event Indexer`).
  - [`tests/test_e2e_all_ucs.py`](file:///c:/ttcs/backend/tests/test_e2e_all_ucs.py): Kịch bản kiểm thử tích hợp End-to-End tự động toàn bộ 14 Use Cases (`UC-01` .. `UC-14`).
- [`frontend/`](file:///c:/ttcs/frontend):
  - 7 màn hình giao diện Next.js tương ứng với Chương 2: `/login`, `/assets`, `/assets/[id]`, `/wallet`, `/kyc`, `/marketplace`, `/admin`.

---

## 4. Kết quả Kiểm thử & Độ bao phủ Mã nguồn (Chương 3)

### 4.1. Kiểm thử Hợp đồng Thông minh (Foundry `forge coverage --ir-minimum`)
```text
╭--------------------------+------------------+------------------+----------------+-----------------╮
| File                     | % Lines          | % Statements     | % Branches     | % Funcs         |
+===================================================================================================+
| src/AssetFactory.sol     | 95.00% (19/20)   | 94.74% (18/19)   | 75.00% (3/4)   | 100.00% (3/3)   |
| src/AssetToken.sol       | 96.00% (48/50)   | 95.65% (44/46)   | 78.57% (11/14) | 100.00% (8/8)   |
| src/IdentityRegistry.sol | 100.00% (20/20)  | 100.00% (16/16)  | 75.00% (3/4)   | 100.00% (5/5)   |
| src/Marketplace.sol      | 97.62% (41/42)   | 97.87% (46/47)   | 64.29% (9/14)  | 100.00% (5/5)   |
| src/MockUSDC.sol         | 100.00% (9/9)    | 100.00% (6/6)    | 100.00% (1/1)  | 100.00% (4/4)   |
| src/PrimarySale.sol      | 100.00% (34/34)  | 100.00% (36/36)  | 60.00% (6/10)  | 100.00% (5/5)   |
|--------------------------+------------------+------------------+----------------+-----------------|
| Total                    | 97.71% (171/175) | 97.65% (166/170) | 70.21% (33/47) | 100.00% (30/30) |
╰--------------------------+------------------+------------------+----------------+-----------------╯
```
- **36/36 bài kiểm thử đơn vị (Unit Tests) ĐẠT 100%**.
- **Độ bao phủ dòng lệnh (Line Coverage) toàn hệ thống đạt `97.71%`** (vượt xa ngưỡng yêu cầu `NFR-05 >= 80%`).

### 4.2. Kiểm thử Tích hợp End-to-End 14 Use Cases (`python backend/tests/test_e2e_all_ucs.py`)
- Kiểm thử tự động xuyên suốt từ `UC-01` đến `UC-14`: **14/14 PASS 100%**, ghi nhận đầy đủ chữ ký số trong bảng `audit_signs`.

---

## 5. Các Tính năng Nâng cao Bản Chính thức (Official v2.0)

1. **Xác thực Thanh toán 2 Bước bằng Mã OTP 6 Số qua Gmail (`2FA On-chain`)**:
   - Trước khi ký giao dịch `MockUSDC.approve` + `PrimarySale.buy` / `Marketplace.buy`, hệ thống khóa tham số giao dịch (`payload_json`), sinh mã OTP 6 số băm `SHA-256` (hiệu lực 5 phút, giới hạn tối đa 5 lần nhập sai) và gửi về Gmail qua Google Apps Script hoặc Gmail SMTP.
   - Sau khi giao dịch xác nhận trên chuỗi, hệ thống tự động gửi **Biên lai Xác nhận Thanh toán HTML** ở nền (`BackgroundTasks`) và ghi vết kiểm toán vào `email_logs`.
2. **Hồ sơ Pháp lý IPFS định dạng Microsoft Word (`.docx`)**:
   - Hỗ trợ tải lên, tự động sinh chuẩn Office Open XML (`.docx`), kiểm chứng mã băm `Keccak-256` (`docHash`) đối chiếu với Smart Contract `AssetToken`.
   - Nút **Xem tài liệu IPFS** hiển thị nội dung trang giấy A4 trực tiếp ngay trên trình duyệt; nút **Tải tài liệu (`.docx`)** tải tệp Word gốc về máy.
3. **Hàng đợi KYC Chống trùng lặp & State Machine Chặt chẽ (`UC-02 / UC-03`)**:
   - Hồ sơ CCCD 2 mặt mã hóa `AES-256-GCM` trong kho lưu trữ bảo mật (`KYC Vault`).
   - Bảng hàng đợi tự động gom đúng **01 hồ sơ mới nhất** trên mỗi nhà đầu tư kèm huy hiệu số lần nộp (`Lần nộp #N`), xem lịch sử các lần nộp trước ở chế độ chỉ đọc (`Read-only`) và khóa chặt chuyển đổi trạng thái `pending -> approved | rejected`, `approved -> revoked`.
4. **Thông báo Hệ thống Thời gian thực khi Nhận Chuyển nhượng Cổ phần**:
   - Tự động gửi thông báo chuông hệ thống (`NotificationBell`) cho người nhận ngay sau mọi giao dịch chuyển nhượng cổ phần (`P2P`, `Marketplace`, `PrimarySale`, `ForcedTransfer`).

---

## 6. Hướng dẫn Khởi chạy Hệ thống

### Cách 1: Khởi chạy Bản Chính thức tối ưu hiệu năng (`Production Mode`)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\prod_up.ps1
```

### Cách 2: Khởi chạy Chế độ Phát triển (`Development Mode`)
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_up.ps1
```

### Cách 2: Khởi chạy từng thành phần
1. **Khởi động node Anvil cục bộ (`:8545`)**:
   ```powershell
   .\tools\foundry\anvil.exe --port 8545 --chain-id 31337
   ```
2. **Triển khai 6 Smart Contracts & dữ liệu mẫu**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\deploy_local.ps1
   ```
3. **Khởi động Backend FastAPI (`:8000`)**:
   ```powershell
   python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
4. **Khởi động Giao diện Web Next.js (`:3000`)**:
   ```powershell
   cd frontend
   npm run dev
   ```
5. **Chạy bộ kiểm thử tự động**:
   ```powershell
   .\tools\foundry\forge.exe test --root contracts -vv
   python backend/tests/test_e2e_all_ucs.py
   ```
