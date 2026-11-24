"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useWeb3 } from "@/context/Web3Context";
import { StatusBadge, BadgeVariant } from "@/components/ui/StatusBadge";
import { CopyAddress } from "@/components/ui/CopyAddress";
import {
  LogIn,
  UserPlus,
  ShieldCheck,
  KeyRound,
  Mail,
  User,
  Lock,
  LogOut,
  CheckCircle2,
  AlertCircle,
  Wallet,
  Building2,
  Eye,
  EyeOff,
} from "lucide-react";

const ROLE_ROUTE: Record<string, string> = {
  admin: "/admin?tab=dashboard",
  issuer: "/admin?tab=issuer-dashboard",
  compliance: "/admin?tab=compliance-dashboard",
  investor: "/assets",
};

const ROLE_LABEL: Record<string, { label: string; variant: BadgeVariant }> = {
  admin: { label: "Quản trị hệ thống", variant: "purple" },
  issuer: { label: "Đơn vị phát hành", variant: "warning" },
  compliance: { label: "Cán bộ tuân thủ", variant: "info" },
  investor: { label: "Nhà đầu tư", variant: "success" },
};

const DEMO_CREDENTIAL_HINTS: Array<{
  username: string;
  role: string;
  variant: BadgeVariant;
  desc: string;
}> = [
  {
    username: "admin",
    role: "Quản trị hệ thống",
    variant: "purple",
    desc: "Phân quyền tài khoản (RBAC), Tạm dừng khẩn cấp, Chuyển nhượng cưỡng chế, Nhật ký kiểm toán",
  },
  {
    username: "issuer",
    role: "Đơn vị phát hành",
    variant: "warning",
    desc: "Đăng ký BĐS, Token hóa, Mở bán sơ cấp, Định giá, Chia cổ tức",
  },
  {
    username: "compliance",
    role: "Cán bộ tuân thủ",
    variant: "info",
    desc: "Thẩm định KYC 2 mặt (Phê duyệt/Từ chối/Thu hồi), Đóng băng ví",
  },
  {
    username: "investora",
    role: "Nhà đầu tư A (Đã KYC)",
    variant: "success",
    desc: "Mua sơ cấp, chuyển P2P, giao dịch Marketplace, nhận cổ tức",
  },
  {
    username: "investorb",
    role: "Nhà đầu tư B (Chưa KYC)",
    variant: "warning",
    desc: "Nộp hồ sơ KYC 2 mặt CCCD để kiểm thử quy trình thẩm định",
  },
];

const USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,39}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function getPasswordStrength(pw: string): { label: string; color: string; width: string } {
  if (!pw) return { label: "", color: "", width: "0%" };
  let score = 0;
  if (pw.length >= 6) score++;
  if (pw.length >= 10) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 2) return { label: "Yếu", color: "bg-rose-500", width: "33%" };
  if (score <= 3) return { label: "Trung bình", color: "bg-amber-500", width: "66%" };
  return { label: "Mạnh", color: "bg-emerald-500", width: "100%" };
}

export default function LoginPage() {
  const router = useRouter();
  const {
    currentUser,
    authNotice,
    clearAuthNotice,
    loginWithCredentials,
    registerAccount,
    changePassword,
    logoutSession,
    isConnecting,
  } = useWeb3();

  const [mode, setMode] = useState<"login" | "register">("login");
  const [showPasswordPanel, setShowPasswordPanel] = useState(false);

  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [showLoginPw, setShowLoginPw] = useState(false);

  const [regDisplayName, setRegDisplayName] = useState("");
  const [regUsername, setRegUsername] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirmPassword, setRegConfirmPassword] = useState("");
  const [showRegPw, setShowRegPw] = useState(false);

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmNewPw, setConfirmNewPw] = useState("");
  const [changingPw, setChangingPw] = useState(false);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const pwStrength = getPasswordStrength(regPassword);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);
    clearAuthNotice();

    if (!loginUsername.trim()) {
      setErrorMsg("Vui lòng nhập Tên đăng nhập hoặc Email.");
      return;
    }
    if (!loginPassword) {
      setErrorMsg("Vui lòng nhập Mật khẩu.");
      return;
    }
    try {
      const user = await loginWithCredentials(loginUsername, loginPassword);
      setSuccessMsg(`Đăng nhập thành công! Chào mừng ${user.display_name}.`);
      const target = ROLE_ROUTE[user.role_label] || "/assets";
      router.push(target);
    } catch (err: any) {
      setErrorMsg(err.message || "Đăng nhập thất bại. Vui lòng kiểm tra lại thông tin.");
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);
    clearAuthNotice();

    const cleanName = regDisplayName.trim();
    const cleanUser = regUsername.trim().toLowerCase();
    const cleanEmail = regEmail.trim().toLowerCase();

    if (cleanName.length < 2) {
      setErrorMsg("Họ và tên phải có ít nhất 2 ký tự!");
      return;
    }
    if (!USERNAME_RE.test(cleanUser)) {
      setErrorMsg(
        "Tên đăng nhập phải từ 3–40 ký tự, bắt đầu bằng chữ hoặc số, chỉ chứa chữ thường, số, dấu chấm (.), gạch dưới (_) hoặc gạch ngang (-)."
      );
      return;
    }
    if (!EMAIL_RE.test(cleanEmail)) {
      setErrorMsg("Địa chỉ Email không đúng định dạng (VD: ten@domain.com)!");
      return;
    }
    if (regPassword.trim().length < 6) {
      setErrorMsg("Mật khẩu phải có ít nhất 6 ký tự và không được toàn khoảng trắng!");
      return;
    }
    if (regPassword !== regConfirmPassword) {
      setErrorMsg("Mật khẩu xác nhận không khớp!");
      return;
    }

    try {
      const created = await registerAccount({
        display_name: cleanName,
        username: cleanUser,
        email: cleanEmail,
        password: regPassword,
      });
      setSuccessMsg(
        `Đăng ký thành công! Tài khoản @${created.username} đã được cấp ví Ethereum ${created.address.slice(0, 10)}...`
      );
      router.push("/kyc");
    } catch (err: any) {
      setErrorMsg(err.message || "Đăng ký tài khoản thất bại!");
    }
  };

  const handleChangePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);

    if (!curPw) {
      setErrorMsg("Vui lòng nhập mật khẩu hiện tại.");
      return;
    }
    if (newPw.trim().length < 6) {
      setErrorMsg("Mật khẩu mới phải có tối thiểu 6 ký tự.");
      return;
    }
    if (newPw !== confirmNewPw) {
      setErrorMsg("Xác nhận mật khẩu mới không khớp!");
      return;
    }
    if (newPw === curPw) {
      setErrorMsg("Mật khẩu mới không được trùng với mật khẩu hiện tại!");
      return;
    }

    setChangingPw(true);
    try {
      const msg = await changePassword(curPw, newPw);
      setSuccessMsg(msg);
      setCurPw("");
      setNewPw("");
      setConfirmNewPw("");
      setShowPasswordPanel(false);
    } catch (err: any) {
      setErrorMsg(err.message || "Đổi mật khẩu thất bại!");
    } finally {
      setChangingPw(false);
    }
  };

  const handleLogout = async () => {
    await logoutSession();
    setShowPasswordPanel(false);
    setSuccessMsg("Đã đăng xuất khỏi phiên làm việc hiện tại.");
    setErrorMsg(null);
  };

  const fillDemoAccount = (username: string) => {
    setMode("login");
    setLoginUsername(username);
    setLoginPassword("123456");
    setErrorMsg(null);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 py-2">
      {authNotice && (
        <div className="rounded-xl border border-amber-200/80 bg-amber-50 px-4 py-3 text-xs text-amber-800 flex items-center justify-between font-medium">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-amber-600" strokeWidth={1.75} />
            <span>{authNotice}</span>
          </div>
          <button onClick={clearAuthNotice} className="font-bold ml-4 text-amber-700 hover:text-amber-900">
            ✕
          </button>
        </div>
      )}

      {/* Active Session Banner */}
      {currentUser && (
        <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-xs space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
                <ShieldCheck className="w-5 h-5" strokeWidth={1.75} />
              </div>
              <div className="space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-sm text-slate-900">{currentUser.display_name}</span>
                  {currentUser.username && (
                    <span className="font-mono text-xs text-slate-500">@{currentUser.username}</span>
                  )}
                  <StatusBadge
                    variant={(ROLE_LABEL[currentUser.role_label] || ROLE_LABEL.investor).variant}
                    dot
                  >
                    {(ROLE_LABEL[currentUser.role_label] || ROLE_LABEL.investor).label}
                  </StatusBadge>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Wallet className="w-3.5 h-3.5 text-slate-400" strokeWidth={1.75} />
                  <span>Ví EOA:</span>
                  <CopyAddress
                    value={currentUser.address}
                    prefixLen={10}
                    suffixLen={6}
                    textClassName="text-xs text-slate-600"
                  />
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setShowPasswordPanel((v) => !v)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-xs transition-colors"
              >
                <KeyRound className="w-4 h-4 text-slate-500" strokeWidth={1.75} />
                <span>Đổi mật khẩu</span>
              </button>
              <button
                type="button"
                onClick={() => router.push(ROLE_ROUTE[currentUser.role_label] || "/assets")}
                className="px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium shadow-xs transition-colors"
              >
                Vào trang làm việc →
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-rose-200/70 bg-rose-50 text-rose-600 hover:bg-rose-100 text-xs font-medium transition-colors"
              >
                <LogOut className="w-4 h-4" strokeWidth={1.75} />
                <span>Đăng xuất</span>
              </button>
            </div>
          </div>

          {showPasswordPanel && (
            <form
              onSubmit={handleChangePasswordSubmit}
              className="pt-4 border-t border-slate-100 grid grid-cols-1 sm:grid-cols-4 gap-3 items-end text-xs"
            >
              <div>
                <label className="block font-medium text-slate-700 mb-1">Mật khẩu hiện tại (*):</label>
                <input
                  type="password"
                  required
                  value={curPw}
                  onChange={(e) => setCurPw(e.target.value)}
                  placeholder="Nhập mật khẩu cũ"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block font-medium text-slate-700 mb-1">Mật khẩu mới (*):</label>
                <input
                  type="password"
                  required
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  placeholder="Tối thiểu 6 ký tự"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block font-medium text-slate-700 mb-1">Xác nhận mật khẩu mới (*):</label>
                <input
                  type="password"
                  required
                  value={confirmNewPw}
                  onChange={(e) => setConfirmNewPw(e.target.value)}
                  placeholder="Nhập lại mật khẩu mới"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <button
                type="submit"
                disabled={changingPw}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium shadow-xs transition-colors disabled:opacity-50"
              >
                {changingPw ? "Đang lưu..." : "Lưu mật khẩu mới"}
              </button>
            </form>
          )}
        </div>
      )}

      {/* Main Auth Card */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-6 py-5 border-b border-slate-200/80 bg-slate-50/50 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-blue-600 text-white flex items-center justify-center shadow-xs">
              <Building2 className="w-5 h-5" strokeWidth={1.75} />
            </div>
            <div>
              <h1 className="text-base font-semibold text-slate-900">
                Cổng Xác Thực Tài Khoản — RWA Real Estate Platform
              </h1>
              <p className="text-[13px] text-slate-500">
                Đăng nhập bằng tài khoản cá nhân hoặc đăng ký mới (tự động khởi tạo ví Blockchain Anvil)
              </p>
            </div>
          </div>

          <div className="inline-flex rounded-lg border border-slate-200 bg-slate-100/80 p-0.5 self-start sm:self-auto">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setErrorMsg(null);
                setSuccessMsg(null);
              }}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                mode === "login"
                  ? "bg-white text-slate-900 shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <LogIn className="w-4 h-4" strokeWidth={1.75} />
              <span>Đăng nhập</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setErrorMsg(null);
                setSuccessMsg(null);
              }}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                mode === "register"
                  ? "bg-white text-slate-900 shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <UserPlus className="w-4 h-4" strokeWidth={1.75} />
              <span>Đăng ký tài khoản</span>
            </button>
          </div>
        </div>

        <div className="p-6 space-y-5">
          {errorMsg && (
            <div className="rounded-lg border border-rose-200/80 bg-rose-50 px-4 py-3 text-xs text-rose-700 flex items-center gap-2 font-medium">
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" strokeWidth={1.75} />
              <span>{errorMsg}</span>
            </div>
          )}

          {successMsg && (
            <div className="rounded-lg border border-emerald-200/80 bg-emerald-50 px-4 py-3 text-xs text-emerald-700 flex items-center gap-2 font-medium">
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" strokeWidth={1.75} />
              <span>{successMsg}</span>
            </div>
          )}

          {mode === "login" ? (
            <form onSubmit={handleLoginSubmit} className="space-y-4 max-w-lg mx-auto py-2">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1.5">
                  Tên đăng nhập hoặc Email (*):
                </label>
                <div className="relative">
                  <User
                    className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                    strokeWidth={1.75}
                  />
                  <input
                    type="text"
                    required
                    autoComplete="username"
                    value={loginUsername}
                    onChange={(e) => setLoginUsername(e.target.value)}
                    placeholder="VD: admin, issuer, compliance, investora hoặc email..."
                    className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 py-2.5 text-sm text-slate-900 placeholder-slate-400 focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1.5">
                  Mật khẩu (*):
                </label>
                <div className="relative">
                  <Lock
                    className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                    strokeWidth={1.75}
                  />
                  <input
                    type={showLoginPw ? "text" : "password"}
                    required
                    autoComplete="current-password"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    placeholder="Nhập mật khẩu..."
                    className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-10 py-2.5 text-sm text-slate-900 placeholder-slate-400 focus:border-blue-500 focus:outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setShowLoginPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                    title={showLoginPw ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                  >
                    {showLoginPw ? (
                      <EyeOff className="w-4 h-4" strokeWidth={1.75} />
                    ) : (
                      <Eye className="w-4 h-4" strokeWidth={1.75} />
                    )}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={isConnecting}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 px-4 py-2.5 text-sm font-medium text-white shadow-xs transition-colors disabled:opacity-50"
              >
                <LogIn className="w-4 h-4" strokeWidth={1.75} />
                <span>{isConnecting ? "Đang xác thực..." : "Đăng nhập Hệ thống"}</span>
              </button>

              <p className="text-center text-xs text-slate-500 pt-1">
                Chưa có tài khoản Nhà đầu tư?{" "}
                <button
                  type="button"
                  onClick={() => setMode("register")}
                  className="text-blue-600 font-medium hover:underline"
                >
                  Đăng ký tài khoản mới ngay
                </button>
              </p>
            </form>
          ) : (
            <form onSubmit={handleRegisterSubmit} className="space-y-4 max-w-lg mx-auto py-2">
              <div className="p-3.5 rounded-lg bg-emerald-50/70 border border-emerald-200/80 text-xs text-emerald-800 space-y-1">
                <p className="font-semibold">Đăng ký tài khoản Nhà đầu tư mới (Tự động cấp ví Ethereum):</p>
                <p className="text-emerald-700/90 leading-relaxed">
                  Tài khoản mới mặc định có vai trò <strong>Nhà đầu tư</strong> và được tự động cấp phát một
                  địa chỉ ví Ethereum riêng trên mạng Anvil. Sau khi đăng ký, bạn có thể nộp hồ sơ KYC 2 mặt CCCD hoặc
                  được Quản trị viên phân quyền vai trò khác.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Họ và tên (*):
                  </label>
                  <div className="relative">
                    <User
                      className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                      strokeWidth={1.75}
                    />
                    <input
                      type="text"
                      required
                      value={regDisplayName}
                      onChange={(e) => setRegDisplayName(e.target.value)}
                      placeholder="VD: Lê Minh Hoàng"
                      className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Tên đăng nhập (*):
                  </label>
                  <div className="relative">
                    <KeyRound
                      className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                      strokeWidth={1.75}
                    />
                    <input
                      type="text"
                      required
                      value={regUsername}
                      onChange={(e) => setRegUsername(e.target.value.toLowerCase())}
                      placeholder="VD: minhhoang"
                      className={`w-full rounded-lg border bg-white pl-9 pr-3 py-2 text-sm text-slate-900 focus:outline-none ${
                        regUsername && !USERNAME_RE.test(regUsername.trim())
                          ? "border-rose-400"
                          : "border-slate-200 focus:border-blue-500"
                      }`}
                    />
                  </div>
                  {regUsername && !USERNAME_RE.test(regUsername.trim()) && (
                    <p className="text-[11px] text-rose-600 mt-0.5">
                      3–40 ký tự, chỉ gồm a-z, 0-9, dấu chấm, gạch dưới/ngang.
                    </p>
                  )}
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Địa chỉ Email (*):
                </label>
                <div className="relative">
                  <Mail
                    className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                    strokeWidth={1.75}
                  />
                  <input
                    type="email"
                    required
                    value={regEmail}
                    onChange={(e) => setRegEmail(e.target.value)}
                    placeholder="VD: minhhoang@gmail.com"
                    className={`w-full rounded-lg border bg-white pl-9 pr-3 py-2 text-sm text-slate-900 focus:outline-none ${
                      regEmail && !EMAIL_RE.test(regEmail.trim())
                        ? "border-rose-400"
                        : "border-slate-200 focus:border-blue-500"
                    }`}
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Mật khẩu (*):
                  </label>
                  <div className="relative">
                    <Lock
                      className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                      strokeWidth={1.75}
                    />
                    <input
                      type={showRegPw ? "text" : "password"}
                      required
                      value={regPassword}
                      onChange={(e) => setRegPassword(e.target.value)}
                      placeholder="Tối thiểu 6 ký tự"
                      className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-9 py-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowRegPw((v) => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                    >
                      {showRegPw ? (
                        <EyeOff className="w-4 h-4" strokeWidth={1.75} />
                      ) : (
                        <Eye className="w-4 h-4" strokeWidth={1.75} />
                      )}
                    </button>
                  </div>
                  {regPassword && (
                    <div className="mt-1.5 space-y-0.5">
                      <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                        <div className={`h-full transition-all ${pwStrength.color}`} style={{ width: pwStrength.width }} />
                      </div>
                      <span className="text-[11px] text-slate-500">
                        Độ mạnh mật khẩu: <strong>{pwStrength.label}</strong>
                      </span>
                    </div>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 mb-1">
                    Xác nhận mật khẩu (*):
                  </label>
                  <div className="relative">
                    <Lock
                      className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
                      strokeWidth={1.75}
                    />
                    <input
                      type={showRegPw ? "text" : "password"}
                      required
                      value={regConfirmPassword}
                      onChange={(e) => setRegConfirmPassword(e.target.value)}
                      placeholder="Nhập lại mật khẩu"
                      className={`w-full rounded-lg border bg-white pl-9 pr-3 py-2 text-sm text-slate-900 focus:outline-none ${
                        regConfirmPassword && regConfirmPassword !== regPassword
                          ? "border-rose-400"
                          : "border-slate-200 focus:border-blue-500"
                      }`}
                    />
                  </div>
                  {regConfirmPassword && regConfirmPassword !== regPassword && (
                    <p className="text-[11px] text-rose-600 mt-0.5">Mật khẩu xác nhận chưa khớp!</p>
                  )}
                </div>
              </div>

              <button
                type="submit"
                disabled={isConnecting}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 px-4 py-2.5 text-sm font-medium text-white shadow-xs transition-colors disabled:opacity-50"
              >
                <UserPlus className="w-4 h-4" strokeWidth={1.75} />
                <span>{isConnecting ? "Đang tạo tài khoản & ví EOA..." : "Đăng ký Tài khoản mới"}</span>
              </button>

              <p className="text-center text-xs text-slate-500 pt-1">
                Đã có tài khoản?{" "}
                <button
                  type="button"
                  onClick={() => setMode("login")}
                  className="text-blue-600 font-medium hover:underline"
                >
                  Quay lại Đăng nhập
                </button>
              </p>
            </form>
          )}
        </div>
      </div>

      {/* Default Demo Credentials Table */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200/80 bg-slate-50/50 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              Danh sách Tài khoản Mặc định Hệ thống (Mật khẩu chung:{" "}
              <code className="font-mono text-rose-600 font-semibold">123456</code>)
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Dùng để kiểm thử nhanh các phân quyền Admin, Issuer, Compliance và Nhà đầu tư.
            </p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 whitespace-nowrap">Tên đăng nhập</th>
                <th className="py-3 px-4 whitespace-nowrap">Mật khẩu</th>
                <th className="py-3 px-4 whitespace-nowrap">Vai trò phân quyền</th>
                <th className="py-3 px-4 hidden md:table-cell">Phạm vi chức năng</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Điền nhanh</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm">
              {DEMO_CREDENTIAL_HINTS.map((item) => (
                <tr key={item.username} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3.5 px-4 font-mono text-xs font-semibold text-blue-600 whitespace-nowrap">
                    {item.username}
                  </td>
                  <td className="py-3.5 px-4 font-mono text-xs text-slate-500 whitespace-nowrap tabular-nums">
                    123456
                  </td>
                  <td className="py-3.5 px-4 whitespace-nowrap">
                    <StatusBadge variant={item.variant}>{item.role}</StatusBadge>
                  </td>
                  <td className="py-3.5 px-4 text-xs text-slate-500 hidden md:table-cell">
                    {item.desc}
                  </td>
                  <td className="py-3.5 px-4 text-right whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => fillDemoAccount(item.username)}
                      className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-xs transition-colors"
                    >
                      Điền vào form
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
