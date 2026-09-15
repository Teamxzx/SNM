import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NOC LAB — SNMP Network Monitor",
  description: "ระบบ Monitor Router และ Switch ผ่าน SNMP สำหรับห้องปฏิบัติการเครือข่าย",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="th"><body className="antialiased">{children}</body></html>;
}
