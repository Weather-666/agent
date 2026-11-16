import { redirect } from "next/navigation";

export default function AdminUsersManagePage() {
  redirect("/admin/users-permissions/platform-users");
}
