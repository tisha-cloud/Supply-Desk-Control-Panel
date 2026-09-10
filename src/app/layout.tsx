import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Shell } from "@/components/Shell";
import { ToastProvider } from "@/components/ui";
import { AccessProvider } from "@/lib/access";
import { themeScript } from "@/components/ThemeToggle";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Bangalore Supply Desk",
  description:
    "Document intake, supply inventory and client proposals for Bengaluru commercial real estate.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full`} suppressHydrationWarning>
      <head>
        {/* Applies the stored theme before first paint, so dark-mode users
            never see a white flash on load. */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full">
        <AccessProvider>
          <ToastProvider>
            <Shell>{children}</Shell>
          </ToastProvider>
        </AccessProvider>
      </body>
    </html>
  );
}
