import { cookies } from "next/headers";
import AppShell from "../app-shell";

export default async function UserLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  const userEmail = cookieStore.get("user_email")?.value ?? "";

  return <AppShell userEmail={userEmail}>{children}</AppShell>;
}
