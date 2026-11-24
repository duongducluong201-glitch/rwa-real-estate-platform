.PHONY: demo-up test-contracts coverage-contracts test-e2e deploy-local run-backend run-frontend

# NFR-06: Khởi động toàn bộ hệ thống thực nghiệm chỉ với 1 câu lệnh duy nhất
demo-up:
	powershell -ExecutionPolicy Bypass -File .\scripts\demo_up.ps1

# Chạy toàn bộ 36 bài kiểm thử đơn vị (Unit Tests) trên Foundry
test-contracts:
	.\tools\foundry\forge.exe test --root contracts -vv

# Đo độ bao phủ mã nguồn (Line Coverage > 95%) của 6 hợp đồng thông minh
coverage-contracts:
	.\tools\foundry\forge.exe coverage --root contracts --ir-minimum

# Kiểm thử tích hợp End-to-End (E2E) toàn bộ 14 Use Cases (UC-01 .. UC-14)
test-e2e:
	python backend/tests/test_e2e_all_ucs.py

# Triển khai 6 Smart Contracts lên mạng Anvil :8545
deploy-local:
	powershell -ExecutionPolicy Bypass -File .\scripts\deploy_local.ps1

# Chạy riêng dịch vụ Backend FastAPI (:8000)
run-backend:
	python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload

# Chạy riêng giao diện Web Next.js (:3000)
run-frontend:
	cd frontend && npm run dev
