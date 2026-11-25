"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useWeb3 } from "@/context/Web3Context";
import { StatusBadge, BadgeVariant } from "@/components/ui/StatusBadge";
import { CopyAddress } from "@/components/ui/CopyAddress";
import { AssetGridSkeleton, TableRowsSkeleton } from "@/components/ui/Skeleton";
import {
  Search,
  RefreshCw,
  Eye,
  Globe,
  Filter,
  Plus,
  Building2,
  MapPin,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  List,
  ShoppingBag,
  Settings2,
  Trash2,
  X,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";

const PROPERTY_KIND_PILLS: Record<
  string,
  { label: string; variant: BadgeVariant; thumbGradient: string }
> = {
  apartment: {
    label: "Căn hộ",
    variant: "info",
    thumbGradient: "from-slate-900 via-slate-800 to-blue-900",
  },
  land: {
    label: "Đất nền",
    variant: "purple",
    thumbGradient: "from-slate-900 via-slate-800 to-indigo-900",
  },
  building: {
    label: "Tòa nhà",
    variant: "neutral",
    thumbGradient: "from-slate-900 via-slate-800 to-emerald-900",
  },
};

export default function AssetsListPage() {
  const { apiFetch, currentUser, isAuthenticated } = useWeb3();
  const role = isAuthenticated && currentUser ? currentUser.role_label : "investor";

  const [estates, setEstates] = useState<any[]>([]);
  const [viewMode, setViewMode] = useState<"grid" | "table">("grid");
  const [userToggledView, setUserToggledView] = useState<boolean>(false);
  const [filterKind, setFilterKind] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"newest" | "oldest" | "valuation_desc">("newest");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [page, setPage] = useState<number>(1);
  const PAGE_SIZE = 6;
  const [loading, setLoading] = useState<boolean>(true);
  const [deleteTarget, setDeleteTarget] = useState<any | null>(null);
  const [deleting, setDeleting] = useState<boolean>(false);
  const [feedbackMsg, setFeedbackMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const canDeleteEstate = (est: any): boolean => {
    if (!isAuthenticated || !currentUser) return false;
    const isUntokenized =
      !est.token_address &&
      ["draft", "ready_to_tokenize"].includes(String(est.status || "ready_to_tokenize").toLowerCase());
    if (!isUntokenized) return false;
    if (currentUser.role_label === "admin") return true;
    if (currentUser.role_label === "issuer") {
      return (
        est.created_by === currentUser.id ||
        Boolean(
          est.issuer_address &&
            currentUser.address &&
            est.issuer_address.toLowerCase() === currentUser.address.toLowerCase()
        )
      );
    }
    return false;
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setFeedbackMsg(null);
    try {
      const res = await apiFetch(`/real-estates/${deleteTarget.id}`, {
        method: "DELETE",
      });
      setDeleteTarget(null);
      await loadEstates();
      setFeedbackMsg({
        type: "ok",
        text: res?.message || `Đã xóa hồ sơ bất động sản ${deleteTarget.name} (${deleteTarget.symbol}) thành công!`,
      });
    } catch (err: any) {
      setFeedbackMsg({
        type: "err",
        text: err?.message || "Không thể xóa hồ sơ bất động sản!",
      });
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  useEffect(() => {
    if (!userToggledView) {
      setViewMode(role === "investor" ? "grid" : "table");
    }
  }, [role, userToggledView]);

  const loadEstates = async () => {
    setLoading(true);
    try {
      const data = await apiFetch(`/assets?property_kind=${filterKind}`);
      setEstates(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("Failed to fetch real estates:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEstates();
  }, [filterKind, currentUser?.address]);

  const getTokenizationBadge = (est: any): { key: string; label: string; variant: BadgeVariant; dot?: boolean } => {
    if (!est.token_address) {
      return { key: "ready", label: "Chờ Token hóa", variant: "warning", dot: true };
    }
    if (est.is_paused) {
      return { key: "paused", label: "Đang tạm dừng", variant: "danger", dot: true };
    }
    return { key: "tokenized", label: "Đã Token hóa (ERC-20)", variant: "info", dot: true };
  };

  const getSaleBadge = (est: any): { key: string; label: string; variant: BadgeVariant; dot?: boolean } => {
    const sale = est.primary_sale || {};
    if (!est.token_address) {
      return { key: "not_tokenized", label: "Chưa phát hành Token", variant: "neutral" };
    }
    if (sale.is_open) {
      return { key: "sale_open", label: "Đang mở bán", variant: "success", dot: true };
    }
    if (Number(sale.total_amount || 0) > 0) {
      return { key: "sale_closed", label: "Đã đóng bán", variant: "danger", dot: true };
    }
    return { key: "sale_closed", label: "Chưa mở đợt bán", variant: "neutral" };
  };

  const filteredEstates = estates
    .filter((est) => {
      const tokBadge = getTokenizationBadge(est);
      const saleBadge = getSaleBadge(est);

      if (filterStatus !== "all") {
        if (filterStatus === "ready" && tokBadge.key !== "ready") return false;
        if (filterStatus === "tokenized" && !est.token_address) return false;
        if (filterStatus === "sale_open" && saleBadge.key !== "sale_open") return false;
        if (filterStatus === "sale_closed" && saleBadge.key !== "sale_closed") return false;
        if (filterStatus === "paused" && tokBadge.key !== "paused") return false;
      }

      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        (est.name || "").toLowerCase().includes(q) ||
        (est.symbol || "").toLowerCase().includes(q) ||
        (est.address_text || "").toLowerCase().includes(q) ||
        (est.doc_cid || "").toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      if (sortBy === "valuation_desc") {
        return Number(b.valuation || 0) - Number(a.valuation || 0);
      }
      const tA = a.created_at ? new Date(a.created_at).getTime() : a.id;
      const tB = b.created_at ? new Date(b.created_at).getTime() : b.id;
      return sortBy === "newest" ? tB - tA : tA - tB;
    });

  const totalPages = Math.max(1, Math.ceil(filteredEstates.length / PAGE_SIZE));
  const paginatedEstates = filteredEstates.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="space-y-5">
      {/* Page Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Danh mục Bất động sản Token hóa
          </h1>
          <p className="text-[13px] text-slate-500 mt-0.5">
            Tra cứu tài sản thực (RWA), kiểm chứng hồ sơ pháp lý IPFS và tham gia đợt mở bán sơ cấp On-chain.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {/* View Mode Switcher: Dạng lưới | Dạng bảng */}
          <div className="inline-flex items-center rounded-lg border border-slate-200 bg-white p-0.5 shadow-xs">
            <button
              type="button"
              onClick={() => {
                setViewMode("grid");
                setUserToggledView(true);
              }}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                viewMode === "grid"
                  ? "bg-slate-900 text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <LayoutGrid className="w-4 h-4" strokeWidth={1.75} />
              <span>Dạng lưới</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setViewMode("table");
                setUserToggledView(true);
              }}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors whitespace-nowrap ${
                viewMode === "table"
                  ? "bg-slate-900 text-white shadow-xs"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <List className="w-4 h-4" strokeWidth={1.75} />
              <span>Dạng bảng</span>
            </button>
          </div>

          {role === "issuer" && (
            <Link
              href="/admin?tab=issuer-register"
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-medium bg-blue-600 hover:bg-blue-700 text-white shadow-xs transition-colors whitespace-nowrap"
            >
              <Plus className="w-4 h-4" strokeWidth={1.75} />
              <span>Đăng ký &amp; Token hóa BĐS</span>
            </Link>
          )}
        </div>
      </div>

      {/* Feedback Banner */}
      {feedbackMsg && (
        <div
          className={`rounded-xl border px-4 py-3 text-xs font-medium flex items-center justify-between shadow-xs ${
            feedbackMsg.type === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-rose-200 bg-rose-50 text-rose-700"
          }`}
        >
          <div className="flex items-center gap-2">
            {feedbackMsg.type === "ok" ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" strokeWidth={1.75} />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" strokeWidth={1.75} />
            )}
            <span>{feedbackMsg.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setFeedbackMsg(null)}
            className="ml-4 p-1 rounded hover:bg-black/5 transition-colors"
          >
            <X className="w-4 h-4" strokeWidth={1.75} />
          </button>
        </div>
      )}

      {/* Filters & Search Toolbar Card */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative inline-flex items-center">
            <select
              aria-label="Filter Property Kind"
              value={filterKind}
              onChange={(e) => {
                setFilterKind(e.target.value);
                setPage(1);
              }}
              className="appearance-none pl-3 pr-7 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 focus:outline-none focus:border-blue-500 cursor-pointer"
            >
              <option value="all">Loại hình: Tất cả</option>
              <option value="apartment">Căn hộ</option>
              <option value="land">Đất nền</option>
              <option value="building">Tòa nhà</option>
            </select>
            <Filter
              className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 pointer-events-none"
              strokeWidth={1.75}
            />
          </div>

          <select
            aria-label="Filter Status"
            value={filterStatus}
            onChange={(e) => {
              setFilterStatus(e.target.value);
              setPage(1);
            }}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 focus:outline-none focus:border-blue-500 cursor-pointer"
          >
            <option value="all">Trạng thái: Tất cả</option>
            <option value="ready">Chờ Token hóa</option>
            <option value="tokenized">Đã phát hành Token</option>
            <option value="sale_open">Đang mở bán sơ cấp</option>
            <option value="sale_closed">Đã đóng / Chưa mở bán</option>
            <option value="paused">Đang tạm dừng</option>
          </select>

          <select
            aria-label="Sort Estates"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as any)}
            className="px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 focus:outline-none focus:border-blue-500 cursor-pointer"
          >
            <option value="newest">Sắp xếp: Mới đăng ký nhất</option>
            <option value="oldest">Sắp xếp: Đăng ký cũ nhất</option>
            <option value="valuation_desc">Sắp xếp: Định giá cao → thấp</option>
          </select>

          <div className="relative">
            <input
              type="text"
              placeholder="Tìm theo tên BĐS hoặc Symbol..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
              className="w-56 sm:w-64 pl-3 pr-8 py-1.5 border border-slate-200 rounded-lg text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-blue-500"
            />
            <Search
              className="w-4 h-4 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2"
              strokeWidth={1.75}
            />
          </div>
        </div>

        <button
          onClick={loadEstates}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 shadow-xs transition-colors whitespace-nowrap"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-blue-600" : ""}`} strokeWidth={1.75} />
          <span>Tải lại</span>
        </button>
      </div>

      {/* =====================================================================
          VIEW 1: DẠNG LƯỚI 3 CỘT (GRID VIEW — MẶC ĐỊNH CHO NHÀ ĐẦU TƯ)
         ===================================================================== */}
      {viewMode === "grid" ? (
        loading ? (
          <AssetGridSkeleton count={6} />
        ) : paginatedEstates.length === 0 ? (
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs py-14 text-center text-sm text-slate-500">
            Không tìm thấy hồ sơ bất động sản nào khớp với bộ lọc.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {paginatedEstates.map((est) => {
              const kindPill = PROPERTY_KIND_PILLS[est.property_kind] || PROPERTY_KIND_PILLS.apartment;
              const tokBadge = getTokenizationBadge(est);
              const saleBadge = getSaleBadge(est);
              const sale = est.primary_sale || {};
              const progressPct = Math.min(100, Number(sale.progress_percent || 0));

              return (
                <div
                  key={est.id}
                  className="bg-white rounded-xl border border-slate-200/80 shadow-xs hover:shadow-md transition-all duration-200 overflow-hidden flex flex-col group"
                >
                  {/* Cover Image / Gradient Fallback (aspect-video) */}
                  <Link
                    href={`/assets/${est.id}`}
                    className={`relative aspect-video w-full bg-gradient-to-br ${kindPill.thumbGradient} flex flex-col items-center justify-center overflow-hidden`}
                  >
                    {est.cover_image_url ? (
                      <img
                        src={est.cover_image_url}
                        alt={est.name}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                    ) : (
                      <div className="flex flex-col items-center justify-center text-white/90 select-none">
                        <div className="w-11 h-11 rounded-xl bg-white/10 backdrop-blur-xs border border-white/15 flex items-center justify-center mb-2">
                          <Building2 className="w-5 h-5 text-white" strokeWidth={1.75} />
                        </div>
                        <span className="font-mono text-xs font-semibold tracking-wider text-white/85">
                          {est.symbol}
                        </span>
                      </div>
                    )}

                    {/* Top-left Kind Pill & Top-right Sale Status Badge */}
                    <div className="absolute top-3 left-3 flex items-center gap-1.5">
                      <StatusBadge variant={kindPill.variant} className="bg-white/95 backdrop-blur-xs shadow-xs">
                        {kindPill.label}
                      </StatusBadge>
                    </div>
                    <div className="absolute top-3 right-3">
                      <StatusBadge
                        variant={est.token_address ? saleBadge.variant : tokBadge.variant}
                        dot
                        className="bg-white/95 backdrop-blur-xs shadow-xs"
                      >
                        {est.token_address ? saleBadge.label : tokBadge.label}
                      </StatusBadge>
                    </div>
                  </Link>

                  {/* Card Body */}
                  <div className="p-5 flex-1 flex flex-col justify-between space-y-4">
                    <div className="space-y-3">
                      <div>
                        <div className="flex items-start justify-between gap-2">
                          <Link
                            href={`/assets/${est.id}`}
                            className="text-base font-semibold text-slate-900 hover:text-blue-600 transition-colors line-clamp-1"
                          >
                            {est.name}
                          </Link>
                          <span className="shrink-0 whitespace-nowrap rounded-md bg-slate-100 px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-700">
                            {est.symbol}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 text-xs text-slate-500 mt-1">
                          <MapPin className="w-3.5 h-3.5 shrink-0 text-slate-400" strokeWidth={1.75} />
                          <span className="truncate">
                            {est.address_text} · {Number(est.area_m2).toLocaleString("en-US")} m²
                          </span>
                        </div>
                      </div>

                      {/* Financial Metrics Box */}
                      <div className="grid grid-cols-2 gap-2.5 p-3 rounded-lg bg-slate-50/90 border border-slate-100 tabular-nums">
                        <div>
                          <span className="block text-[11px] text-slate-500">Giá nội tại / CP</span>
                          <strong className="text-sm font-semibold text-slate-900">
                            ${Number(sale.price_per_share || est.intrinsic_price_per_share || 0).toLocaleString("en-US")}{" "}
                            <span className="text-[11px] font-normal text-slate-500">mUSDC</span>
                          </strong>
                        </div>
                        <div>
                          <span className="block text-[11px] text-slate-500">Tổng định giá</span>
                          <strong className="text-sm font-semibold text-slate-900">
                            ${Number(est.valuation).toLocaleString("en-US")}
                          </strong>
                        </div>
                      </div>

                      {/* Progress Bar */}
                      <div className="space-y-1.5 tabular-nums">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-slate-500">
                            Đã phân phối:{" "}
                            <strong className="font-medium text-slate-700">
                              {Number(sale.sold_amount || 0).toLocaleString("en-US")} /{" "}
                              {Number(sale.total_amount || est.total_shares || 0).toLocaleString("en-US")}
                            </strong>{" "}
                            CP
                          </span>
                          <span className="font-semibold text-slate-900">{progressPct}%</span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-emerald-500 rounded-full transition-all duration-300"
                            style={{ width: `${progressPct}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Card Footer CTA */}
                    <div className="pt-3 border-t border-slate-100 flex items-center gap-2">
                      {role === "investor" && sale.is_open ? (
                        <>
                          <Link
                            href={`/assets/${est.id}`}
                            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium shadow-xs transition-colors whitespace-nowrap"
                          >
                            <ShoppingBag className="w-4 h-4" strokeWidth={1.75} />
                            <span>Mua cổ phần</span>
                          </Link>
                          <Link
                            href={`/assets/${est.id}`}
                            title="Xem chi tiết & kiểm chứng IPFS"
                            className="inline-flex items-center justify-center w-8 h-8 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 transition-colors shrink-0"
                          >
                            <Eye className="w-4 h-4" strokeWidth={1.75} />
                          </Link>
                        </>
                      ) : role === "issuer" ? (
                        <>
                          <Link
                            href={`/assets/${est.id}`}
                            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-xs transition-colors whitespace-nowrap"
                          >
                            <Settings2 className="w-4 h-4 text-blue-600" strokeWidth={1.75} />
                            <span>Quản lý &amp; Mở bán</span>
                          </Link>
                          {canDeleteEstate(est) && (
                            <button
                              type="button"
                              onClick={() => setDeleteTarget(est)}
                              className="inline-flex items-center justify-center gap-1 px-3 py-2 rounded-lg bg-rose-50 text-rose-600 border border-rose-200/70 hover:bg-rose-100 text-xs font-medium transition-colors whitespace-nowrap shrink-0"
                            >
                              <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                              <span>Xóa hồ sơ</span>
                            </button>
                          )}
                        </>
                      ) : (
                        <>
                          <Link
                            href={`/assets/${est.id}`}
                            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-xs transition-colors whitespace-nowrap"
                          >
                            <Eye className="w-4 h-4 text-slate-500" strokeWidth={1.75} />
                            <span>Xem chi tiết BĐS</span>
                          </Link>
                          {canDeleteEstate(est) && (
                            <button
                              type="button"
                              onClick={() => setDeleteTarget(est)}
                              className="inline-flex items-center justify-center gap-1 px-3 py-2 rounded-lg bg-rose-50 text-rose-600 border border-rose-200/70 hover:bg-rose-100 text-xs font-medium transition-colors whitespace-nowrap shrink-0"
                            >
                              <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                              <span>Xóa hồ sơ</span>
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )
      ) : (
        /* =====================================================================
           VIEW 2: DẠNG BẢNG TỐI ƯU KHÔNG CUỘN NGANG (TABLE VIEW)
           ===================================================================== */
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <th className="py-3 px-3.5 whitespace-nowrap">Bất động sản</th>
                  <th className="py-3 px-2.5 whitespace-nowrap">Định giá</th>
                  <th className="py-3 px-2.5 whitespace-nowrap">Cổ phần</th>
                  <th className="py-3 px-2.5 whitespace-nowrap">Token hóa</th>
                  <th className="py-3 px-2.5 whitespace-nowrap">Mở bán</th>
                  <th className="py-3 px-3.5 text-right whitespace-nowrap">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm text-slate-900">
                {loading ? (
                  <TableRowsSkeleton rows={6} cols={6} />
                ) : paginatedEstates.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-xs text-slate-500">
                      Không tìm thấy hồ sơ bất động sản nào khớp với bộ lọc.
                    </td>
                  </tr>
                ) : (
                  paginatedEstates.map((est) => {
                    const kindPill =
                      PROPERTY_KIND_PILLS[est.property_kind] || PROPERTY_KIND_PILLS.apartment;
                    const tokBadge = getTokenizationBadge(est);
                    const saleBadge = getSaleBadge(est);
                    const sale = est.primary_sale || {};

                    return (
                      <tr key={est.id} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-3.5 px-3.5">
                          <div className="flex items-center gap-2.5">
                            <div
                              className={`w-9 h-9 rounded-lg bg-gradient-to-br ${kindPill.thumbGradient} text-white flex flex-col items-center justify-center shrink-0 shadow-xs`}
                            >
                              <Building2 className="w-3.5 h-3.5 opacity-90" strokeWidth={1.75} />
                            </div>
                            <div className="min-w-0 max-w-[185px]">
                              <div className="flex items-center gap-1.5">
                                <Link
                                  href={`/assets/${est.id}`}
                                  className="text-sm font-medium text-slate-900 hover:text-blue-600 truncate"
                                  title={est.name}
                                >
                                  {est.name}
                                </Link>
                                <span className="shrink-0 whitespace-nowrap px-1.5 py-0.5 rounded bg-slate-100 text-slate-700 font-mono text-[10px] font-semibold">
                                  {est.symbol}
                                </span>
                              </div>
                              <div className="text-xs text-slate-500 flex items-center gap-1.5 mt-0.5 truncate tabular-nums">
                                <StatusBadge variant={kindPill.variant} className="!px-2 !py-0 !text-[10px]">
                                  {kindPill.label}
                                </StatusBadge>
                                <span className="truncate">
                                  {Number(est.area_m2).toLocaleString("en-US")} m²
                                </span>
                              </div>
                            </div>
                          </div>
                        </td>

                        <td className="py-3.5 px-2.5 whitespace-nowrap tabular-nums">
                          <div className="text-sm font-medium text-slate-900">
                            ${Number(est.valuation).toLocaleString("en-US")}
                          </div>
                          <div className="text-xs text-slate-500">
                            ${Number(est.intrinsic_price_per_share).toLocaleString("en-US")}/CP
                          </div>
                        </td>

                        <td className="py-3.5 px-2.5 whitespace-nowrap tabular-nums">
                          <div className="text-sm font-medium text-slate-900">
                            {Number(est.total_shares).toLocaleString("en-US")} {est.symbol}
                          </div>
                          <div className="text-xs text-slate-500">
                            Đã bán: <strong className="font-medium text-slate-700">{Number(sale.sold_amount || 0).toLocaleString("en-US")}</strong>
                          </div>
                        </td>

                        <td className="py-3.5 px-2.5 whitespace-nowrap">
                          <StatusBadge variant={tokBadge.variant} dot={tokBadge.dot}>
                            {tokBadge.label}
                          </StatusBadge>
                          {est.token_address && (
                            <div className="mt-1">
                              <CopyAddress value={est.token_address} prefixLen={4} suffixLen={3} />
                            </div>
                          )}
                        </td>

                        <td className="py-3.5 px-2.5 whitespace-nowrap tabular-nums">
                          <StatusBadge variant={saleBadge.variant} dot={saleBadge.dot}>
                            {saleBadge.label}
                          </StatusBadge>
                          {Number(sale.total_amount || 0) > 0 && (
                            <div className="mt-1.5 w-20">
                              <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-emerald-500 rounded-full"
                                  style={{ width: `${Math.min(100, sale.progress_percent || 0)}%` }}
                                />
                              </div>
                            </div>
                          )}
                        </td>

                        <td className="py-3.5 px-3.5 text-right whitespace-nowrap">
                          <div className="inline-flex items-center justify-end gap-1.5">
                            <Link
                              href={`/assets/${est.id}`}
                              title="Xem chi tiết BĐS & Kiểm chứng IPFS"
                              className="w-8 h-8 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 inline-flex items-center justify-center shadow-xs transition-colors"
                            >
                              <Eye className="w-4 h-4" strokeWidth={1.75} />
                            </Link>

                            {role === "investor" && sale.is_open && (
                              <Link
                                href={`/assets/${est.id}`}
                                className="px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium shadow-xs transition-colors whitespace-nowrap"
                              >
                                Mua
                              </Link>
                            )}

                            {role === "issuer" && (
                              <Link
                                href={`/assets/${est.id}`}
                                className="px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-medium shadow-xs transition-colors whitespace-nowrap"
                              >
                                Quản lý
                              </Link>
                            )}

                            {canDeleteEstate(est) && (
                              <button
                                type="button"
                                onClick={() => setDeleteTarget(est)}
                                title="Xóa hồ sơ bất động sản chưa token hóa"
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-50 text-rose-600 border border-rose-200/70 hover:bg-rose-100 text-xs font-medium transition-colors whitespace-nowrap"
                              >
                                <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                                <span>Xóa hồ sơ</span>
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pagination Bar */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs px-5 py-3 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500 tabular-nums">
        <div className="flex items-center gap-1.5">
          <Globe className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
          <span>
            Hiển thị{" "}
            <strong className="font-semibold text-slate-900">
              {filteredEstates.length === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}
            </strong>{" "}
            đến{" "}
            <strong className="font-semibold text-slate-900">
              {Math.min(page * PAGE_SIZE, filteredEstates.length)}
            </strong>{" "}
            trong tổng số{" "}
            <StatusBadge variant="info" className="mx-0.5">
              {filteredEstates.length}
            </StatusBadge>{" "}
            bất động sản
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-40 font-medium text-slate-700 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" strokeWidth={1.75} /> Trước
          </button>
          <span className="font-semibold text-slate-900 px-1">
            Trang {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-40 font-medium text-slate-700 transition-colors"
          >
            Sau <ChevronRight className="w-4 h-4" strokeWidth={1.75} />
          </button>
        </div>
      </div>
      {/* Modal Xác nhận Xóa hồ sơ BĐS chưa token hóa */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-[2px] flex items-center justify-center p-4">
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-start justify-between gap-3 border-b border-slate-100 pb-3.5">
              <div className="flex items-center gap-2.5">
                <div className="w-10 h-10 rounded-xl bg-rose-50 text-rose-600 flex items-center justify-center shrink-0">
                  <Trash2 className="w-5 h-5" strokeWidth={1.75} />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-slate-900">
                    Xác nhận xóa hồ sơ bất động sản
                  </h3>
                  <p className="text-xs text-slate-500">
                    Thao tác này sẽ xóa vĩnh viễn bản ghi nháp khỏi hệ thống
                  </p>
                </div>
              </div>
              <button
                type="button"
                disabled={deleting}
                onClick={() => setDeleteTarget(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
              >
                <X className="w-4 h-4" strokeWidth={1.75} />
              </button>
            </div>

            <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70 text-xs space-y-1.5">
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Tên bất động sản:</span>
                <strong className="text-slate-900 font-semibold text-right">{deleteTarget.name}</strong>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Mã Token (Symbol):</span>
                <strong className="font-mono text-slate-900">{deleteTarget.symbol}</strong>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Trạng thái hiện tại:</span>
                <StatusBadge variant="warning" dot>
                  Chờ Token hóa
                </StatusBadge>
              </div>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Hồ sơ chưa được triển khai lên Blockchain nên có thể xóa an toàn. Thao tác xóa sẽ được ghi nhận vào Nhật ký quản trị hệ thống.
            </p>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                disabled={deleting}
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700 transition-colors"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={handleConfirmDelete}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-medium shadow-xs transition-colors disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" strokeWidth={1.75} />
                <span>{deleting ? "Đang xóa..." : "Xác nhận xóa"}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
