import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import { findUserById, logAdminAction } from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  return_path: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const auth = await requireAccess(req);
  if (!auth.ok) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const secretKey = process.env.STRIPE_SECRET_KEY || "";
  if (!secretKey) {
    return NextResponse.json(
      { error: "stripe is not configured yet — contact support" },
      { status: 503 },
    );
  }

  const fresh = await findUserById(auth.user.id);
  if (!fresh) {
    return NextResponse.json({ error: "user not found" }, { status: 404 });
  }
  if (!fresh.stripe_customer) {
    return NextResponse.json(
      { error: "no subscription yet — start one from the upgrade button" },
      { status: 400 },
    );
  }

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  const returnPath =
    parsed.success && parsed.data.return_path && parsed.data.return_path.startsWith("/") && !parsed.data.return_path.startsWith("//")
      ? parsed.data.return_path
      : "/account";

  const stripe = new Stripe(secretKey, {
    apiVersion: "2025-03-31.basil" as Stripe.LatestApiVersion,
  });

  const origin = new URL(req.url).origin;
  let session: Stripe.Response<Stripe.BillingPortal.Session>;
  try {
    session = await stripe.billingPortal.sessions.create({
      customer: fresh.stripe_customer,
      return_url: `${origin}${returnPath}`,
    });
  } catch {
    return NextResponse.json({ error: "billing portal unavailable" }, { status: 503 });
  }

  if (!session.url) {
    return NextResponse.json({ error: "billing portal unavailable" }, { status: 503 });
  }

  try {
    await logAdminAction({
      actor_user_id: fresh.id,
      target_user_id: fresh.id,
      action: "billing.portal_opened",
      payload: { session_id: session.id },
    });
  } catch {
    // Audit is best-effort; Stripe already returned a redirect URL.
  }

  return NextResponse.json({ url: session.url });
}
