"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useWeb3 } from "@/context/Web3Context";
import { useLanguage } from "@/context/LanguageContext";
import { NotificationBell } from "@/components/ui/NotificationBell";
import { SyncHealthBadge } from "@/components/ui/SyncHealthBadge";
import { AccountDropdown } from "@/components/ui/AccountDropdown";
import { LanguageSwitcher } from "@/components/ui/LanguageSwitcher";
import {
  LayoutDashboard,
  Building2,
  Store,
  Wallet,
  ShieldCheck,
  ListTodo,
  FileCheck,
  Settings,
  Users,
  FileSignature,
  Lock,
  ChevronUp,
  ChevronDown,
  Coins,
  UserCheck,
  AlertTriangle,
  Activity,
  Repeat,
  PanelLeftClose,
  PanelLeftOpen,
  Shield,
  BarChart3,
  History,
  ShieldAlert,
  FileText,
  LogIn,
} from "lucide-react";

const ROLE_PILL_MAP: Record<string, { label: string; defaultRoute: string }> = {
  admin: {
    label: "DEFAULT_ADMIN_ROLE",
    defaultRoute: "/admin?tab=dashboard",
  },
  issuer: {
    label: "ISSUER_ROLE",
    defaultRoute: "/admin?tab=issuer-dashboard",
  },
  compliance: {
    label: "COMPLIANCE_ROLE",
    defaultRoute: "/admin?tab=compliance-dashboard",
  },
  investor: {
    label: "INVESTOR (EOA)",
    defaultRoute: "/assets",
  },
  guest: {
    label: "GUEST (PUBLIC)",
    defaultRoute: "/assets",
  },
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTabParam = searchParams?.get("tab") || "";

  const {
    currentUser,
    isAuthenticated,
    isAuthReady,
    usdcBalance,
    claimFaucet,
    setAuthNotice,
  } = useWeb3();
  const { t } = useLanguage();

  const role = isAuthenticated && currentUser ? currentUser.role_label : "guest";
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);

  // Tự động chuyển hướng sang /login kèm thông báo nếu chưa đăng nhập mà truy cập trang cá nhân / quản trị
  useEffect(() => {
    if (!isAuthReady || isAuthenticated) return;
    const isProtectedPersonalRoute =
      pathname.startsWith("/wallet") ||
      pathname.startsWith("/kyc") ||
      pathname.startsWith("/dividends") ||
      pathname.startsWith("/admin") ||
      pathname.startsWith("/portfolio");
    if (isProtectedPersonalRoute) {
      setAuthNotice("Vui lòng đăng nhập tài khoản để truy cập chức năng này!");
      router.replace("/login");
    }
  }, [isAuthReady, isAuthenticated, pathname, router, setAuthNotice]);

  const [openMenus, setOpenMenus] = useState<Record<string, boolean>>({
    kyc: true,
    assets: true,
    admin: true,
  });

  const toggleMenu = (key: string) => {
    setOpenMenus((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Breadcrumb tự động theo đường dẫn & vai trò hiện tại
  const getBreadcrumbs = () => {
    if (pathname.startsWith("/admin")) {
      if (role === "issuer" || activeTabParam.startsWith("issuer")) {
        if (activeTabParam === "issuer-register") {
          return ["BẢNG ĐIỀU KHIỂN", "CỔNG PHÁT HÀNH", "ĐĂNG KÝ & TOKEN HÓA BĐS"];
        }
        if (activeTabParam === "issuer-sales") {
          return ["BẢNG ĐIỀU KHIỂN", "CỔNG PHÁT HÀNH", "QUẢN LÝ MỞ BÁN SƠ CẤP"];
        }
        if (activeTabParam === "issuer-docs") {
          return ["BẢNG ĐIỀU KHIỂN", "CỔNG PHÁT HÀNH", "QUẢN LÝ HỒ SƠ PHÁP LÝ IPFS"];
        }
        if (activeTabParam === "issuer-reports") {
          return ["BẢNG ĐIỀU KHIỂN", "CỔNG PHÁT HÀNH", "BÁO CÁO PHÁT HÀNH & ĐỊNH GIÁ"];
        }
        return ["BẢNG ĐIỀU KHIỂN", "CỔNG PHÁT HÀNH", "TỔNG QUAN PHÁT HÀNH"];
      }
      if (role === "compliance" || activeTabParam.startsWith("compliance")) {
        if (activeTabParam === "compliance-queue" || activeTabParam === "compliance") {
          return ["BẢNG ĐIỀU KHIỂN", "XÁC MINH KYC", "HÀNG ĐỢI XÉT DUYỆT KYC"];
        }
        if (activeTabParam === "compliance-history") {
          return ["BẢNG ĐIỀU KHIỂN", "XÁC MINH KYC", "LỊCH SỬ XÉT DUYỆT KYC"];
        }
        if (activeTabParam === "compliance-freeze") {
          return ["BẢNG ĐIỀU KHIỂN", "QUẢN LÝ TÀI KHOẢN", "ĐÓNG BĂNG / MỞ KHÓA TÀI KHOẢN"];
        }
        if (activeTabParam === "compliance-freeze-history") {
          return ["BẢNG ĐIỀU KHIỂN", "QUẢN LÝ TÀI KHOẢN", "LỊCH SỬ ĐÓNG BĂNG"];
        }
        if (activeTabParam === "compliance-audit") {
          return ["BẢNG ĐIỀU KHIỂN", "CỔNG TUÂN THỦ", "NHẬT KÝ KIỂM TOÁN TUÂN THỦ"];
        }
        return ["BẢNG ĐIỀU KHIỂN", "CỔNG TUÂN THỦ", "TỔNG QUAN TUÂN THỦ"];
      }
      if (activeTabParam === "pause") {
        return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ NỀN TẢNG", "TẠM DỪNG KHẨN CẤP"];
      }
      if (activeTabParam === "forced-transfer") {
        return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ NỀN TẢNG", "CHUYỂN NHƯỢNG CƯỠNG CHẾ"];
      }
      if (activeTabParam === "roles" || activeTabParam === "role-management") {
        return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ NỀN TẢNG", "QUẢN LÝ PHÂN QUYỀN"];
      }
      if (activeTabParam === "audit") {
        return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ NỀN TẢNG", "NHẬT KÝ KIỂM TOÁN"];
      }
      if (activeTabParam === "monitoring") {
        return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ NỀN TẢNG", "GIÁM SÁT HỆ THỐNG"];
      }
      if (activeTabParam === "settings") {
        return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ NỀN TẢNG", "CẤU HÌNH HỆ THỐNG"];
      }
      return ["BẢNG ĐIỀU KHIỂN", "QUẢN TRỊ HỆ THỐNG", "TỔNG QUAN QUẢN TRỊ"];
    }
    if (pathname.startsWith("/kyc")) {
      return ["BẢNG ĐIỀU KHIỂN", "XÁC MINH KYC CÁ NHÂN", "NỘP HỒ SƠ KYC NHÀ ĐẦU TƯ"];
    }
    if (pathname.startsWith("/marketplace")) {
      return ["BẢNG ĐIỀU KHIỂN", "SÀN THỨ CẤP MARKETPLACE", "DANH SÁCH LỆNH ESCROW"];
    }
    if (pathname.startsWith("/wallet")) {
      return ["BẢNG ĐIỀU KHIỂN", "VÍ & DANH MỤC ĐẦU TƯ", "SỞ HỮU, CỔ TỨC & CHUYỂN P2P"];
    }
    if (pathname.startsWith("/dividends")) {
      return ["BẢNG ĐIỀU KHIỂN", "PHÂN PHỐI CỔ TỨC", "PHÂN PHỐI CỔ TỨC & LỢI TỨC BĐS (mUSDC)"];
    }
    if (pathname.startsWith("/login") || pathname.startsWith("/lab-login")) {
      return ["BẢNG ĐIỀU KHIỂN", "QUẢN LÝ TÀI KHOẢN", "ĐĂNG NHẬP & CHUYỂN ĐỔI VAI TRÒ"];
    }
    if (pathname.startsWith("/assets/") && pathname !== "/assets") {
      return ["BẢNG ĐIỀU KHIỂN", "TÀI SẢN BẤT ĐỘNG SẢN", "CHI TIẾT BĐS & MỞ BÁN SƠ CẤP"];
    }
    return ["BẢNG ĐIỀU KHIỂN", "TÀI SẢN BẤT ĐỘNG SẢN", "DANH MỤC BĐS TOKEN HÓA"];
  };

  const breadcrumbs = getBreadcrumbs();
  const rolePill = ROLE_PILL_MAP[role] || ROLE_PILL_MAP.investor;

  const navItemClass = (active: boolean) =>
    `flex items-center gap-3 px-4 py-2.5 transition-colors border-l-2 ${
      active
        ? "bg-blue-600/15 text-blue-400 border-blue-500 font-medium"
        : "border-transparent text-slate-400 hover:text-slate-100 hover:bg-slate-800/60"
    }`;

  const subNavItemClass = (active: boolean) =>
    `flex items-center gap-2.5 ${
      sidebarCollapsed ? "px-4 justify-center" : "pl-9 pr-4"
    } py-2 text-[12.5px] transition-colors border-l-2 ${
      active
        ? "bg-blue-600/15 text-blue-400 border-blue-500 font-medium"
        : "border-transparent text-slate-400 hover:text-slate-100 hover:bg-slate-800/50"
    }`;

  return (
    <div className="min-h-screen flex bg-slate-50 text-slate-900 antialiased">
      {/* LEFT VERTICAL DARK SIDEBAR — CHUẨN FINTECH / WEB3 */}
      <aside
        className={`${
          sidebarCollapsed ? "w-[68px]" : "w-[260px]"
        } shrink-0 bg-slate-900 text-slate-400 flex flex-col border-r border-slate-800 select-none transition-all duration-200 sticky top-0 h-screen`}
      >
        {/* Brand Header */}
        <div className="px-3.5 py-3.5 border-b border-slate-800 flex items-center justify-between gap-2 bg-slate-950/40">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="h-8 w-8 shrink-0 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-xs shadow-xs">
              RWA
            </div>
            {!sidebarCollapsed && (
              <div className="leading-tight truncate">
                <span className="text-sm font-semibold text-white block tracking-tight truncate">
                  Cổng RWA
                </span>
                <span className="text-[11px] text-slate-400 block truncate font-mono">
                  {isAuthenticated ? `Vai trò: ${role.toUpperCase()}` : "Khách (Chưa đăng nhập)"}
                </span>
              </div>
            )}
          </div>
          <button
            onClick={() => setSidebarCollapsed((prev) => !prev)}
            title={sidebarCollapsed ? "Mở rộng Sidebar" : "Thu gọn Sidebar"}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors shrink-0"
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen className="w-4 h-4" strokeWidth={1.75} />
            ) : (
              <PanelLeftClose className="w-4 h-4" strokeWidth={1.75} />
            )}
          </button>
        </div>

        {/* Navigation Links Filtered by Role */}
        <nav className="flex-1 overflow-y-auto py-3 text-[13px] space-y-0.5">
          {role === "admin" ? (
            <>
              <Link
                href="/admin?tab=dashboard"
                title="Bảng điều khiển quản trị"
                className={navItemClass(
                  pathname.startsWith("/admin") &&
                    (activeTabParam === "dashboard" || activeTabParam === "admin" || !activeTabParam)
                )}
              >
                <LayoutDashboard className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Bảng điều khiển</span>}
              </Link>

              <Link
                href="/assets"
                title="Quản lý tài sản RWA"
                className={navItemClass(pathname === "/" || pathname.startsWith("/assets"))}
              >
                <Building2 className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Quản lý tài sản</span>}
              </Link>

              <Link
                href="/login"
                title="Quản lý người dùng & Session Lab"
                className={navItemClass(pathname.startsWith("/login"))}
              >
                <Users className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Quản lý người dùng</span>}
              </Link>

              <div className="pt-1">
                <button
                  onClick={() => toggleMenu("admin")}
                  title="Quản trị nền tảng"
                  className={`w-full flex items-center justify-between px-4 py-2.5 transition-colors border-l-2 ${
                    pathname.startsWith("/admin") &&
                    ["pause", "forced-transfer", "roles", "role-management", "audit", "monitoring"].includes(
                      activeTabParam
                    )
                      ? "bg-slate-800/60 text-slate-100 border-blue-500/60 font-medium"
                      : "border-transparent text-slate-400 hover:text-slate-100 hover:bg-slate-800/50"
                  }`}
                >
                  <span className="flex items-center gap-3">
                    <Lock className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                    {!sidebarCollapsed && <span>Quản trị nền tảng</span>}
                  </span>
                  {!sidebarCollapsed &&
                    (openMenus.admin ? (
                      <ChevronUp className="w-4 h-4 opacity-75" strokeWidth={1.75} />
                    ) : (
                      <ChevronDown className="w-4 h-4 opacity-75" strokeWidth={1.75} />
                    ))}
                </button>

                {openMenus.admin && (
                  <div className="bg-slate-950/40 py-1 space-y-0.5">
                    <Link
                      href="/admin?tab=pause"
                      title="Tạm dừng khẩn cấp"
                      className={subNavItemClass(
                        pathname.startsWith("/admin") && activeTabParam === "pause"
                      )}
                    >
                      <AlertTriangle className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="truncate">Tạm dừng khẩn cấp</span>}
                    </Link>

                    <Link
                      href="/admin?tab=forced-transfer"
                      title="Chuyển nhượng cưỡng chế"
                      className={subNavItemClass(
                        pathname.startsWith("/admin") && activeTabParam === "forced-transfer"
                      )}
                    >
                      <Repeat className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="truncate">Chuyển nhượng cưỡng chế</span>}
                    </Link>

                    <Link
                      href="/admin?tab=role-management"
                      title="Quản lý phân quyền"
                      className={subNavItemClass(
                        pathname.startsWith("/admin") &&
                          (activeTabParam === "role-management" || activeTabParam === "roles")
                      )}
                    >
                      <Shield className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="truncate">Quản lý phân quyền</span>}
                    </Link>

                    <Link
                      href="/admin?tab=audit"
                      title="Nhật ký kiểm toán"
                      className={subNavItemClass(
                        pathname.startsWith("/admin") && activeTabParam === "audit"
                      )}
                    >
                      <UserCheck className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="truncate">Nhật ký kiểm toán</span>}
                    </Link>

                    <Link
                      href="/admin?tab=monitoring"
                      title="Giám sát hệ thống"
                      className={subNavItemClass(
                        pathname.startsWith("/admin") && activeTabParam === "monitoring"
                      )}
                    >
                      <Activity className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="truncate">Giám sát hệ thống</span>}
                    </Link>

                    <Link
                      href="/dividends"
                      title="Phân phối cổ tức"
                      className={subNavItemClass(pathname.startsWith("/dividends"))}
                    >
                      <Coins className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="truncate">Phân phối cổ tức</span>}
                    </Link>
                  </div>
                )}
              </div>

              <div className="pt-1 border-t border-slate-800 mt-1">
                <Link
                  href="/admin?tab=settings"
                  title="Cấu hình hệ thống"
                  className={navItemClass(
                    pathname.startsWith("/admin") && activeTabParam === "settings"
                  )}
                >
                  <Settings className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                  {!sidebarCollapsed && <span>Cấu hình hệ thống</span>}
                </Link>
              </div>
            </>
          ) : role === "issuer" ? (
            <>
              <Link
                href="/admin?tab=issuer-dashboard"
                title="Bảng điều khiển phát hành"
                className={navItemClass(
                  pathname.startsWith("/admin") &&
                    (activeTabParam === "issuer-dashboard" || activeTabParam === "issuer" || !activeTabParam)
                )}
              >
                <LayoutDashboard className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Bảng điều khiển</span>}
              </Link>

              <Link
                href="/assets"
                title="Danh mục bất động sản"
                className={navItemClass(pathname === "/" || pathname.startsWith("/assets"))}
              >
                <Building2 className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Danh mục bất động sản</span>}
              </Link>

              <Link
                href="/admin?tab=issuer-register"
                title="Đăng ký & Token hóa"
                className={navItemClass(
                  pathname.startsWith("/admin") && activeTabParam === "issuer-register"
                )}
              >
                <FileSignature className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Đăng ký & Token hóa</span>}
              </Link>

              <Link
                href="/admin?tab=issuer-sales"
                title="Quản lý mở bán sơ cấp"
                className={navItemClass(
                  pathname.startsWith("/admin") && activeTabParam === "issuer-sales"
                )}
              >
                <Coins className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Quản lý mở bán</span>}
              </Link>

              <Link
                href="/admin?tab=issuer-docs"
                title="Quản lý Hồ sơ pháp lý IPFS"
                className={navItemClass(
                  pathname.startsWith("/admin") && activeTabParam === "issuer-docs"
                )}
              >
                <FileCheck className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Hồ sơ pháp lý</span>}
              </Link>

              <Link
                href="/admin?tab=issuer-reports"
                title="Báo cáo phát hành"
                className={navItemClass(
                  pathname.startsWith("/admin") && activeTabParam === "issuer-reports"
                )}
              >
                <Activity className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Báo cáo phát hành</span>}
              </Link>

              <Link
                href="/dividends"
                title="Phân phối cổ tức"
                className={navItemClass(pathname.startsWith("/dividends"))}
              >
                <Coins className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Phân phối cổ tức</span>}
              </Link>

              <div className="pt-2 mt-2 border-t border-slate-800">
                <Link
                  href="/login"
                  title="Chuyển đổi vai trò"
                  className={navItemClass(pathname.startsWith("/login"))}
                >
                  <Users className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                  {!sidebarCollapsed && <span>Chuyển đổi vai trò</span>}
                </Link>
              </div>
            </>
          ) : (
            <>
              <Link
                href="/assets"
                className={navItemClass(pathname === "/" || pathname === "/assets")}
              >
                <LayoutDashboard className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                {!sidebarCollapsed && <span>Danh mục BĐS</span>}
              </Link>

              {role === "investor" && (
                <>
                  <Link
                    href="/assets/1"
                    className={navItemClass(
                      pathname.startsWith("/assets/") && pathname !== "/assets"
                    )}
                  >
                    <Coins className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                    {!sidebarCollapsed && <span>Mua Sơ cấp BĐS</span>}
                  </Link>

                  <Link
                    href="/marketplace"
                    className={`justify-between gap-2 ${navItemClass(pathname.startsWith("/marketplace"))}`}
                  >
                    <span className="flex items-center gap-3 min-w-0">
                      <Store className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && (
                        <span className="whitespace-nowrap truncate">Marketplace</span>
                      )}
                    </span>
                    {!sidebarCollapsed && (
                      <span className="whitespace-nowrap shrink-0 rounded-full bg-blue-500/15 text-blue-400 ring-1 ring-inset ring-blue-500/30 text-[10px] font-medium px-2 py-0.5">
                        Escrow
                      </span>
                    )}
                  </Link>

                  <Link
                    href="/wallet"
                    className={navItemClass(pathname.startsWith("/wallet"))}
                  >
                    <Wallet className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                    {!sidebarCollapsed && <span>Ví & Chuyển P2P</span>}
                  </Link>

                  <Link
                    href="/kyc"
                    className={navItemClass(pathname.startsWith("/kyc"))}
                  >
                    <FileCheck className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                    {!sidebarCollapsed && <span>Hồ sơ KYC Cá nhân</span>}
                  </Link>
                </>
              )}

              {role === "compliance" && (
                <div className="space-y-0.5">
                  <Link
                    href="/admin?tab=compliance-dashboard"
                    className={navItemClass(
                      activeTabParam === "compliance-dashboard" || activeTabParam === ""
                    )}
                  >
                    <BarChart3 className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                    {!sidebarCollapsed && <span>Bảng điều khiển</span>}
                  </Link>

                  <div>
                    <button
                      onClick={() => toggleMenu("compliance_kyc")}
                      className={`w-full flex items-center justify-between px-4 py-2.5 transition-colors border-l-2 ${
                        activeTabParam.startsWith("compliance-queue") ||
                        activeTabParam.startsWith("compliance-history") ||
                        activeTabParam === "compliance"
                          ? "bg-slate-800/60 text-slate-100 border-blue-500/60 font-medium"
                          : "border-transparent text-slate-400 hover:text-slate-100 hover:bg-slate-800/50"
                      }`}
                    >
                      <span className="flex items-center gap-3">
                        <ShieldCheck className="w-4 h-4 shrink-0 text-blue-400" strokeWidth={1.75} />
                        {!sidebarCollapsed && <span>Xác minh KYC</span>}
                      </span>
                      {!sidebarCollapsed &&
                        (openMenus.compliance_kyc !== false ? (
                          <ChevronUp className="w-4 h-4 opacity-75" strokeWidth={1.75} />
                        ) : (
                          <ChevronDown className="w-4 h-4 opacity-75" strokeWidth={1.75} />
                        ))}
                    </button>
                    {openMenus.compliance_kyc !== false && !sidebarCollapsed && (
                      <div className="bg-slate-950/40 py-1 space-y-0.5">
                        <Link
                          href="/admin?tab=compliance-queue"
                          className={subNavItemClass(
                            activeTabParam === "compliance-queue" || activeTabParam === "compliance"
                          )}
                        >
                          <ListTodo className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                          <span className="truncate">Hàng đợi xét duyệt KYC</span>
                        </Link>
                        <Link
                          href="/admin?tab=compliance-history"
                          className={subNavItemClass(activeTabParam === "compliance-history")}
                        >
                          <History className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                          <span className="truncate">Lịch sử xét duyệt KYC</span>
                        </Link>
                      </div>
                    )}
                  </div>

                  <div>
                    <button
                      onClick={() => toggleMenu("compliance_account")}
                      className={`w-full flex items-center justify-between px-4 py-2.5 transition-colors border-l-2 ${
                        activeTabParam.startsWith("compliance-freeze")
                          ? "bg-slate-800/60 text-slate-100 border-blue-500/60 font-medium"
                          : "border-transparent text-slate-400 hover:text-slate-100 hover:bg-slate-800/50"
                      }`}
                    >
                      <span className="flex items-center gap-3">
                        <Lock className="w-4 h-4 shrink-0 text-amber-400" strokeWidth={1.75} />
                        {!sidebarCollapsed && <span>Quản lý tài khoản</span>}
                      </span>
                      {!sidebarCollapsed &&
                        (openMenus.compliance_account !== false ? (
                          <ChevronUp className="w-4 h-4 opacity-75" strokeWidth={1.75} />
                        ) : (
                          <ChevronDown className="w-4 h-4 opacity-75" strokeWidth={1.75} />
                        ))}
                    </button>
                    {openMenus.compliance_account !== false && !sidebarCollapsed && (
                      <div className="bg-slate-950/40 py-1 space-y-0.5">
                        <Link
                          href="/admin?tab=compliance-freeze"
                          className={subNavItemClass(activeTabParam === "compliance-freeze")}
                        >
                          <ShieldAlert className="w-4 h-4 shrink-0 text-rose-400" strokeWidth={1.75} />
                          <span className="truncate">Đóng băng / Mở khóa tài khoản</span>
                        </Link>
                        <Link
                          href="/admin?tab=compliance-freeze-history"
                          className={subNavItemClass(activeTabParam === "compliance-freeze-history")}
                        >
                          <History className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                          <span className="truncate">Lịch sử đóng băng</span>
                        </Link>
                      </div>
                    )}
                  </div>

                  <Link
                    href="/admin?tab=compliance-audit"
                    className={navItemClass(activeTabParam === "compliance-audit")}
                  >
                    <FileText className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                    {!sidebarCollapsed && <span>Nhật ký kiểm toán tuân thủ</span>}
                  </Link>
                </div>
              )}

              <div className="pt-2 mt-2 border-t border-slate-800">
                <Link
                  href="/login"
                  className={navItemClass(pathname.startsWith("/login"))}
                >
                  <LogIn className="w-4 h-4 shrink-0" strokeWidth={1.75} />
                  {!sidebarCollapsed && (
                    <span>{currentUser ? "Tài khoản & Đăng nhập" : "Đăng nhập / Đăng ký"}</span>
                  )}
                </Link>
              </div>
            </>
          )}
        </nav>

        {/* Sidebar Footer: Anvil RPC + SyncHealthBadge */}
        <div className="p-3 border-t border-slate-800 bg-slate-950/50 text-[11px] text-slate-400 space-y-2">
          <SyncHealthBadge compact={sidebarCollapsed} />
          <div className="flex items-center gap-2 text-emerald-400 font-medium px-1">
            <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-400 animate-pulse" />
            {!sidebarCollapsed && <span className="truncate">Anvil RPC :8545 Connected</span>}
          </div>
        </div>
      </aside>

      {/* RIGHT WORKSPACE AREA */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Clean Minimal Top Header */}
        <header className="bg-white/95 backdrop-blur border-b border-slate-200/80 px-6 py-2.5 flex flex-wrap lg:flex-nowrap items-center justify-between gap-3 sticky top-0 z-30">
          {/* Left: Breadcrumb */}
          <div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wider uppercase min-w-0 overflow-hidden">
            {breadcrumbs.map((crumb, idx) => {
              const isLast = idx === breadcrumbs.length - 1;
              return (
                <React.Fragment key={idx}>
                  <span
                    className={`whitespace-nowrap ${
                      isLast ? "text-slate-900 truncate" : "text-slate-500 hidden md:inline"
                    }`}
                  >
                    {crumb}
                  </span>
                  {!isLast && <span className="text-slate-300 font-normal hidden md:inline">/</span>}
                </React.Fragment>
              );
            })}
          </div>

          {/* Right: mUSDC + Faucet (Investor only), Language Switcher, Notification Bell, Account Dropdown */}
          <div className="flex items-center gap-2 shrink-0 ml-auto">
            {isAuthenticated && currentUser && role === "investor" && (
              <div className="inline-flex items-center gap-2 bg-slate-50 border border-slate-200/80 rounded-lg px-2.5 py-1 text-xs tabular-nums">
                <span className="text-slate-500 font-medium">mUSDC:</span>
                <span className="font-semibold text-slate-900">
                  ${Number(usdcBalance).toLocaleString("en-US")}
                </span>
                <button
                  onClick={claimFaucet}
                  title="Nhận 50,000 MockUSDC thử nghiệm"
                  className="rounded-full bg-emerald-50 hover:bg-emerald-100 text-emerald-700 ring-1 ring-inset ring-emerald-600/20 px-2 py-0.5 text-[11px] font-medium transition-colors"
                >
                  +Faucet
                </button>
              </div>
            )}

            <LanguageSwitcher />

            {isAuthenticated && currentUser && <NotificationBell />}

            {isAuthenticated && currentUser ? (
              <AccountDropdown />
            ) : (
              <Link
                href="/login"
                className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 px-3.5 py-1.5 text-xs font-medium text-white shadow-xs transition-colors"
              >
                <LogIn className="w-4 h-4" strokeWidth={1.75} />
                <span>{t("common.loginRegister")}</span>
              </Link>
            )}
          </div>
        </header>

        {/* Main Content Canvas */}
        <main className="flex-1 px-6 py-6 max-w-[1400px] w-full mx-auto">
          {children}
        </main>

        {/* Compact Footer */}
        <footer className="px-6 py-3 border-t border-slate-200/80 bg-white text-[11px] text-slate-400 text-center">
          {t("footer.disclaimerBody")}
        </footer>
      </div>
    </div>
  );
}

export function Header() {
  return null;
}

export default AppShell;
