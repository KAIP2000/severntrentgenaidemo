import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AquaOps Intelligence",
  description: "Observable agentic water operations workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
