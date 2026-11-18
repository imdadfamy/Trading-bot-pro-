import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = { title: "TRADING INTELLIGENCE PRO", description: "Research and demo trading command center" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="fr"><body>{children}</body></html>;
}
