"use client";

import React, { useEffect, useState } from "react";
import { RefreshCw, WifiOff } from "lucide-react";
import { useWeb3 } from "@/context/Web3Context";

interface SyncReport {
  status: "SYNCED" | "DRIFT_DETECTED" | "OFFLINE";
  rpc_connected: boolean;
  block_number: number;
  drift_count: number;
}

export function SyncHealthBadge({ compact = false }: { compact?: boolean }) {
  const { currentUser, apiFetch, refreshBalances } = useWeb3();
  const [report, setReport] = useState<SyncReport | null>(null);
  const [syncing, setSyncing] = useState(false);

  const loadSync = async () => {
    try {
      const data = await apiFetch("/system/sync-status");
      if (data?.status) setReport(data);
    } catch {
      setReport({ status: "OFFLINE", rpc_connected: false, block_number: 0, drift_count: 0 });
    }
  };

  useEffect(() => {
    loadSync();
    const timer = setInterval(loadSync, 20000);
    return () => clearInterval(timer);
  }, [currentUser?.address]);

  const handleReconcile = async () => {
    setSyncing(true);
    try {
      const res = await apiFetch("/system/reconcile", { method: "POST" });
      if (res?.sync_report) setReport(res.sync_report);
      await refreshBalances();
    } catch {
      await loadSync();
    } finally {
      setSyncing(false);
    }
  };

  if (!report) return null;

  const canReconcile = ["admin", "compliance", "issuer"].includes(currentUser?.role_label || "");

  if (report.status === "SYNCED") {
    if (compact) {
      return (
        <button
          type="button"
          onClick={loadSync}
          title={`Chuỗi Anvil & DB đồng bộ 100% (Block #${report.block_number})`}
          className="flex items-center justify-center w-full py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 text-emerald-400 transition-colors"
        >
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
        </button>
      );
    }
    return (
      <button
        type="button"
        onClick={loadSync}
        title={`Chuỗi Anvil & DB đồng bộ 100% (Block #${report.block_number})`}
        className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg bg-slate-800/70 hover:bg-slate-800 border border-slate-700/70 text-[11px] text-slate-300 transition-colors"
      >
        <span className="inline-flex items-center gap-1.5 truncate">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
          <span className="truncate font-medium text-slate-200">Chain Synced</span>
        </span>
        <span className="font-mono tabular-nums text-[11px] text-emerald-400 font-medium shrink-0">
          #{report.block_number}
        </span>
      </button>
    );
  }

  if (report.status === "DRIFT_DETECTED") {
    return (
      <button
        type="button"
        disabled={syncing || !canReconcile}
        onClick={canReconcile ? handleReconcile : loadSync}
        title={
          canReconcile
            ? `Phát hiện ${report.drift_count} sai lệch DB ↔ On-chain. Nhấn để đồng bộ ngay!`
            : `Phát hiện ${report.drift_count} sai lệch DB ↔ On-chain`
        }
        className="w-full flex items-center justify-between gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-[11px] text-amber-300 font-medium transition-colors"
      >
        <span className="inline-flex items-center gap-1.5 truncate">
          {syncing ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin shrink-0" strokeWidth={1.75} />
          ) : (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
          )}
          {!compact && (
            <span className="truncate">
              {syncing ? "Đang đồng bộ..." : `Lệch Chain (${report.drift_count})`}
            </span>
          )}
        </span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={loadSync}
      title="Node Anvil (:8545) đang ngoại tuyến"
      className="w-full flex items-center justify-between gap-1.5 px-2.5 py-1.5 rounded-lg bg-rose-500/15 border border-rose-500/30 text-[11px] text-rose-300 font-medium"
    >
      <span className="inline-flex items-center gap-1.5 truncate">
        <WifiOff className="w-3.5 h-3.5 shrink-0" strokeWidth={1.75} />
        {!compact && <span className="truncate">Anvil Offline</span>}
      </span>
    </button>
  );
}
