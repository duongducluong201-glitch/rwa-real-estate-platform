"use client";

import React, { useEffect, useState } from "react";
import {
  Coins,
  Send,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Building2,
  Users,
} from "lucide-react";
import { useWeb3 } from "@/context/Web3Context";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CopyAddress } from "@/components/ui/CopyAddress";
import { TableRowsSkeleton } from "@/components/ui/Skeleton";

interface RealEstateItem {
  id: number;
  name: string;
  symbol: string;
  token_address?: string | null;
  valuation: number;
  total_shares: number;
}

interface PayoutItem {
  id?: number;
  investor_name: string;
  investor_address: string;
  shares_held: number;
  ownership_pct: number;
  payout_usdc: number;
  tx_hash: string;
  status: string;
}

interface DistributionRecord {
  id: number;
  real_estate_id: number;
  asset_name: string;
  asset_symbol: string;
  token_address: string;
  period_label: string;
  total_amount_usdc: number;
  total_eligible_shares: number;
  recipients_count: number;
  distributed_by_name: string;
  notes?: string;
  created_at?: string;
  payouts: PayoutItem[];
}

export function DividendPanel() {
  const { currentUser, apiFetch, refreshBalances } = useWeb3();
  const [assets, setAssets] = useState<RealEstateItem[]>([]);
  const [distributions, setDistributions] = useState<DistributionRecord[]>([]);
  const [selectedAssetId, setSelectedAssetId] = useState<string>("");
  const [periodLabel, setPeriodLabel] = useState<string>("Q4/2026 - Doanh thu cho thuê");
  const [amountUsdc, setAmountUsdc] = useState<string>("5000");
  const [notes, setNotes] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const canDistribute = ["issuer", "admin"].includes(currentUser?.role_label || "");

  const loadData = async () => {
    setLoading(true);
    try {
      const [estRes, divRes] = await Promise.all([apiFetch("/assets"), apiFetch("/dividends")]);
      const tokenized = (Array.isArray(estRes) ? estRes : []).filter(
        (a: RealEstateItem) => !!a.token_address
      );
      setAssets(tokenized);
      if (!selectedAssetId && tokenized.length > 0) {
        setSelectedAssetId(String(tokenized[0].id));
      }
      setDistributions(Array.isArray(divRes?.items) ? divRes.items : []);
    } catch (err: any) {
      setFeedback({ type: "err", text: err?.message || "Không thể tải dữ liệu phân phối cổ tức" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [currentUser?.address]);

  const handleDistribute = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAssetId || !amountUsdc || !periodLabel.trim()) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      const res = await apiFetch("/dividends/distribute", {
        method: "POST",
        body: JSON.stringify({
          real_estate_id: Number(selectedAssetId),
          total_amount_usdc: Number(amountUsdc),
          period_label: periodLabel.trim(),
          notes: notes.trim(),
        }),
      });
      await refreshBalances();
      await loadData();
      setExpandedId(res.distribution_id);
      setFeedback({
        type: "ok",
        text: `Đã phân phối thành công ${Number(res.total_amount_usdc).toLocaleString("en-US")} mUSDC cổ tức (${res.asset_symbol}) cho ${res.recipients_count} nhà đầu tư hợp lệ trên Blockchain!`,
      });
      setNotes("");
    } catch (err: any) {
      setFeedback({ type: "err", text: err?.message || "Phân phối cổ tức thất bại" });
    } finally {
      setSubmitting(false);
    }
  };

  const totalDistributedAll = distributions.reduce(
    (acc, d) => acc + Number(d.total_amount_usdc || 0),
    0
  );
  const totalPayoutTxs = distributions.reduce((acc, d) => acc + (d.payouts?.length || 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Phân phối Cổ tức &amp; Lợi tức BĐS
        </h1>
        <p className="text-[13px] text-slate-500 mt-0.5">
          Chụp tỷ lệ sở hữu thực tế On-chain (Snapshot) và tự động chi trả mUSDC tới ví nhà đầu tư hợp lệ.
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
          <div className="flex items-center gap-2">
            {feedback.type === "ok" ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" strokeWidth={1.75} />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" strokeWidth={1.75} />
            )}
            <span>{feedback.text}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="ml-4 font-bold">
            ✕
          </button>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 tabular-nums">
        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Tổng quỹ cổ tức đã chi trả</div>
          <div className="text-2xl font-semibold text-emerald-600 mt-1.5">
            ${totalDistributedAll.toLocaleString("en-US", { maximumFractionDigits: 2 })}{" "}
            <span className="text-xs font-medium text-slate-500">mUSDC</span>
          </div>
        </div>
        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Số đợt phân phối</div>
          <div className="text-2xl font-semibold text-slate-900 mt-1.5">{distributions.length}</div>
        </div>
        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs">
          <div className="text-xs font-medium text-slate-500">Giao dịch chuyển mUSDC on-chain</div>
          <div className="text-2xl font-semibold text-blue-600 mt-1.5">{totalPayoutTxs}</div>
        </div>
      </div>

      {canDistribute && (
        <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-200/80">
            <h2 className="text-base font-semibold text-slate-900 flex items-center gap-2">
              <Coins className="w-4 h-4 text-emerald-600" strokeWidth={1.75} />
              <span>Khởi tạo Đợt Phân phối Cổ tức / Tiền thuê BĐS (On-chain Snapshot)</span>
            </h2>
            <p className="text-[13px] text-slate-500 mt-0.5">
              Hệ thống tự động chụp tỷ lệ sở hữu thực tế (balanceOf) trên Smart Contract, loại trừ ví bị đóng băng / chưa KYC và chuyển mUSDC trực tiếp.
            </p>
          </div>

          <form
            onSubmit={handleDistribute}
            className="p-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1.5">
                Bất động sản đã Token hóa
              </label>
              <select
                value={selectedAssetId}
                onChange={(e) => setSelectedAssetId(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 bg-white focus:border-blue-500 focus:outline-none"
              >
                {assets.length === 0 && <option value="">Chưa có tài sản nào được Token hóa</option>}
                {assets.map((a) => (
                  <option key={a.id} value={a.id}>
                    [{a.symbol}] {a.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1.5">Kỳ phân phối</label>
              <input
                type="text"
                value={periodLabel}
                onChange={(e) => setPeriodLabel(e.target.value)}
                required
                placeholder="VD: Q4/2026 - Doanh thu cho thuê"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1.5">
                Tổng quỹ phân phối (mUSDC)
              </label>
              <input
                type="number"
                min="1"
                step="any"
                value={amountUsdc}
                onChange={(e) => setAmountUsdc(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 tabular-nums focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1.5">
                Ghi chú minh bạch
              </label>
              <input
                type="text"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="VD: Tiền thuê tháng 10-12/2026 sau thuế"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-900 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div className="md:col-span-2 lg:col-span-4 flex justify-end">
              <button
                type="submit"
                disabled={submitting || assets.length === 0}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium shadow-xs transition-colors"
              >
                <Send className="w-4 h-4" strokeWidth={1.75} />
                <span>
                  {submitting
                    ? "Đang chụp Snapshot & chuyển mUSDC on-chain..."
                    : "Phân phối Cổ tức On-chain"}
                </span>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Distribution History Table */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200/80 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Lịch sử các đợt phân phối cổ tức
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Nhấn vào từng đợt để xem chi tiết giao dịch chuyển mUSDC tới từng ví Nhà đầu tư.
            </p>
          </div>
          <button
            onClick={loadData}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 shadow-xs transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-blue-600" : ""}`} strokeWidth={1.75} />
            <span>Tải lại</span>
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 whitespace-nowrap">Đợt</th>
                <th className="py-3 px-4 whitespace-nowrap">Bất động sản</th>
                <th className="py-3 px-4 whitespace-nowrap">Kỳ phân phối</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Tổng quỹ (mUSDC)</th>
                <th className="py-3 px-4 text-center whitespace-nowrap">Nhà đầu tư nhận</th>
                <th className="py-3 px-4 whitespace-nowrap">Thời gian</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Chi tiết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-900">
              {loading ? (
                <TableRowsSkeleton rows={3} cols={7} />
              ) : distributions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-xs text-slate-500">
                    Chưa có đợt phân phối cổ tức nào được thực hiện.
                  </td>
                </tr>
              ) : (
                distributions.map((dist) => (
                  <React.Fragment key={dist.id}>
                    <tr className="hover:bg-slate-50/80 transition-colors tabular-nums">
                      <td className="py-3.5 px-4 font-mono text-xs font-semibold text-blue-600 whitespace-nowrap">
                        #DIV-{dist.id}
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="font-medium flex items-center gap-1.5">
                          <Building2 className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
                          <span>{dist.asset_symbol}</span>
                        </div>
                        <div className="text-xs text-slate-500">{dist.asset_name}</div>
                      </td>
                      <td className="py-3.5 px-4">
                        <div className="text-sm font-medium">{dist.period_label}</div>
                        {dist.notes && <div className="text-xs text-slate-500">{dist.notes}</div>}
                      </td>
                      <td className="py-3.5 px-4 text-right font-semibold text-emerald-600 whitespace-nowrap">
                        +${Number(dist.total_amount_usdc).toLocaleString("en-US", { maximumFractionDigits: 2 })}
                      </td>
                      <td className="py-3.5 px-4 text-center whitespace-nowrap">
                        <StatusBadge variant="info">
                          <Users className="w-3 h-3" strokeWidth={1.75} />
                          {dist.recipients_count}
                        </StatusBadge>
                      </td>
                      <td className="py-3.5 px-4 text-xs text-slate-500 whitespace-nowrap">
                        {dist.created_at ? new Date(dist.created_at).toLocaleString("vi-VN") : "—"}
                      </td>
                      <td className="py-3.5 px-4 text-right whitespace-nowrap">
                        <button
                          type="button"
                          onClick={() => setExpandedId(expandedId === dist.id ? null : dist.id)}
                          className="px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700 shadow-xs transition-colors"
                        >
                          {expandedId === dist.id ? "Thu gọn" : "Xem Payouts"}
                        </button>
                      </td>
                    </tr>
                    {expandedId === dist.id && (
                      <tr className="bg-slate-50/70">
                        <td colSpan={7} className="px-6 py-4">
                          <div className="text-xs font-semibold text-slate-900 mb-2 tabular-nums">
                            Chi tiết giải ngân on-chain (Tổng cổ phần hợp lệ:{" "}
                            {Number(dist.total_eligible_shares).toLocaleString("en-US")} {dist.asset_symbol})
                          </div>
                          <div className="border border-slate-200/80 rounded-xl bg-white overflow-x-auto">
                            <table className="w-full text-left text-xs">
                              <thead>
                                <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                                  <th className="py-2.5 px-3">Nhà đầu tư</th>
                                  <th className="py-2.5 px-3">Địa chỉ ví</th>
                                  <th className="py-2.5 px-3 text-right">Cổ phần nắm giữ</th>
                                  <th className="py-2.5 px-3 text-right">Tỷ lệ nhận</th>
                                  <th className="py-2.5 px-3 text-right">Cổ tức (mUSDC)</th>
                                  <th className="py-2.5 px-3">TxHash On-chain</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-slate-100 tabular-nums">
                                {dist.payouts.map((p, idx) => (
                                  <tr key={p.id || idx} className="hover:bg-slate-50/80">
                                    <td className="py-2.5 px-3 font-medium text-slate-900">
                                      {p.investor_name}
                                    </td>
                                    <td className="py-2.5 px-3">
                                      <CopyAddress value={p.investor_address} prefixLen={8} suffixLen={6} />
                                    </td>
                                    <td className="py-2.5 px-3 text-right">
                                      {Number(p.shares_held).toLocaleString("en-US")}
                                    </td>
                                    <td className="py-2.5 px-3 text-right font-semibold text-blue-600">
                                      {Number(p.ownership_pct).toFixed(2)}%
                                    </td>
                                    <td className="py-2.5 px-3 text-right font-semibold text-emerald-600">
                                      +${Number(p.payout_usdc).toLocaleString("en-US", { maximumFractionDigits: 2 })}
                                    </td>
                                    <td className="py-2.5 px-3">
                                      <CopyAddress value={p.tx_hash} prefixLen={10} suffixLen={4} />
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
