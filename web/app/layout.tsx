import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

const DESCRIPTION =
  "Faculty-authored research profiles matched to live funding opportunities with a visible rationale.";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol =
    requestHeaders.get("x-forwarded-proto") ??
    (host?.startsWith("localhost") ? "http" : "https");
  const metadataBase = host ? new URL(`${protocol}://${host}`) : undefined;
  const socialImage = metadataBase
    ? new URL("/og.png", metadataBase).toString()
    : undefined;

  return {
    title: "UR Grant Matcher",
    description: DESCRIPTION,
    metadataBase,
    openGraph: {
      title: "UR Grant Matcher",
      description: DESCRIPTION,
      type: "website",
      images: socialImage
        ? [{ url: socialImage, width: 1747, height: 909 }]
        : undefined,
    },
    twitter: {
      card: "summary_large_image",
      title: "UR Grant Matcher",
      description: DESCRIPTION,
      images: socialImage ? [socialImage] : undefined,
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
