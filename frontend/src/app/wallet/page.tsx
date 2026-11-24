"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useWeb3 } from "@/context/Web3Context";
import { formatEventTypeLabel } from "@/i18n/labels";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { CopyAddress } from "@/components/ui/CopyAddress";
import { TableRowsSkeleton } from "@/components/ui/Skeleton";
import {
  RefreshCw,
  Globe,
  Eye,
  ArrowUpDown,
  Send,
  Coins,
  PieChart,
  TrendingUp,
  Wallet,
  Building2,
} from "lucide-react";

const CHART_COLORS = ["#2563eb", "#10b981", "#f59e0b", "#7c3aed", "#e11d48", "#0d9488"];

export default function WalletPage() {
  const {
    currentUser,
    labAccounts,
    usdcBalance,
    isKYCVerified,
    claimFaucet,
    apiFetch,
    refreshBalances,
  } = useWeb3();

  const [portfolio, setPortfolio] = useState<any>({
    holdings: [],
    total_portfolio_value_usdc: 0,
  });
  const [history, setHistory] = useState<any[]>([]);
  const [myDividends, setMyDividends] = useState<{ total_received_usdc: number; items: any[] }>({
    total_received_usdc: 0,
    items: [],
  });
  const [selectedToken, setSelectedToken] = useState<string>("");
  const [toAddress, setToAddress] = useState<string>("");
  const [transferAmount, setTransferAmount] = useState<string>("20");
  const [loading, setLoading] = useState<boolean>(true);
  const [busy, setBusy] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const loadWalletData = async () => {
    if (!currentUser?.address) return;
    setLoading(true);
    try {
      const [ownData, txData, divData] = await Promise.all([
        apiFetch(`/ownership/${currentUser.address}`),
        apiFetch(`/transactions?address=${currentUser.address}`),
        apiFetch("/dividends/my").catch(() => ({ total_received_usdc: 0, items: [] })),
      ]);
      setPortfolio(ownData);
      setHistory(Array.isArray(txData) ? txData : []);
      setMyDividends({
        total_received_usdc: Number(divData?.total_received_usdc || 0),
        items: Array.isArray(divData?.items) ? divData.items : [],
      });
      if (!selectedToken && ownData.holdings?.length > 0) {
        setSelectedToken(ownData.holdings[0].token_address);
      }
    } catch (err) {
      console.error("Load wallet error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadWalletData();
    const otherInvestor = labAccounts.find(
      (a) =>
        a.address.toLowerCase() !== currentUser?.address.toLowerCase() &&
        a.role_label === "investor"
    );
    if (otherInvestor && !toAddress) {
      setToAddress(otherInvestor.address);
    }
  }, [currentUser?.address]);

  const handleP2PTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);
    if (!currentUser) {
      setFeedback({ type: "err", text: "Vui lòng đăng nhập để thực hiện giao dịch chuyển nhượng!" });
      return;
    }
    if (!selectedToken) {
      setFeedback({ type: "err", text: "Vui lòng chọn loại Token BĐS cần chuyển!" });
      return;
    }
    const cleanTo = toAddress.trim();
    if (!/^0x[a-fA-F0-9]{40}$/.test(cleanTo)) {
      setFeedback({
        type: "err",
        text: "Địa chỉ ví người nhận không đúng định dạng Ethereum (0x... 42 ký tự)!",
      });
      return;
    }
    if (cleanTo.toLowerCase() === currentUser.address.toLowerCase()) {
      setFeedback({
        type: "err",
        text: "Không thể tự chuyển nhượng Token cho chính địa chỉ ví của mình!",
      });
      return;
    }
    const parsedAmount = Number(transferAmount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
      setFeedback({
        type: "err",
        text: "Số lượng cổ phần chuyển nhượng phải là số dương lớn hơn 0!",
      });
      return;
    }

    setBusy(true);
    try {
      const res = await apiFetch("/tokens/transfer", {
        method: "POST",
        body: JSON.stringify({
          token_address: selectedToken,
          to_address: cleanTo,
          amount: parsedAmount,
        }),
      });
      await refreshBalances();
      await loadWalletData();
      window.dispatchEvent(new Event("rwa:notifications-updated"));
      setFeedback({
        type: "ok",
        text:
          `[Chuyển nhượng P2P thành công] Đã chuyển ${res.amount} cổ phần tới ${res.to} qua hàm _update kiểm tra tuân thủ!` +
          (res.notified_recipient
            ? " Hệ thống đã gửi thông báo nhận cổ phần tới tài khoản người nhận."
            : "") +
          ` (TxHash: ${res.tx_hash})`,
      });
    } catch (err: any) {
      setFeedback({ type: "err", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  if (!currentUser) {
    return (
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs p-8 max-w-2xl mx-auto text-center space-y-4 my-8">
        <StatusBadge variant="warning">401 · YÊU CẦU ĐĂNG NHẬP</StatusBadge>
        <h1 className="text-lg font-semibold text-slate-900">
          Vui lòng đăng nhập để xem Ví Tài sản &amp; Danh mục đầu tư
        </h1>
        <p className="text-[13px] text-slate-500">
          Bạn cần đăng nhập tài khoản để xem số dư MockUSDC, cổ phần BĐS đang sở hữu, nhận cổ tức và chuyển nhượng P2P.
        </p>
        <div className="pt-2">
          <Link
            href="/login"
            className="inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium shadow-xs transition-colors"
          >
            Đi tới trang Đăng nhập / Đăng ký →
          </Link>
        </div>
      </div>
    );
  }

  const holdings: any[] = portfolio.holdings || [];
  const totalPortfolioVal = Number(portfolio.total_portfolio_value_usdc || 0);
  const chartSlices = holdings
    .filter((h) => Number(h.estimated_value_usdc || 0) > 0)
    .map((h, idx) => {
      const val = Number(h.estimated_value_usdc || 0);
      const pct = totalPortfolioVal > 0 ? (val / totalPortfolioVal) * 100 : 0;
      return {
        symbol: h.symbol,
        name: h.name,
        value: val,
        pct,
        color: CHART_COLORS[idx % CHART_COLORS.length],
      };
    });

  let cumulativePct = 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          Ví Tài sản &amp; Danh mục Đầu tư
        </h1>
        <p className="text-[13px] text-slate-500 mt-0.5">
          Theo dõi phần sở hữu bất động sản On-chain, cổ tức mUSDC đã nhận và thực hiện chuyển nhượng P2P.
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

      {/* PORTFOLIO KPI SUMMARY + DONUT ALLOCATION CHART */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-3 gap-4 tabular-nums">
          <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500">Tổng giá trị cổ phần BĐS</span>
              <span className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
                <Building2 className="w-4 h-4" strokeWidth={1.75} />
              </span>
            </div>
            <div className="text-2xl font-semibold text-slate-900 mt-2">
              ${totalPortfolioVal.toLocaleString("en-US", { maximumFractionDigits: 2 })}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Đang nắm giữ {holdings.length} mã bất động sản
            </div>
          </div>

          <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500">Số dư thanh toán mUSDC</span>
              <span className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center">
                <Wallet className="w-4 h-4" strokeWidth={1.75} />
              </span>
            </div>
            <div className="text-2xl font-semibold text-blue-600 mt-2">
              ${Number(usdcBalance || 0).toLocaleString("en-US", { maximumFractionDigits: 2 })}
            </div>
            <div className="text-xs text-slate-500 mt-1">Sẵn sàng mua sơ cấp &amp; chợ thứ cấp</div>
          </div>

          <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500">Cổ tức đã nhận</span>
              <span className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
                <TrendingUp className="w-4 h-4" strokeWidth={1.75} />
              </span>
            </div>
            <div className="text-2xl font-semibold text-emerald-600 mt-2">
              +${myDividends.total_received_usdc.toLocaleString("en-US", { maximumFractionDigits: 2 })}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Từ {myDividends.items.length} đợt chi trả lợi tức on-chain
            </div>
          </div>
        </div>

        {/* SVG Portfolio Allocation Donut */}
        <div className="bg-white border border-slate-200/80 rounded-xl p-5 shadow-xs flex items-center gap-4">
          <div className="shrink-0 relative w-24 h-24">
            {chartSlices.length > 0 ? (
              <svg viewBox="0 0 36 36" className="w-24 h-24 -rotate-90">
                {chartSlices.map((s) => {
                  const dashArray = `${s.pct} ${100 - s.pct}`;
                  const dashOffset = -cumulativePct;
                  cumulativePct += s.pct;
                  return (
                    <circle
                      key={s.symbol}
                      cx="18"
                      cy="18"
                      r="15.915"
                      fill="transparent"
                      stroke={s.color}
                      strokeWidth="4.2"
                      strokeDasharray={dashArray}
                      strokeDashoffset={dashOffset}
                    />
                  );
                })}
              </svg>
            ) : (
              <div className="w-24 h-24 rounded-full border-4 border-dashed border-slate-200 flex items-center justify-center text-slate-400">
                <PieChart className="w-6 h-6" strokeWidth={1.75} />
              </div>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold text-slate-900 mb-1.5">Tỷ trọng Danh mục BĐS</div>
            {chartSlices.length === 0 ? (
              <p className="text-xs text-slate-500">Chưa có cổ phần BĐS trong danh mục.</p>
            ) : (
              <div className="space-y-1 max-h-20 overflow-y-auto tabular-nums">
                {chartSlices.map((s) => (
                  <div key={s.symbol} className="flex items-center justify-between text-xs gap-2">
                    <div className="flex items-center gap-1.5 truncate">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                      <span className="font-medium text-slate-900 truncate">{s.symbol}</span>
                    </div>
                    <span className="font-mono text-slate-500 shrink-0">{s.pct.toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* PORTFOLIO HOLDINGS DATA TABLE (UC-14) */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200/80 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Danh mục Phần sở hữu Bất động sản
            </h2>
            <p className="text-xs text-slate-500 mt-0.5 tabular-nums">
              Tài khoản đang chọn:{" "}
              <strong className="font-medium text-slate-900">{currentUser?.display_name}</strong> · Tổng giá trị
              danh mục:{" "}
              <strong className="font-semibold text-emerald-600">
                ${totalPortfolioVal.toLocaleString("en-US")} mUSDC
              </strong>
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={async () => {
                await claimFaucet();
                await loadWalletData();
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 hover:bg-emerald-100 text-emerald-700 ring-1 ring-inset ring-emerald-600/20 transition-colors"
            >
              <Coins className="w-4 h-4" strokeWidth={1.75} />
              <span>+50,000 mUSDC Faucet</span>
            </button>
            <button
              onClick={loadWalletData}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-medium text-slate-700 bg-white hover:bg-slate-50 shadow-xs transition-colors"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-blue-600" : ""}`} strokeWidth={1.75} />
              <span>Tải lại</span>
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 whitespace-nowrap">Bất động sản</th>
                <th className="py-3 px-3 whitespace-nowrap">Cổ phần nắm giữ</th>
                <th className="py-3 px-3 whitespace-nowrap">Tỷ lệ</th>
                <th className="py-3 px-3 whitespace-nowrap">Giá trị ước tính</th>
                <th className="py-3 px-3 whitespace-nowrap">Trạng thái tuân thủ</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-900">
              {loading ? (
                <TableRowsSkeleton rows={4} cols={6} />
              ) : holdings.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-xs text-slate-500">
                    Chưa có cổ phần bất động sản nào trong ví hiện tại.
                  </td>
                </tr>
              ) : (
                holdings.map((h: any) => (
                  <tr key={h.token_address} className="hover:bg-slate-50/80 transition-colors">
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-slate-400 tabular-nums">
                          #{h.real_estate_id}
                        </span>
                        <Link
                          href={`/assets/${h.real_estate_id}`}
                          className="text-sm font-medium text-slate-900 hover:text-blue-600 truncate max-w-[210px]"
                          title={h.name}
                        >
                          {h.name}
                        </Link>
                        <StatusBadge variant="info" className="font-mono !px-2 !py-0 !text-[11px]">
                          {h.symbol}
                        </StatusBadge>
                      </div>
                      <div className="mt-0.5 pl-6">
                        <CopyAddress value={h.token_address} prefixLen={6} suffixLen={4} />
                      </div>
                    </td>
                    <td className="py-3.5 px-3 text-sm font-medium whitespace-nowrap tabular-nums">
                      {Number(h.shares_balance).toLocaleString("en-US")} /{" "}
                      {Number(h.total_shares).toLocaleString("en-US")}
                    </td>
                    <td className="py-3.5 px-3 whitespace-nowrap tabular-nums">
                      <StatusBadge variant="purple">{h.ownership_percent}%</StatusBadge>
                    </td>
                    <td className="py-3.5 px-3 text-sm font-semibold text-emerald-600 whitespace-nowrap tabular-nums">
                      ${Number(h.estimated_value_usdc).toLocaleString("en-US")} mUSDC
                    </td>
                    <td className="py-3.5 px-3 whitespace-nowrap">
                      {h.is_frozen ? (
                        <StatusBadge variant="danger" dot>
                          Đang bị đóng băng
                        </StatusBadge>
                      ) : isKYCVerified ? (
                        <StatusBadge variant="success" dot>
                          Đã duyệt KYC
                        </StatusBadge>
                      ) : (
                        <StatusBadge variant="warning" dot>
                          Chờ KYC
                        </StatusBadge>
                      )}
                    </td>
                    <td className="py-3.5 px-4 text-right whitespace-nowrap">
                      <Link
                        href={`/assets/${h.real_estate_id}`}
                        className="w-8 h-8 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 inline-flex items-center justify-center shadow-xs transition-colors"
                      >
                        <Eye className="w-4 h-4" strokeWidth={1.75} />
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="px-5 py-3 border-t border-slate-200/80 flex items-center gap-1.5 text-xs text-slate-500 tabular-nums">
          <Globe className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
          <span>
            Hiển thị 1–{holdings.length} trong tổng số{" "}
            <StatusBadge variant="neutral" className="mx-0.5">
              {holdings.length}
            </StatusBadge>{" "}
            tài sản sở hữu
          </span>
        </div>
      </div>

      {/* DIVIDEND INCOME HISTORY TABLE */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200/80 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-slate-900 flex items-center gap-2">
              <Coins className="w-4 h-4 text-emerald-600" strokeWidth={1.75} />
              <span>Lịch sử nhận Cổ tức / Tiền thuê BĐS (mUSDC On-chain)</span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Khoản lợi tức được đơn vị phát hành tự động chia tỷ lệ và chuyển mUSDC trực tiếp vào ví của bạn.
            </p>
          </div>
          <StatusBadge variant="success" className="tabular-nums">
            Tổng nhận: +${myDividends.total_received_usdc.toLocaleString("en-US", { maximumFractionDigits: 2 })} mUSDC
          </StatusBadge>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 whitespace-nowrap">Bất động sản</th>
                <th className="py-3 px-4 whitespace-nowrap">Kỳ phân phối</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Cổ phần chụp Snapshot</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Tỷ lệ chia</th>
                <th className="py-3 px-4 text-right whitespace-nowrap">Cổ tức nhận (mUSDC)</th>
                <th className="py-3 px-4 whitespace-nowrap">Thời gian</th>
                <th className="py-3 px-4 whitespace-nowrap">TxHash</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-900">
              {myDividends.items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-xs text-slate-500">
                    Chưa có đợt chi trả cổ tức nào cho tài khoản này.
                  </td>
                </tr>
              ) : (
                myDividends.items.map((d: any) => (
                  <tr key={d.id} className="hover:bg-slate-50/80 transition-colors tabular-nums">
                    <td className="py-3.5 px-4 font-medium">
                      {d.asset_name}{" "}
                      <StatusBadge variant="info" className="ml-1 font-mono">
                        {d.asset_symbol}
                      </StatusBadge>
                    </td>
                    <td className="py-3.5 px-4 text-xs text-slate-600">{d.period_label}</td>
                    <td className="py-3.5 px-4 text-right font-mono text-xs">
                      {Number(d.shares_held).toLocaleString("en-US")}
                    </td>
                    <td className="py-3.5 px-4 text-right text-xs font-semibold text-blue-600">
                      {Number(d.ownership_pct).toFixed(2)}%
                    </td>
                    <td className="py-3.5 px-4 text-right text-sm font-semibold text-emerald-600">
                      +${Number(d.payout_usdc).toLocaleString("en-US", { maximumFractionDigits: 2 })}
                    </td>
                    <td className="py-3.5 px-4 text-xs text-slate-500 whitespace-nowrap">
                      {d.created_at ? new Date(d.created_at).toLocaleString("vi-VN") : "—"}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <CopyAddress value={d.tx_hash} prefixLen={10} suffixLen={4} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* P2P TRANSFER FORM CARD (UC-10) */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs p-5">
        <div className="border-b border-slate-100 pb-3.5 mb-4">
          <StatusBadge variant="info" className="mb-1.5">
            CHUYỂN NHƯỢNG P2P TRỰC TIẾP
          </StatusBadge>
          <h2 className="text-base font-semibold text-slate-900">
            Chuyển nhượng Cổ phần BĐS Ngang hàng (P2P)
          </h2>
          <p className="text-[13px] text-slate-500 mt-0.5">
            Kiểm tra tuân thủ trực tiếp tại hàm <code className="font-mono text-xs text-slate-700">_update</code>: tự động chặn nếu người gửi hoặc người nhận chưa
            duyệt KYC trong <code className="font-mono text-xs text-slate-700">IdentityRegistry</code> hoặc đang bị đóng băng.
          </p>
        </div>

        <form
          onSubmit={handleP2PTransfer}
          className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end text-xs"
        >
          <div>
            <label className="block font-medium text-slate-700 mb-1.5">Chọn Token BĐS:</label>
            <select
              value={selectedToken}
              onChange={(e) => setSelectedToken(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none"
            >
              {holdings.map((h: any) => (
                <option key={h.token_address} value={h.token_address}>
                  {h.symbol} — {h.name} (Dư: {h.shares_balance})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block font-medium text-slate-700 mb-1.5">
              Chọn Tài khoản Nhận trong Lab:
            </label>
            <select
              value={toAddress}
              onChange={(e) => setToAddress(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900 focus:border-blue-500 focus:outline-none"
            >
              {labAccounts
                .filter((a) => a.address.toLowerCase() !== currentUser?.address.toLowerCase())
                .map((a) => (
                  <option key={a.address} value={a.address}>
                    {a.display_name} ({a.is_whitelisted ? "Đã duyệt KYC" : "Chưa KYC - Test Revert"})
                  </option>
                ))}
            </select>
          </div>

          <div>
            <label className="block font-medium text-slate-700 mb-1.5">
              Số lượng cổ phần chuyển:
            </label>
            <input
              type="number"
              min="1"
              value={transferAmount}
              onChange={(e) => setTransferAmount(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-slate-900 tabular-nums focus:border-blue-500 focus:outline-none"
            />
          </div>

          <button
            type="submit"
            disabled={busy || !selectedToken}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 px-4 py-2 text-sm font-medium text-white shadow-xs transition-colors disabled:opacity-50"
          >
            <Send className="w-4 h-4" strokeWidth={1.75} />
            <span>{busy ? "Đang ký..." : "Chuyển nhượng P2P"}</span>
          </button>
        </form>
      </div>

      {/* ON-CHAIN TRANSFER HISTORY TABLE */}
      <div className="bg-white border border-slate-200/80 rounded-xl shadow-xs overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200/80">
          <h2 className="text-base font-semibold text-slate-900">
            Lịch sử Biến động Giao dịch On-chain
          </h2>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200/80 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4 whitespace-nowrap">ID</th>
                <th className="py-3 px-4 whitespace-nowrap">Loại sự kiện</th>
                <th className="py-3 px-4 whitespace-nowrap">Tài sản</th>
                <th className="py-3 px-4 whitespace-nowrap">Từ ví</th>
                <th className="py-3 px-4 whitespace-nowrap">Đến ví</th>
                <th className="py-3 px-4 whitespace-nowrap">Số lượng</th>
                <th className="py-3 px-4 whitespace-nowrap">TxHash</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-900">
              {loading ? (
                <TableRowsSkeleton rows={4} cols={7} />
              ) : history.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-xs text-slate-500">
                    Chưa có giao dịch chuyển nhượng nào phát sinh cho ví này.
                  </td>
                </tr>
              ) : (
                history.map((t) => (
                  <tr key={t.id} className="hover:bg-slate-50/80 transition-colors tabular-nums">
                    <td className="py-3.5 px-4 font-mono text-xs text-slate-600">#{t.id}</td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <StatusBadge
                        variant={
                          t.event_type === "PRIMARY_BUY"
                            ? "success"
                            : t.event_type === "FORCED_TRANSFER"
                            ? "purple"
                            : "info"
                        }
                      >
                        {formatEventTypeLabel(t.event_type)}
                      </StatusBadge>
                    </td>
                    <td className="py-3.5 px-4 font-medium">
                      {t.real_estate_name} ({t.symbol})
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <CopyAddress value={t.from_address} prefixLen={6} suffixLen={4} />
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <CopyAddress value={t.to_address} prefixLen={6} suffixLen={4} />
                    </td>
                    <td className="py-3.5 px-4 font-semibold whitespace-nowrap">
                      {Number(t.amount).toLocaleString("en-US")} {t.symbol}
                    </td>
                    <td className="py-3.5 px-4 whitespace-nowrap">
                      <CopyAddress value={t.tx_hash} prefixLen={10} suffixLen={4} />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="px-5 py-3 border-t border-slate-200/80 flex items-center gap-1.5 text-xs text-slate-500 tabular-nums">
          <Globe className="w-4 h-4 text-slate-400" strokeWidth={1.75} />
          <span>
            Hiển thị 1–{history.length} trong tổng số{" "}
            <StatusBadge variant="neutral" className="mx-0.5">
              {history.length}
            </StatusBadge>{" "}
            giao dịch
          </span>
        </div>
      </div>
    </div>
  );
}
