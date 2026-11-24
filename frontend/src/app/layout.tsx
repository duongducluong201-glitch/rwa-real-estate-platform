import type { Metadata } from "next";
import React, { Suspense } from "react";
import { Be_Vietnam_Pro, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Web3Provider } from "@/context/Web3Context";
import { LanguageProvider } from "@/context/LanguageContext";
import { AppShell } from "@/components/Header";
import { AppShellSkeleton } from "@/components/ui/Skeleton";

const beVietnamPro = Be_Vietnam_Pro({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Hệ thống Token hóa Bất động sản (RWA) — Bản Chính thức",
  description:
    "Hệ thống mô phỏng token hóa bất động sản (RWA) với cơ chế quản lý quyền sở hữu và giao dịch trên mạng cục bộ Anvil — Học viện Kỹ thuật Mật mã (KMA)",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" className={`${beVietnamPro.variable} ${jetbrainsMono.variable}`}>
      <body className="font-sans bg-slate-50 text-slate-900 min-h-screen antialiased">
        <LanguageProvider>
          <Web3Provider>
            <Suspense fallback={<AppShellSkeleton />}>
              <AppShell>{children}</AppShell>
            </Suspense>
          </Web3Provider>
        </LanguageProvider>
      </body>
    </html>
  );
}
