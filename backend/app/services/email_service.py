import datetime
import html
import os
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

import httpx

from ..config import settings
from ..database import SessionLocal
from ..models import EmailLog


TX_TYPE_META = {
    "PRIMARY_BUY": {
        "title": "Xác Nhận Thanh Toán Mua Sơ Cấp (PrimarySale)",
        "badge": "MUA SƠ CẤP · PRIMARY SALE",
        "accent": "#206bc4",
        "action_label": "Thanh toán mua cổ phần sơ cấp thành công",
    },
    "MARKET_BUY": {
        "title": "Xác Nhận Thanh Toán Mua Thứ Cấp (Marketplace)",
        "badge": "MUA THỨ CẤP · MARKETPLACE ESCROW",
        "accent": "#2fb344",
        "action_label": "Khớp lệnh mua cổ phần thứ cấp thành công",
    },
    "MARKET_SELL": {
        "title": "Thông Báo Khớp Lệnh Bán Thành Công (Marketplace)",
        "badge": "BÁN THÀNH CÔNG · MARKETPLACE ESCROW",
        "accent": "#ae3ec9",
        "action_label": "Lệnh niêm yết của bạn vừa được khớp thành công",
    },
}


async def _dispatch_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str,
) -> tuple[str, Optional[dict]]:
    """
    Gửi email qua 1 trong 2 kênh miễn phí tùy cấu hình trong .env:
    1. Gmail SMTP (smtp.gmail.com:587 dùng App Password) nếu SMTP_USER & SMTP_APP_PASSWORD hợp lệ.
    2. Google Apps Script Web App (GOOGLE_SCRIPT_EMAIL_URL + GOOGLE_SCRIPT_SECRET) qua httpx (follow_redirects=True).
    Trả về (channel_used, response_metadata).
    """
    clean_recipient = (to_email or "").strip()
    if not clean_recipient or "@" not in clean_recipient:
        raise ValueError(f"Địa chỉ email người nhận không hợp lệ: '{clean_recipient}'")

    smtp_user = (os.getenv("SMTP_USER") or settings.SMTP_USER or "").strip()
    smtp_pass = (os.getenv("SMTP_APP_PASSWORD") or settings.SMTP_APP_PASSWORD or "").strip()
    smtp_host = (os.getenv("SMTP_HOST") or settings.SMTP_HOST or "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT") or settings.SMTP_PORT or 587)

    script_url = (os.getenv("GOOGLE_SCRIPT_EMAIL_URL") or settings.GOOGLE_SCRIPT_EMAIL_URL or "").strip()
    script_secret = (os.getenv("GOOGLE_SCRIPT_SECRET") or settings.GOOGLE_SCRIPT_SECRET or "").strip()

    has_smtp = bool(smtp_user and smtp_pass and "your_email" not in smtp_user and "xxxx" not in smtp_pass)
    has_script = bool(script_url and "YOUR_DEPLOY_ID" not in script_url and "/macros/s/" in script_url)

    # Ưu tiên Gmail SMTP nếu người dùng cấu hình App Password thật
    if has_smtp:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = str(Header(subject, "utf-8"))
        msg["From"] = formataddr((str(Header(settings.EMAIL_FROM_NAME, "utf-8")), smtp_user))
        msg["To"] = clean_recipient
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [clean_recipient], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [clean_recipient], msg.as_string())
        return "gmail_smtp", {"host": smtp_host, "port": smtp_port}

    # Kênh Google Apps Script Web App (không cần SMTP/OAuth)
    if has_script:
        payload = {
            "secret": script_secret,
            "to": clean_recipient,
            "subject": subject,
            "htmlBody": html_body,
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.post(script_url, json=payload)

        if resp.status_code == 403:
            raise RuntimeError(
                "Google Apps Script trả về HTTP 403 (Bị chặn quyền truy cập). "
                "Vui lòng vào Google Apps Script -> Deploy -> New deployment -> Web app -> "
                "Execute as: Me, Who has access: Anyone, rồi cập nhật GOOGLE_SCRIPT_EMAIL_URL (đuôi /exec) trong tệp .env!"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Google Apps Script trả về HTTP {resp.status_code}: {resp.text[:200]}")

        try:
            response_data = resp.json()
        except Exception:
            if "<!DOCTYPE html>" in resp.text or "<html" in resp.text.lower():
                raise RuntimeError(
                    "Google Apps Script trả về trang HTML thay vì JSON (có thể chưa cấp quyền Web App 'Anyone' hoặc sai URL /exec)."
                )
            response_data = {"raw_text": resp.text[:200]}

        if isinstance(response_data, dict):
            if (
                response_data.get("ok") is False
                or response_data.get("success") is False
                or response_data.get("status") == "error"
            ):
                err_detail = response_data.get("error") or response_data.get("message") or str(response_data)
                raise RuntimeError(f"Google Apps Script từ chối gửi mail: {err_detail}")

        return "google_apps_script", response_data

    raise RuntimeError(
        "Chưa cấu hình kênh gửi Gmail trong tệp .env! "
        "Hãy cấu hình SMTP_USER + SMTP_APP_PASSWORD (Gmail SMTP) HOẶC GOOGLE_SCRIPT_EMAIL_URL (Web app đuôi /exec)."
    )


def render_payment_otp_html(
    investor_name: str,
    wallet_address: str,
    otp_code: str,
    tx_type: str,
    estate_name: str,
    token_symbol: str,
    amount_shares: float,
    price_per_share: float,
    total_usdc: float,
    expires_minutes: int = 5,
    listing_id: Optional[int] = None,
) -> str:
    """Tạo email HTML chứa mã OTP 6 chữ số in đậm cỡ lớn kèm tóm tắt giao dịch thanh toán MockUSDC."""
    meta = TX_TYPE_META.get(tx_type, TX_TYPE_META["PRIMARY_BUY"])
    safe_name = html.escape(investor_name or "Nhà đầu tư")
    safe_estate = html.escape(estate_name or "Bất động sản RWA")
    safe_symbol = html.escape(token_symbol or "RWA")
    safe_wallet = html.escape(wallet_address or "")
    tx_label = (
        "Mua sơ cấp (PrimarySale)"
        if tx_type == "PRIMARY_BUY"
        else f"Mua thứ cấp (Marketplace Listing #{listing_id})"
    )

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <title>Mã OTP Xác Thực Thanh Toán MockUSDC</title>
</head>
<body style="margin:0;padding:24px;background-color:#f4f6fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#182433;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #e6e8ec;border-radius:10px;overflow:hidden;">
    <tr>
      <td style="background:{meta['accent']};padding:22px 28px;color:#ffffff;">
        <div style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;opacity:0.9;">
          XÁC THỰC THANH TOÁN 2 BƯỚC · GMAIL OTP
        </div>
        <h1 style="margin:6px 0 0;font-size:20px;font-weight:700;">
          Mã OTP Xác Nhận Thanh Toán MockUSDC
        </h1>
      </td>
    </tr>

    <tr>
      <td style="padding:26px 28px;">
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6;">
          Xin chào <strong>{safe_name}</strong>,<br/>
          Bạn vừa yêu cầu thực hiện giao dịch thanh toán bằng <strong>MockUSDC</strong> trên hệ thống <strong>{html.escape(settings.EMAIL_FROM_NAME)}</strong>. Vui lòng nhập mã OTP dưới đây để xác nhận ký giao dịch on-chain:
        </p>

        <div style="text-align:center;margin:22px 0;padding:20px;background:#f0f6ff;border:2px dashed #206bc4;border-radius:10px;">
          <div style="font-size:11px;font-weight:700;color:#6c7a91;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
            MÃ XÁC THỰC OTP CỦA BẠN (Hiệu lực {expires_minutes} phút)
          </div>
          <div style="font-size:38px;font-weight:800;letter-spacing:12px;color:#182433;font-family:'Courier New',Courier,monospace;">
            {html.escape(otp_code)}
          </div>
        </div>

        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #e6e8ec;border-radius:8px;border-collapse:separate;overflow:hidden;margin-bottom:18px;">
          <tr style="background:#f8fafd;">
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Loại giao dịch</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">{tx_label}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Bất động sản / Mã Token</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">{safe_estate} ({safe_symbol})</td>
          </tr>
          <tr style="background:#f8fafd;">
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Số lượng phần sở hữu</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">{amount_shares:,.4f} {safe_symbol}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Đơn giá</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">${price_per_share:,.2f} MockUSDC</td>
          </tr>
          <tr style="background:#eef8f0;">
            <td style="padding:12px 14px;border-bottom:1px solid #eef0f3;color:#1e7e34;font-size:14px;font-weight:700;">Tổng tiền thanh toán</td>
            <td style="padding:12px 14px;border-bottom:1px solid #eef0f3;color:#1e7e34;font-size:16px;font-weight:800;text-align:right;">${total_usdc:,.2f} MockUSDC</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;color:#6c7a91;font-size:13px;">Ví thực hiện (Anvil)</td>
            <td style="padding:10px 14px;color:#182433;font-size:12px;font-family:monospace;text-align:right;word-break:break-all;">{safe_wallet}</td>
          </tr>
        </table>

        <div style="background:#fff5f5;border:1px solid #ffc9c9;border-radius:6px;padding:12px 14px;font-size:12px;line-height:1.5;color:#a61e4d;margin-bottom:12px;">
          <strong>Cảnh báo bảo mật:</strong> Mã OTP có hiệu lực trong <strong>{expires_minutes} phút</strong> và chỉ dùng 1 lần (tối đa 5 lần nhập sai). <strong>Tuyệt đối không chia sẻ mã này với bất kỳ ai!</strong> Nếu bạn không yêu cầu giao dịch này, hãy bỏ qua email.
        </div>

        <div style="background:#fff9db;border:1px solid #ffe066;border-radius:6px;padding:10px 14px;font-size:11.5px;line-height:1.5;color:#745000;">
          Lưu ý: Đây là hệ thống mô phỏng trên mạng cục bộ Anvil (RWA Demo), không có giá trị pháp lý thay thế Giấy chứng nhận quyền sử dụng đất.
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def send_payment_otp_email(
    user_id: Optional[int],
    recipient_email: str,
    investor_name: str,
    wallet_address: str,
    otp_id: str,
    otp_code: str,
    tx_type: str,
    estate_name: str,
    token_symbol: str,
    amount_shares: float,
    price_per_share: float,
    total_usdc: float,
    expires_minutes: int = 5,
    listing_id: Optional[int] = None,
) -> dict:
    """
    Gửi mã OTP 6 chữ số về Gmail (qua Gmail SMTP hoặc Google Apps Script Web App) và ghi log vào email_logs.
    """
    clean_recipient = (recipient_email or "").strip()
    subject = f"[RWA OTP] Mã xác thực thanh toán {token_symbol} — ${total_usdc:,.2f} MockUSDC"

    html_body = render_payment_otp_html(
        investor_name=investor_name,
        wallet_address=wallet_address,
        otp_code=otp_code,
        tx_type=tx_type,
        estate_name=estate_name,
        token_symbol=token_symbol,
        amount_shares=amount_shares,
        price_per_share=price_per_share,
        total_usdc=total_usdc,
        expires_minutes=expires_minutes,
        listing_id=listing_id,
    )
    plain_body = (
        f"Mã OTP xác nhận thanh toán MockUSDC của bạn là: {otp_code}\n"
        f"Giao dịch: {tx_type} | BĐS: {estate_name} ({token_symbol})\n"
        f"Số lượng: {amount_shares:,.4f} | Tổng thanh toán: ${total_usdc:,.2f} MockUSDC\n"
        f"Hiệu lực: {expires_minutes} phút. Tuyệt đối không chia sẻ mã OTP này với bất kỳ ai!"
    )

    status = "failed"
    channel = "none"
    error_message: Optional[str] = None
    try:
        channel, _ = await _dispatch_email(clean_recipient, subject, html_body, plain_body)
        status = "sent"
    except Exception as exc:
        status = "failed"
        error_message = f"{type(exc).__name__}: {str(exc)}"
    finally:
        db = SessionLocal()
        try:
            log_row = EmailLog(
                user_id=user_id,
                recipient_email=clean_recipient or "N/A",
                tx_hash=f"OTP:{otp_id}",
                tx_type="PAYMENT_OTP",
                subject=subject,
                status=status,
                error_message=error_message,
                sent_at=datetime.datetime.utcnow(),
            )
            db.add(log_row)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    return {
        "sent": status == "sent",
        "status": status,
        "channel": channel,
        "recipient_email": clean_recipient,
        "error_message": error_message,
    }


def render_payment_confirmation_html(
    investor_name: str,
    wallet_address: str,
    tx_type: str,
    estate_name: str,
    token_symbol: str,
    token_address: str,
    amount_shares: float,
    price_per_share: float,
    total_usdc: float,
    tx_hash: str,
    block_number: int,
    confirmed_at_str: str,
    ownership_percent: Optional[float] = None,
    new_token_balance: Optional[float] = None,
    listing_id: Optional[int] = None,
) -> str:
    """Tạo nội dung HTML biên lai xác nhận giao dịch MockUSDC tương thích Gmail."""
    meta = TX_TYPE_META.get(tx_type, TX_TYPE_META["PRIMARY_BUY"])
    safe_name = html.escape(investor_name or "Nhà đầu tư")
    safe_estate = html.escape(estate_name or "Bất động sản RWA")
    safe_symbol = html.escape(token_symbol or "RWA")
    safe_wallet = html.escape(wallet_address or "")
    safe_token_addr = html.escape(token_address or "")
    safe_tx_hash = html.escape(tx_hash or "")

    ownership_row = ""
    if ownership_percent is not None and new_token_balance is not None:
        ownership_row = f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Số dư &amp; Tỷ lệ sở hữu mới</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">
            {new_token_balance:,.4f} {safe_symbol} ({ownership_percent:.4f}%)
          </td>
        </tr>
        """

    listing_row = ""
    if listing_id is not None:
        listing_row = f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Mã lệnh Marketplace</td>
          <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">
            Listing #{listing_id}
          </td>
        </tr>
        """

    total_label = "Tổng MockUSDC đã nhận" if tx_type == "MARKET_SELL" else "Tổng MockUSDC đã thanh toán"

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <title>{meta['title']}</title>
</head>
<body style="margin:0;padding:24px;background-color:#f4f6fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#182433;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #e6e8ec;border-radius:10px;overflow:hidden;">
    <tr>
      <td style="background:{meta['accent']};padding:22px 28px;color:#ffffff;">
        <div style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;opacity:0.9;">
          {meta['badge']}
        </div>
        <h1 style="margin:6px 0 0;font-size:20px;line-height:1.3;font-weight:700;">
          {meta['title']}
        </h1>
        <p style="margin:6px 0 0;font-size:13px;opacity:0.92;">
          {meta['action_label']} trên mạng EVM cục bộ Anvil (Chain ID: {settings.CHAIN_ID})
        </p>
      </td>
    </tr>

    <tr>
      <td style="padding:24px 28px;">
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6;">
          Xin chào <strong>{safe_name}</strong>,<br/>
          Hệ thống <strong>{html.escape(settings.EMAIL_FROM_NAME)}</strong> xác nhận giao dịch của bạn đã được ghi nhận thành công trên Smart Contract:
        </p>

        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #e6e8ec;border-radius:8px;border-collapse:separate;overflow:hidden;margin-bottom:18px;">
          <tr style="background:#f8fafd;">
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Nhà đầu tư</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">{safe_name}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Địa chỉ ví Anvil</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:12px;font-family:monospace;text-align:right;word-break:break-all;">{safe_wallet}</td>
          </tr>
          <tr style="background:#f8fafd;">
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Bất động sản / Mã Token</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">{safe_estate} ({safe_symbol})</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Hợp đồng AssetToken</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#206bc4;font-size:12px;font-family:monospace;text-align:right;word-break:break-all;">{safe_token_addr}</td>
          </tr>
          {listing_row}
          <tr style="background:#f8fafd;">
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Số lượng phần sở hữu</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">{amount_shares:,.4f} {safe_symbol}</td>
          </tr>
          <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Đơn giá (pricePerShare)</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#182433;font-size:13px;font-weight:700;text-align:right;">${price_per_share:,.2f} MockUSDC</td>
          </tr>
          <tr style="background:#eef8f0;">
            <td style="padding:12px 14px;border-bottom:1px solid #eef0f3;color:#1e7e34;font-size:14px;font-weight:700;">{total_label}</td>
            <td style="padding:12px 14px;border-bottom:1px solid #eef0f3;color:#1e7e34;font-size:16px;font-weight:800;text-align:right;">${total_usdc:,.2f} MockUSDC</td>
          </tr>
          {ownership_row}
          <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#6c7a91;font-size:13px;">Mã giao dịch (TxHash)</td>
            <td style="padding:10px 14px;border-bottom:1px solid #eef0f3;color:#206bc4;font-size:11.5px;font-family:monospace;text-align:right;word-break:break-all;">{safe_tx_hash}</td>
          </tr>
          <tr style="background:#f8fafd;">
            <td style="padding:10px 14px;color:#6c7a91;font-size:13px;">Số khối / Thời gian xác nhận</td>
            <td style="padding:10px 14px;color:#182433;font-size:12px;font-family:monospace;text-align:right;">Block #{block_number} · {html.escape(confirmed_at_str)}</td>
          </tr>
        </table>

        <div style="background:#fff9db;border:1px solid #ffe066;border-radius:6px;padding:12px 14px;font-size:12px;line-height:1.5;color:#745000;">
          <strong>Lưu ý miễn trừ trách nhiệm:</strong> Đây là giao dịch mô phỏng trên mạng cục bộ Anvil (RWA Demo), không có giá trị pháp lý thay thế Giấy chứng nhận quyền sử dụng đất.
        </div>
      </td>
    </tr>

    <tr>
      <td style="background:#f8fafd;border-top:1px solid #e6e8ec;padding:14px 28px;font-size:11px;color:#6c7a91;text-align:center;">
        Email tự động từ <strong>{html.escape(settings.EMAIL_FROM_NAME)}</strong> — Không cần trả lời email này.
      </td>
    </tr>
  </table>
</body>
</html>"""


async def send_payment_confirmation_email(
    user_id: Optional[int],
    recipient_email: str,
    investor_name: str,
    wallet_address: str,
    tx_type: str,
    estate_name: str,
    token_symbol: str,
    token_address: str,
    amount_shares: float,
    price_per_share: float,
    total_usdc: float,
    tx_hash: str,
    block_number: int,
    ownership_percent: Optional[float] = None,
    new_token_balance: Optional[float] = None,
    listing_id: Optional[int] = None,
) -> dict:
    """
    Gửi biên lai xác nhận thanh toán MockUSDC về Gmail (chạy nền trong BackgroundTasks).
    Luôn bắt mọi ngoại lệ để KHÔNG BAO GIỜ làm rollback giao dịch blockchain đã thành công.
    """
    clean_recipient = (recipient_email or "").strip()
    meta = TX_TYPE_META.get(tx_type, TX_TYPE_META["PRIMARY_BUY"])
    subject = f"[RWA Demo] {meta['title']} - {estate_name} ({token_symbol})"

    now_utc = datetime.datetime.utcnow()
    vn_time = now_utc + datetime.timedelta(hours=7)
    confirmed_at_str = vn_time.strftime("%d/%m/%Y %H:%M:%S (UTC+7)")

    html_body = render_payment_confirmation_html(
        investor_name=investor_name,
        wallet_address=wallet_address,
        tx_type=tx_type,
        estate_name=estate_name,
        token_symbol=token_symbol,
        token_address=token_address,
        amount_shares=amount_shares,
        price_per_share=price_per_share,
        total_usdc=total_usdc,
        tx_hash=tx_hash,
        block_number=block_number,
        confirmed_at_str=confirmed_at_str,
        ownership_percent=ownership_percent,
        new_token_balance=new_token_balance,
        listing_id=listing_id,
    )
    plain_body = (
        f"{meta['title']}\n"
        f"Nhà đầu tư: {investor_name} ({wallet_address})\n"
        f"BĐS: {estate_name} ({token_symbol} - {token_address})\n"
        f"Số lượng: {amount_shares:,.4f} | Tổng MockUSDC: ${total_usdc:,.2f}\n"
        f"TxHash: {tx_hash} | Block #{block_number} | {confirmed_at_str}"
    )

    status = "failed"
    error_message: Optional[str] = None
    channel = "none"
    try:
        channel, _ = await _dispatch_email(clean_recipient, subject, html_body, plain_body)
        status = "sent"
    except Exception as exc:
        status = "failed"
        error_message = f"{type(exc).__name__}: {str(exc)}"
    finally:
        db = SessionLocal()
        try:
            log_row = EmailLog(
                user_id=user_id,
                recipient_email=clean_recipient or "N/A",
                tx_hash=tx_hash,
                tx_type=tx_type,
                subject=subject,
                status=status,
                error_message=error_message,
                sent_at=datetime.datetime.utcnow(),
            )
            db.add(log_row)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    return {
        "status": status,
        "channel": channel,
        "recipient_email": clean_recipient,
        "tx_hash": tx_hash,
        "error_message": error_message,
    }
