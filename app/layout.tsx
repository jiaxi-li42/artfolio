import type { Metadata } from "next";
import ArchiveTransition from "../components/ArchiveTransition";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARTFOLIO",
  description: "A daily collection of photography, art and visual culture.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><ArchiveTransition>{children}</ArchiveTransition></body></html>;
}
