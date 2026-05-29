import { redirect } from "next/navigation";

// The root is just a gate to sign-in (access is invite-only, nothing to show
// here). Redirect straight to the login page instead of an extra landing step.
export default function Page() {
  redirect("/admin/login");
}
