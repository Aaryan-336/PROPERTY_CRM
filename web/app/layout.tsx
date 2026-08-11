import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans, Space_Grotesk } from "next/font/google";

import { ServiceWorker } from "@/components/ServiceWorker";

import "./globals.css";

/* Display: geometric grotesk, bold and tightly tracked — architectural rather
   than corporate-friendly. Body: warm humanist, tuned for outdoor legibility.
   Mono: tabular figures so prices, budgets and phone numbers align in lists. */
const display = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "700"],
  variable: "--font-display",
});
const body = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Balaji CRM",
  description: "Real estate brokerage CRM — leads, inventory, site visits and calls.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Balaji CRM",
    statusBarStyle: "black-translucent",
  },
};

export const viewport: Viewport = {
  themeColor: "#15141B",
  width: "device-width",
  initialScale: 1,
  // Installed-app feel on a phone, without blocking pinch-zoom for anyone who
  // needs it to read a number in bright sun.
  maximumScale: 5,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        {children}
        <ServiceWorker />
      </body>
    </html>
  );
}
