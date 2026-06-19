import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { z } from "zod";
import { requireAccess } from "@/lib/auth-guard";
import { findUserById, logAdminAction, updateUserSubscription } from "@/lib/store";

export const runtime = "nodejs";

const Body = z.object({
  plan: z.enum(["pro", "builder"]).optional(),
  // Where Stripe redirects after success / cancel — must be a same-origin path.
  success_path: z.string().optional(),
  cancel_path: z.string().optional(),
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

  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  const plan = parsed.data.plan || "pro";
  const priceId =
    plan === "builder"
      ? process.env.STRIPE_PRICE_BUILDER_MONTHLY
      : process.env.STRIPE_PRICE_PRO_MONTHLY;
  if (!priceId) {
    return NextResponse.json(
      { error: `no price configured for plan ${plan}` },
      { status: 503 },
    );
  }

  const fresh = await findUserById(auth.user.id);
  if (!fresh) {
    return NextResponse.json({ error: "user not found" }, { status: 404 });
  }

  const stripe = new Stripe(secretKey, {
    apiVersion: "2025-03-31.basil" as Stripe.LatestApiVersion,
  });

  // Ensure we have a stripe Customer attached to the user so the portal works
  // for return visits and the webhook can match by customer id.
  let stripeCustomerId = fresh.stripe_customer;
  let session: Stripe.Response<Stripe.Checkout.Session>;
  try {
    if (!stripeCustomerId) {
      const customer = await stripe.customers.create({
        email: fresh.email,
        metadata: { elevate_user_id: fresh.id },
      });
      stripeCustomerId = customer.id;
      await updateUserSubscription(fresh.id, { stripe_customer: stripeCustomerId });
    }

    const origin = new URL(req.url).origin;
    const safePath = (p?: string, fallback = "/account") =>
      p && p.startsWith("/") && !p.startsWith("//") ? p : fallback;

    session = await stripe.checkout.sessions.create({
      mode: "subscription",
      customer: stripeCustomerId,
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${origin}${safePath(parsed.data.success_path, "/account")}?upgrade=success`,
      cancel_url: `${origin}${safePath(parsed.data.cancel_path, "/account")}?upgrade=cancel`,
      client_reference_id: fresh.id,
      metadata: { elevate_user_id: fresh.id, plan },
      allow_promotion_codes: true,
    });
  } catch {
    return NextResponse.json({ error: "checkout unavailable" }, { status: 503 });
  }

  if (!session.url) {
    return NextResponse.json({ error: "checkout unavailable" }, { status: 503 });
  }

  try {
    await logAdminAction({
      actor_user_id: fresh.id,
      target_user_id: fresh.id,
      action: "billing.checkout_started",
      payload: { plan, session_id: session.id },
    });
  } catch {
    // Audit is best-effort; Stripe already returned a redirect URL.
  }

  return NextResponse.json({ url: session.url });
}
