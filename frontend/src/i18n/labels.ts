/**
 * Shared UI display label formatters (Vietnamese canonical labels, translated to EN by LanguageContext).
 * Never alters underlying API enum values.
 */

const EVENT_TYPE_LABELS: Record<string, string> = {
  PRIMARY_BUY: "Mua sơ cấp",
  MARKET_BUY: "Mua thứ cấp",
  MINT: "Phát hành Token",
  TRANSFER: "Chuyển nhượng P2P",
  FORCED_TRANSFER: "Chuyển nhượng cưỡng chế",
  ESCROW_LIST: "Niêm yết Escrow",
  MARKET_LIST: "Niêm yết Escrow",
  ESCROW_CANCEL: "Hủy lệnh Escrow",
  MARKET_CANCEL: "Hủy lệnh Escrow",
  DIVIDEND: "Chi trả cổ tức",
};

const PROPERTY_KIND_LABELS: Record<string, string> = {
  apartment: "Căn hộ",
  land: "Đất nền",
  building: "Tòa nhà",
};

const KYC_STATUS_LABELS: Record<string, string> = {
  pending: "Chờ xét duyệt",
  under_review: "Đang kiểm tra",
  approved: "Đã phê duyệt",
  rejected: "Bị từ chối",
  revoked: "Đã thu hồi",
  none: "Chưa nộp",
};

const COMPLIANCE_ACTION_LABELS: Record<string, string> = {
  "Approve": "Phê duyệt",
  "Reject": "Từ chối",
  "Revoke": "Thu hồi",
  "Resubmission": "Nộp lại",
  "Approve KYC": "Phê duyệt KYC",
  "Reject KYC": "Từ chối KYC",
  "Revoke KYC": "Thu hồi KYC",
  "Freeze Account": "Đóng băng ví",
  "Unfreeze Account": "Mở khóa ví",
  "Freeze": "Đóng băng",
  "Unfreeze": "Mở khóa",
  "Access KYC Doc": "Xem tài liệu KYC",
};

export function formatEventTypeLabel(eventType?: string | null): string {
  if (!eventType) return "Giao dịch";
  const key = eventType.toUpperCase();
  return EVENT_TYPE_LABELS[key] || eventType;
}

export function formatPropertyKindLabel(kind?: string | null): string {
  if (!kind) return "Bất động sản";
  return PROPERTY_KIND_LABELS[kind.toLowerCase()] || kind;
}

export function formatKycStatusLabel(status?: string | null): string {
  if (!status) return "Chờ xét duyệt";
  return KYC_STATUS_LABELS[status.toLowerCase()] || status;
}

export function formatComplianceActionLabel(action?: string | null): string {
  if (!action) return "—";
  return COMPLIANCE_ACTION_LABELS[action] || action;
}
