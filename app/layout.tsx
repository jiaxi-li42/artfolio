import type { Metadata, Viewport } from "next";
import ArchiveTransition from "../components/ArchiveTransition";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARTFOLIO",
  description: "A daily collection of photography, art and visual culture.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><ArchiveTransition>{children}</ArchiveTransition></body></html>;
}
