import { redirect } from "next/navigation";

// /admin has no dashboard of its own — land on the main control panel.
export default function AdminPage() {
  redirect("/admin/users");
}
