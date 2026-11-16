import { cookies } from "next/headers";
import AccountClient from "./account-client";

export default async function AccountPage() {
  const cookieStore = await cookies();
  const initialUsername = cookieStore.get("user_name")?.value ?? "";
  const initialEmail = cookieStore.get("user_email")?.value ?? "";

  return <AccountClient initialUsername={initialUsername} initialEmail={initialEmail} />;
}
