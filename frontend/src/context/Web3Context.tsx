"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  ReactNode,
  useCallback,
} from "react";
import { ethers, JsonRpcProvider, Contract } from "ethers";
import { CONTRACT_ADDRESSES } from "@/contracts/addresses";
import { ABIS } from "@/contracts/abis";

export interface LabAccount {
  id: number;
  username?: string | null;
  email?: string | null;
  address: string;
  role_label: "admin" | "issuer" | "compliance" | "investor";
  display_name: string;
  is_whitelisted: boolean;
  is_frozen: boolean;
  kyc_status?: string;
  created_at?: string | null;
}

const DEFAULT_LAB_ACCOUNTS: LabAccount[] = [
  {
    id: 1,
    username: "admin",
    email: "admin@rwa.vn",
    address: "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266",
    role_label: "admin",
    display_name: "Quản trị hệ thống (Admin #0)",
    is_whitelisted: true,
    is_frozen: false,
    kyc_status: "approved",
  },
  {
    id: 2,
    username: "issuer",
    email: "issuer@rwa.vn",
    address: "0x70997970c51812dc3a010c7d01b50e0d17dc79c8",
    role_label: "issuer",
    display_name: "Đơn vị phát hành BĐS (Issuer #1)",
    is_whitelisted: true,
    is_frozen: false,
    kyc_status: "approved",
  },
  {
    id: 3,
    username: "compliance",
    email: "compliance@rwa.vn",
    address: "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc",
    role_label: "compliance",
    display_name: "Cán bộ tuân thủ KYC (Compliance #2)",
    is_whitelisted: true,
    is_frozen: false,
    kyc_status: "approved",
  },
  {
    id: 4,
    username: "investora",
    email: "an.nguyen@rwa.vn",
    address: "0x90f79bf6eb2c4f870365e785982e1f101e93b906",
    role_label: "investor",
    display_name: "Nhà đầu tư A — Nguyễn Văn An (#3)",
    is_whitelisted: true,
    is_frozen: false,
    kyc_status: "approved",
  },
  {
    id: 5,
    username: "investorb",
    email: "binh.tran@rwa.vn",
    address: "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65",
    role_label: "investor",
    display_name: "Nhà đầu tư B — Trần Thị Bình (#4)",
    is_whitelisted: false,
    is_frozen: false,
    kyc_status: "pending",
  },
];

interface Web3ContextType {
  account: string | null;
  currentUser: LabAccount | null;
  isAuthenticated: boolean;
  labAccounts: LabAccount[];
  sessionToken: string | null;
  chainId: number;
  rpcProvider: JsonRpcProvider;
  isConnecting: boolean;
  isAuthReady: boolean;
  isKYCVerified: boolean;
  isFrozen: boolean;
  usdcBalance: string;
  apiUrl: string;
  authNotice: string | null;
  setAuthNotice: (notice: string | null) => void;
  clearAuthNotice: () => void;
  loginLabSession: (address: string) => Promise<void>;
  loginWithCredentials: (username: string, password: string) => Promise<LabAccount>;
  registerAccount: (payload: {
    username: string;
    email: string;
    password: string;
    display_name: string;
  }) => Promise<LabAccount>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<string>;
  logoutSession: () => Promise<void>;
  logout: () => Promise<void>;
  refreshBalances: () => Promise<void>;
  claimFaucet: () => Promise<void>;
  apiFetch: (endpoint: string, options?: RequestInit) => Promise<any>;
  getContract: (name: keyof typeof ABIS, customAddress?: string) => Contract;
}

const Web3Context = createContext<Web3ContextType>({} as Web3ContextType);

function extractErrorMessage(data: any, fallback: string): string {
  if (!data) return fallback;
  if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item: any) => (typeof item === "string" ? item : item?.msg || JSON.stringify(item)))
      .join("; ");
  }
  if (typeof data.message === "string" && data.message.trim()) return data.message;
  return fallback;
}

export const Web3Provider = ({ children }: { children: ReactNode }) => {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
  const rpcUrl = process.env.NEXT_PUBLIC_RPC_URL || "http://127.0.0.1:8545";

  const [rpcProvider] = useState<JsonRpcProvider>(() => new JsonRpcProvider(rpcUrl));
  const [labAccounts, setLabAccounts] = useState<LabAccount[]>(DEFAULT_LAB_ACCOUNTS);
  const [currentUser, setCurrentUser] = useState<LabAccount | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isAuthReady, setIsAuthReady] = useState(false);
  const [isKYCVerified, setIsKYCVerified] = useState(false);
  const [isFrozen, setIsFrozen] = useState(false);
  const [usdcBalance, setUsdcBalance] = useState("0.00");
  const [authNotice, setAuthNotice] = useState<string | null>(null);

  // Con trỏ địa chỉ phiên hiện hành để chống tuyệt đối hiện tượng Race Condition
  const activeAddressRef = useRef<string>("");
  const sessionTokenRef = useRef<string | null>(null);

  const clearAuthNotice = useCallback(() => setAuthNotice(null), []);

  const clearClientSession = useCallback((notice?: string) => {
    activeAddressRef.current = "";
    sessionTokenRef.current = null;
    setSessionToken(null);
    setCurrentUser(null);
    setIsKYCVerified(false);
    setIsFrozen(false);
    setUsdcBalance("0.00");
    if (notice) setAuthNotice(notice);
    if (typeof window !== "undefined") {
      localStorage.removeItem("rwa_lab_address");
      localStorage.removeItem("rwa_session_token");
      localStorage.removeItem("rwa_notifications");
      localStorage.removeItem("rwa_user");
      try {
        sessionStorage.clear();
      } catch {
        // ignore storage restrictions
      }
      window.dispatchEvent(new CustomEvent("rwa:session-cleared"));
    }
  }, []);

  const getContract = useCallback(
    (name: keyof typeof ABIS, customAddress?: string) => {
      const addr =
        customAddress || CONTRACT_ADDRESSES[name as keyof typeof CONTRACT_ADDRESSES];
      return new Contract(addr, ABIS[name], rpcProvider);
    },
    [rpcProvider]
  );

  const apiFetch = useCallback(
    async (endpoint: string, options: RequestInit = {}) => {
      const headers: Record<string, string> = {
        ...(options.headers as Record<string, string>),
      };
      if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
      }
      if (sessionTokenRef.current) {
        headers["Authorization"] = `Bearer ${sessionTokenRef.current}`;
      } else if (activeAddressRef.current) {
        headers["X-Session-Address"] = activeAddressRef.current;
      }

      const url = endpoint.startsWith("http")
        ? endpoint
        : `${apiUrl}${endpoint.startsWith("/") ? endpoint : "/" + endpoint}`;

      let res: Response;
      try {
        res = await fetch(url, {
          ...options,
          headers,
        });
      } catch {
        throw new Error(
          "Không thể kết nối đến máy chủ Backend (http://127.0.0.1:8000). Vui lòng kiểm tra kết nối mạng hoặc dịch vụ máy chủ!"
        );
      }

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const errMsg = extractErrorMessage(data, `Lỗi HTTP ${res.status}`);
        if (res.status === 401 && sessionTokenRef.current) {
          clearClientSession("Phiên đăng nhập đã hết hạn hoặc bị thu hồi. Vui lòng đăng nhập lại!");
        }
        throw new Error(errMsg);
      }
      return data;
    },
    [apiUrl, clearClientSession]
  );

  const refreshBalances = useCallback(async () => {
    const targetAddr = activeAddressRef.current;
    if (!targetAddr) return;

    // 1. Cập nhật trạng thái danh sách tài khoản từ Backend (chỉ cập nhật cờ KYC/Frozen của đúng địa chỉ đang chọn)
    try {
      const res = await fetch(`${apiUrl}/auth/accounts`);
      if (res.ok) {
        const list: LabAccount[] = await res.json();
        if (list.length > 0 && activeAddressRef.current === targetAddr) {
          setLabAccounts(list);
          const me = list.find(
            (a) => a.address.toLowerCase() === targetAddr.toLowerCase()
          );
          if (me) {
            setIsKYCVerified(Boolean(me.is_whitelisted));
            setIsFrozen(Boolean(me.is_frozen));
            setCurrentUser((prev) => {
              if (!prev || prev.address.toLowerCase() !== targetAddr.toLowerCase()) {
                return prev;
              }
              if (
                prev.is_whitelisted === me.is_whitelisted &&
                prev.is_frozen === me.is_frozen &&
                prev.kyc_status === me.kyc_status
              ) {
                return prev;
              }
              return { ...prev, ...me };
            });
          }
        }
      }
    } catch {
      // Giữ danh sách mặc định nếu Backend đang khởi động
    }

    // 2. Đọc số dư trực tiếp từ Read-only JsonRpcProvider (ethers.js v6) trên Anvil :8545
    try {
      const usdc = getContract("MockUSDC");
      const registry = getContract("IdentityRegistry");
      const [rawBal, verified] = await Promise.all([
        usdc.balanceOf(targetAddr),
        registry.isVerified(targetAddr),
      ]);
      if (activeAddressRef.current === targetAddr) {
        setUsdcBalance(Number(ethers.formatUnits(rawBal, 6)).toFixed(2));
        setIsKYCVerified(Boolean(verified));
      }
      return;
    } catch {
      // 3. Fallback sang API /ownership/{address}
    }

    try {
      const data = await apiFetch(`/ownership/${targetAddr}`);
      if (
        activeAddressRef.current === targetAddr &&
        data &&
        typeof data.usdc_balance === "number"
      ) {
        setUsdcBalance(data.usdc_balance.toFixed(2));
        setIsKYCVerified(Boolean(data.is_whitelisted));
      }
    } catch {
      // Bỏ qua nếu đang khởi động
    }
  }, [apiUrl, getContract, apiFetch]);

  const loginLabSession = useCallback(
    async (address: string) => {
      const lowerAddr = address.trim().toLowerCase();
      if (!lowerAddr) return;

      // Khóa ngay con trỏ địa chỉ hiện hành để mọi phản hồi mạng cũ bị hủy bỏ
      activeAddressRef.current = lowerAddr;
      if (typeof window !== "undefined") {
        localStorage.setItem("rwa_lab_address", lowerAddr);
        localStorage.removeItem("rwa_logged_out");
      }

      const foundDefault =
        DEFAULT_LAB_ACCOUNTS.find((a) => a.address.toLowerCase() === lowerAddr) ||
        DEFAULT_LAB_ACCOUNTS[3];
      setCurrentUser(foundDefault);
      setIsKYCVerified(Boolean(foundDefault.is_whitelisted));
      setIsFrozen(Boolean(foundDefault.is_frozen));

      setIsConnecting(true);
      try {
        const res = await fetch(`${apiUrl}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: lowerAddr }),
        });

        if (res.ok && activeAddressRef.current === lowerAddr) {
          const data = await res.json();
          sessionTokenRef.current = data.session_token;
          setSessionToken(data.session_token);
          setCurrentUser(data.user);
          setIsKYCVerified(Boolean(data.user.is_whitelisted));
          setIsFrozen(Boolean(data.user.is_frozen));
          if (typeof window !== "undefined") {
            localStorage.setItem("rwa_session_token", data.session_token);
          }
        }
      } catch (err) {
        console.warn("Session login fallback local mode:", err);
      } finally {
        if (activeAddressRef.current === lowerAddr) {
          setIsConnecting(false);
        }
      }

      if (activeAddressRef.current === lowerAddr) {
        await refreshBalances();
      }
    },
    [apiUrl, refreshBalances]
  );

  const loginWithCredentials = useCallback(
    async (username: string, password: string): Promise<LabAccount> => {
      setIsConnecting(true);
      setAuthNotice(null);
      try {
        let res: Response;
        try {
          res = await fetch(`${apiUrl}/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username: username.trim(), password }),
          });
        } catch {
          throw new Error("Không thể kết nối máy chủ Backend (127.0.0.1:8000). Vui lòng thử lại!");
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(extractErrorMessage(data, "Tên đăng nhập hoặc mật khẩu không chính xác!"));
        }
        const loggedUser: LabAccount = data.user;
        const lowerAddr = loggedUser.address.toLowerCase();
        activeAddressRef.current = lowerAddr;
        sessionTokenRef.current = data.session_token;
        setSessionToken(data.session_token);
        setCurrentUser(loggedUser);
        setIsKYCVerified(Boolean(loggedUser.is_whitelisted));
        setIsFrozen(Boolean(loggedUser.is_frozen));
        if (typeof window !== "undefined") {
          localStorage.setItem("rwa_lab_address", lowerAddr);
          localStorage.setItem("rwa_session_token", data.session_token);
          localStorage.removeItem("rwa_logged_out");
        }
        await refreshBalances();
        return loggedUser;
      } finally {
        setIsConnecting(false);
      }
    },
    [apiUrl, refreshBalances]
  );

  const registerAccount = useCallback(
    async (payload: {
      username: string;
      email: string;
      password: string;
      display_name: string;
    }): Promise<LabAccount> => {
      setIsConnecting(true);
      setAuthNotice(null);
      try {
        let res: Response;
        try {
          res = await fetch(`${apiUrl}/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
        } catch {
          throw new Error("Không thể kết nối máy chủ Backend (127.0.0.1:8000). Vui lòng thử lại!");
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(extractErrorMessage(data, "Đăng ký tài khoản thất bại!"));
        }
        const createdUser: LabAccount = data.user;
        const lowerAddr = createdUser.address.toLowerCase();
        activeAddressRef.current = lowerAddr;
        sessionTokenRef.current = data.session_token;
        setSessionToken(data.session_token);
        setCurrentUser(createdUser);
        setIsKYCVerified(Boolean(createdUser.is_whitelisted));
        setIsFrozen(Boolean(createdUser.is_frozen));
        if (typeof window !== "undefined") {
          localStorage.setItem("rwa_lab_address", lowerAddr);
          localStorage.setItem("rwa_session_token", data.session_token);
          localStorage.removeItem("rwa_logged_out");
        }
        await refreshBalances();
        return createdUser;
      } finally {
        setIsConnecting(false);
      }
    },
    [apiUrl, refreshBalances]
  );

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string): Promise<string> => {
      const data = await apiFetch("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      return data?.message || "Đổi mật khẩu thành công!";
    },
    [apiFetch]
  );

  const logoutSession = useCallback(async () => {
    const tok = sessionTokenRef.current;
    // Dọn sạch ngay lập tức toàn bộ state phiên cũ trên giao diện & bộ nhớ trình duyệt
    clearClientSession();
    if (typeof window !== "undefined") {
      localStorage.setItem("rwa_logged_out", "1");
    }
    try {
      if (tok) {
        await fetch(`${apiUrl}/auth/logout`, {
          method: "POST",
          headers: { Authorization: `Bearer ${tok}` },
        });
      }
    } catch {
      // ignore network error on logout
    }
  }, [apiUrl, clearClientSession]);

  const claimFaucet = useCallback(async () => {
    if (!activeAddressRef.current) return;
    try {
      const res = await apiFetch("/wallet/faucet?amount_usdc=50000", {
        method: "POST",
      });
      await refreshBalances();
      alert(
        `[Faucet] Đã ký giao dịch MockUSDC.faucet() phía máy chủ thành công!\n` +
          `• Nhận thêm: +50,000 MockUSDC\n` +
          `• Số dư mới: ${Number(res.new_balance_usdc).toLocaleString("en-US")} MockUSDC\n` +
          `• Mã giao dịch (TxHash): ${res.tx_hash}`
      );
    } catch (err: any) {
      alert("Lỗi nhận Faucet MockUSDC: " + err.message);
    }
  }, [apiFetch, refreshBalances]);

  // Khôi phục và xác thực phiên đăng nhập thực với /auth/me khi mở ứng dụng
  useEffect(() => {
    let cancelled = false;
    const bootstrapAuth = async () => {
      if (typeof window === "undefined") return;
      const wasLoggedOut = localStorage.getItem("rwa_logged_out") === "1";
      const savedTok = localStorage.getItem("rwa_session_token");

      try {
        if (wasLoggedOut || !savedTok) {
          clearClientSession();
          // Vẫn tải danh sách tài khoản (nếu cần cho bảng công khai) nhưng không tự động đăng nhập
          return;
        }

        const res = await fetch(`${apiUrl}/auth/me`, {
          headers: { Authorization: `Bearer ${savedTok}` },
        });
        if (res.ok && !cancelled) {
          const me: LabAccount = await res.json();
          const lowerAddr = me.address.toLowerCase();
          sessionTokenRef.current = savedTok;
          activeAddressRef.current = lowerAddr;
          setSessionToken(savedTok);
          setCurrentUser(me);
          setIsKYCVerified(Boolean(me.is_whitelisted));
          setIsFrozen(Boolean(me.is_frozen));
          localStorage.setItem("rwa_lab_address", lowerAddr);
          await refreshBalances();
        } else if (!cancelled) {
          clearClientSession("Phiên đăng nhập trước đó đã hết hạn. Vui lòng đăng nhập lại!");
        }
      } catch {
        // Nếu Backend đang khởi động tạm thời, giữ nguyên trạng thái an toàn
      } finally {
        if (!cancelled) setIsAuthReady(true);
      }
    };

    bootstrapAuth();
    return () => {
      cancelled = true;
    };
  }, [apiUrl, clearClientSession, refreshBalances]);

  const isAuthenticated = Boolean(currentUser && currentUser.address);

  return (
    <Web3Context.Provider
      value={{
        account: currentUser?.address || null,
        currentUser,
        isAuthenticated,
        labAccounts,
        sessionToken,
        chainId: 31337,
        rpcProvider,
        isConnecting,
        isAuthReady,
        isKYCVerified,
        isFrozen,
        usdcBalance,
        apiUrl,
        authNotice,
        setAuthNotice,
        clearAuthNotice,
        loginLabSession,
        loginWithCredentials,
        registerAccount,
        changePassword,
        logoutSession,
        logout: logoutSession,
        refreshBalances,
        claimFaucet,
        apiFetch,
        getContract,
      }}
    >
      {children}
    </Web3Context.Provider>
  );
};

export const useWeb3 = () => useContext(Web3Context);
