import type { Metadata, Viewport } from "next";

import "./globals.css";

import { Providers } from "./providers";

const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "ArtRestore Studio";

export const metadata: Metadata = {
  title: {
    default: `${APP_NAME} - authorized image cleanup and reconstructed timelapses`,
    template: `%s | ${APP_NAME}`,
  },
  description:
    "Remove overlays and date stamps from images you own, and build reconstructed process " +
    "videos from your finished artwork. Attribution and provenance are preserved.",
  robots: { index: true, follow: true },
  openGraph: {
    title: APP_NAME,
    description:
      "Authorized visible-watermark cleanup and reconstructed artwork timelapses for artists, " +
      "photographers and designers.",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#faf7f2",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <a href="#main" className="skip-link">
          Skip to main content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
