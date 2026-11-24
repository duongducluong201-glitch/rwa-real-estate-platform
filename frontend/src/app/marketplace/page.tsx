"use client";

import React, { useEffect, useState } from "react";
import { useWeb3 } from "@/context/Web3Context";
import { StatusBadge, BadgeVariant } from "@/components/ui/StatusBadge";
import { CopyAddress } from "@/components/ui/CopyAddress";
import { TableRowsSkeleton } from "@/components/ui/Skeleton";
import {
  PaymentOtpModal,
  PaymentOtpPayload,
  PaymentOtpSuccessResult,
} from "@/components/PaymentOtpModal";
import {
  Search,
  RefreshCw,
  Globe,
  Filter,
  ArrowUpDown,
  ShoppingCart,
  XCircle,
  PlusCircle,
} from "lucide-react";

export default function MarketplacePage() {
  const { currentUser, apiFetch, refreshBalances } = useWeb3();

  const [listings, setListings] = useState<any[]>([]);
  const [holdings, setHoldings] = useState<any[]>([]);
  const [listTokenAddr, setListTokenAddr] = useState<string>("");
  const [listAmount, setListAmount] = useState<string>("50");
  const [listPrice, setListPrice] = useState<string>("115");
  const [buyQuantities, setBuyQuantities] = useState<Record<number, string>>({});
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [loading, setLoading] = useState<boolean>(true);
  const [busy, setBusy] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const loadMarketplace = async () => {
    setLoading(true);
    try {
      const [listData, ownData] = await Promise.all([
        apiFetch("/marketplace/listings"),
        currentUser?.address
          ? apiFetch(`/ownership/${currentUser.address}`)
          : Promise.resolve({ holdings: [] }),
      ]);
      setListings(Array.isArray(listData) ? listData : []);
      const userHoldings = ownData.holdings || [];
      setHoldings(userHoldings);
      if (!listTokenAddr && userHoldings.length > 0) {
        setListTokenAddr(userHoldings[0].token_address);
      }
    } catch (err) {
      console.error("Failed to load marketplace:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMarketplace();
  }, [currentUser?.address]);

  const handleCreateListing = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!listTokenAddr) return;
    setBusy(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/marketplace/list", {
        method: "POST",
        body: JSON.stringify({
          token_address: listTokenAddr,
          amount: Number(listAmount),
          price_per_share: Number(listPrice),
        }),
      });
      await refreshBalances();
      await loadMarketplace();
      setFeedback({
        type: "ok",
        text: `[Niêm yết Ký quỹ thành công] Đã ký gộp AssetToken.approve + Marketplace.list()! Mã lệnh #${res.listing_id} (TxHash: ${res.tx_hash})`,
      });
    } catch (err: any) {
      setFeedback({ type: "err", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const [paymentOtpPayload, setPaymentOtpPayload] = useState<PaymentOtpPayload | null>(null);

  const handleBuyListing = (listing: any) => {
    const qty = Number(buyQuantities[listing.listing_id] || listing.remaining_amount);
    if (!Number.isFinite(qty) || qty <= 0) {
      setFeedback({ type: "err", text: "Vui lòng nhập số lượng cổ phần hợp lệ (> 0)!" });
      return;
    }
    setFeedback(null);
    setPaymentOtpPayload({
      txType: "MARKET_BUY",
      targetId: listing.listing_id,
      estateName:
        listing.real_estate_name || listing.estate_name || listing.name || `BĐS (${listing.symbol})`,
      symbol: listing.symbol || "RWA",
      tokenAddress: listing.token_address || "",
      amount: qty,
      pricePerShare: Number(listing.price_per_share || 0),
    });
  };

  const handleMarketplacePaymentSuccess = async (res: PaymentOtpSuccessResult) => {
    await refreshBalances();
    await loadMarketplace();
    const sym = paymentOtpPayload?.symbol || "RWA";
    const lid = paymentOtpPayload?.targetId;
    setFeedback({
      type: "ok",
      text:
        `[Mua thứ cấp thành công · OTP Verified] Đã mua +${res.shares_bought} ${sym} từ lệnh #${lid} ` +
        `($${Number(res.usdc_paid).toLocaleString("en-US")} mUSDC · Tỷ lệ sở hữu mới: ${Number(
          res.ownership_percent
        ).toFixed(4)}% — Tx: ${res.tx_hash})` +
        (res.receipt_email_queued && res.recipient_email
          ? ` — Biên lai xác nhận đã được gửi về Gmail (${res.recipient_email})!`
          : "!"),
    });
  };

  const handleCancelListing = async (listingId: number) => {
    setBusy(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/marketplace/cancel", {
        method: "POST",
        body: JSON.stringify({ listing_id: listingId }),
      });
      await refreshBalances();
      await loadMarketplace();
      setFeedback({
        type: "ok",
        text: `[Hủy lệnh thành công] Đã hoàn trả toàn bộ token chưa khớp của lệnh #${listingId} về ví người bán! (Tx: ${res.tx_hash})`,
      });
    } catch (err: any) {
      setFeedback({ type: "err", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const filteredListings = listings.filter((item) => {
    if (statusFilter !== "all" && item.status !== statusFilter) return false;
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      (item.real_estate_name || "").toLowerCase().includes(q) ||
      (item.symbol || "").toLowerCase().includes(q) ||
      (item.seller_address || "").toLowerCase().includes(q) ||
      String(item.listing_id).includes(q)
    );
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Sàn Giao dịch Thứ cấp Marketplace
        </h1>
        <p className="text-[13px] text-slate-500 mt-0.5">
          Giao dịch cổ phần bất động sản qua hợp đồng ký quỹ cố định giá (Fixed-Price Escrow) an toàn On-chain.
        </p>
      </div>

      {feedback && (
        <div
          className={`rounded-xl border px-4 py-3 text-xs font-medium flex items-center justify-between ${
            feedback.type === "ok"
              ? "border-emerald-200/80 bg-emerald-50 text-emerald-800"
              : "border-rose-200/80 bg-rose-50 text-rose-800"
          }`}
        >
          <span>{feedback.text}</span>
          <button onClick={() => setFeedback(null)} className="ml-4 font-bold">
            ✕
          </button>
        </div>
      )}

      {/* MAIN DATA TABLE CARD: MARKETPLACE ESCROW LISTINGS */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        {/* Toolbar */}
        <div className="px-5 py-3.5 border-b border-slate-200/80 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="relative inline-flex items-center">
              <select
                aria-label="Filter Listing Status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="appearance-none pl-3.5 pr-7 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 focus:outline-none focus:border-blue-500"
              >
                <option value="all">Bộ lọc: Tất cả</option>
                <option value="open">Trạng thái: Đang mở</option>
                <option value="filled">Trạng thái: Đã khớp hết</option>
                <option value="cancelled">Trạng thái: Đã hủy</option>
              </select>
              <Filter
                className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 pointer-events-none"
                strokeWidth={1.75}
              />
            </div>

            <div className="relative">
              <input
                type="text"
                placeholder="Tìm kiếm..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-60 pl-3 pr-8 py-1.5 border border-slate-200 rounded-lg text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-blue-500"
              />
              <Search
                className="w-4 h-4 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2"
                strokeWidth={1.75}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={loadMarketplace}
              disabled={busy || loading}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 shadow-xs transition-colors"
            >
              <RefreshCw
                className={`w-4 h-4 ${busy || loading ? "animate-spin text-blue-600" : ""}`}
                strokeWidth={1.75}
              />
              <span>Tải lại</span>
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 w-16 whitespace-nowrap">
                  <span className="inline-flex items-center gap-1">
                    ID <ArrowUpDown className="w-3 h-3 opacity-60" strokeWidth={1.75} />
                  </span>
                </th>
                <th className="py-3 px-4 whitespace-nowrap">TÀI SẢN BĐS</th>
                <th className="py-3 px-4 whitespace-nowrap">NGƯỜI BÁN</th>
                <th className="py-3 px-4 whitespace-nowrap">CỔ PHẦN ESCROW</th>
                <th className="py-3 px-4 whitespace-nowrap">ĐƠN GIÁ / CỔ PHẦN</th>
                <th className="py-3 px-4 whitespace-nowrap">TRẠNG THÁI</th>
                <th className="py-3 px-4 whitespace-nowrap">CẬP NHẬT LÚC</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">THAO TÁC</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-900">
              {loading ? (
                <TableRowsSkeleton rows={4} cols={8} />
              ) : filteredListings.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-xs text-slate-500">
                    Chưa có lệnh niêm yết nào trên sàn thứ cấp. Hãy dùng biểu mẫu bên dưới để ký quỹ token vào Marketplace!
                  </td>
                </tr>
              ) : (
                filteredListings.map((item) => {
                  const isSeller =
                    currentUser?.address.toLowerCase() === item.seller_address.toLowerCase();
                  const buyVal =
                    buyQuantities[item.listing_id] ??
                    String(Math.min(20, item.remaining_amount));

                  const statusBadge: { label: string; variant: BadgeVariant; dot?: boolean } =
                    item.status === "open"
                      ? { label: "Đang mở Escrow", variant: "success", dot: true }
                      : item.status === "filled"
                      ? { label: "Đã khớp hết", variant: "info", dot: true }
                      : { label: "Đã hủy", variant: "neutral" };

                  return (
                    <tr key={item.listing_id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-3.5 px-4 font-mono text-xs font-semibold text-slate-700 whitespace-nowrap tabular-nums">
                        #{item.listing_id}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="text-sm font-medium text-slate-900">{item.real_estate_name}</div>
                        <div className="mt-0.5">
                          <StatusBadge variant="info" className="font-mono">
                            {item.symbol}
                          </StatusBadge>
                        </div>
                      </td>
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <div className="text-sm font-medium text-slate-900">{item.seller_name}</div>
                        <CopyAddress value={item.seller_address} prefixLen={8} suffixLen={4} />
                      </td>
                      <td className="py-3.5 px-4 whitespace-nowrap tabular-nums">
                        <StatusBadge variant="purple">
                          {Number(item.remaining_amount).toLocaleString("en-US")} /{" "}
                          {Number(item.initial_amount).toLocaleString("en-US")} {item.symbol}
                        </StatusBadge>
                      </td>
                      <td className="py-3.5 px-4 text-sm font-semibold text-slate-900 whitespace-nowrap tabular-nums">
                        ${Number(item.price_per_share).toLocaleString("en-US")}{" "}
                        <span className="text-xs font-normal text-slate-500">mUSDC</span>
                      </td>
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <StatusBadge variant={statusBadge.variant} dot={statusBadge.dot}>
                          {statusBadge.label}
                        </StatusBadge>
                      </td>
                      <td className="py-3.5 px-4 text-xs text-slate-500 whitespace-nowrap tabular-nums">
                        {item.updated_at
                          ? item.updated_at.replace("T", " ").slice(0, 16)
                          : "2026-04-15 08:59"}
                      </td>
                      <td className="py-3.5 px-4 text-right whitespace-nowrap">
                        {item.status === "open" ? (
                          <div className="inline-flex items-center justify-end gap-1.5">
                            <input
                              type="number"
                              min="1"
                              max={item.remaining_amount}
                              value={buyVal}
                              onChange={(e) =>
                                setBuyQuantities((prev) => ({
                                  ...prev,
                                  [item.listing_id]: e.target.value,
                                }))
                              }
                              className="w-16 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-900 tabular-nums focus:border-blue-500 focus:outline-none"
                            />
                            <button
                              onClick={() => handleBuyListing(item)}
                              disabled={busy}
                              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium shadow-xs transition-colors"
                            >
                              <ShoppingCart className="w-3.5 h-3.5" strokeWidth={1.75} />
                              <span>Mua</span>
                            </button>
                            {isSeller && (
                              <button
                                onClick={() => handleCancelListing(item.listing_id)}
                                disabled={busy}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-50 text-rose-600 border border-rose-200/70 hover:bg-rose-100 text-xs font-medium transition-colors"
                              >
                                <XCircle className="w-3.5 h-3.5" strokeWidth={1.75} />
                                <span>Hủy lệnh</span>
                              </button>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400">Đã đóng</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 border-t border-slate-200/80 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 tabular-nums">
          <div className="flex items-center gap-1.5">
            <Globe className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
            <span>
              Hiển thị từ 1 đến {filteredListings.length} trong{" "}
              <StatusBadge variant="neutral" className="mx-0.5">
                {filteredListings.length}
              </StatusBadge>{" "}
              bản ghi
            </span>
          </div>
          <div>
            Smart Contract: <code className="font-mono text-blue-600">Marketplace (Fixed-Price Escrow)</code>
          </div>
        </div>
      </div>

      {/* CREATE ESCROW LISTING CARD (UC-11) */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs p-5">
        <div className="border-b border-slate-100 pb-3.5 mb-4">
          <StatusBadge variant="purple" className="mb-1.5">
            ESCROW LISTING CREATION
          </StatusBadge>
          <h2 className="text-base font-semibold text-slate-900">
            Đăng bán Cổ phần BĐS vào Hợp đồng Ký quỹ (Escrow)
          </h2>
          <p className="text-[13px] text-slate-500 mt-0.5">
            Tự động ký gộp <code className="font-mono text-xs text-slate-700">AssetToken.approve(Marketplace, amount)</code> và{" "}
            <code className="font-mono text-xs text-slate-700">Marketplace.list(token, amount, pricePerShare)</code>.
          </p>
        </div>

        <form
          onSubmit={handleCreateListing}
          className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end text-xs"
        >
          <div>
            <label className="block font-medium text-slate-700 mb-1.5">
              Chọn Token BĐS đang sở hữu:
            </label>
            <select
              value={listTokenAddr}
              onChange={(e) => setListTokenAddr(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none"
            >
              {holdings.map((h) => (
                <option key={h.token_address} value={h.token_address}>
                  {h.symbol} — {h.name} (Số dư: {h.shares_balance})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block font-medium text-slate-700 mb-1.5">
              Số lượng cổ phần ký quỹ:
            </label>
            <input
              type="number"
              min="1"
              value={listAmount}
              onChange={(e) => setListAmount(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900 tabular-nums focus:border-blue-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block font-medium text-slate-700 mb-1.5">
              Đơn giá mỗi cổ phần (mUSDC):
            </label>
            <input
              type="number"
              min="1"
              step="0.5"
              value={listPrice}
              onChange={(e) => setListPrice(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900 tabular-nums focus:border-blue-500 focus:outline-none"
            />
          </div>

          <button
            type="submit"
            disabled={busy || !listTokenAddr}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-xs transition-colors disabled:opacity-50"
          >
            <PlusCircle className="w-4 h-4" strokeWidth={1.75} />
            <span>{busy ? "Đang xử lý..." : "Ký quỹ & Đăng bán"}</span>
          </button>
        </form>
      </div>

      {/* Modal Xác Thực OTP qua Gmail & Thanh Toán MockUSDC (UC-11) */}
      <PaymentOtpModal
        open={Boolean(paymentOtpPayload)}
        payload={paymentOtpPayload}
        onClose={() => setPaymentOtpPayload(null)}
        onSuccess={handleMarketplacePaymentSuccess}
      />
    </div>
  );
}
