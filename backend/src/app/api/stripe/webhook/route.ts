import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { supabase } from "@/lib/supabase";

export const runtime = "nodejs";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY || "", {
  apiVersion: "2025-03-31.basil" as Stripe.LatestApiVersion,
});

const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET || "";

export async function POST(req: NextRequest) {
  const sig = req.headers.get("stripe-signature");
  if (!sig) return NextResponse.json({ error: "missing signature" }, { status: 400 });

  const raw = await req.text();
  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(raw, sig, webhookSecret);
  } catch (err: any) {
    return NextResponse.json({ error: `signature verification failed: ${err.message}` }, { status: 400 });
  }

  switch (event.type) {
    case "customer.subscription.created":
    case "customer.subscription.updated": {
      const sub = event.data.object as Stripe.Subscription;
      await upsertSubscription(sub);
      break;
    }
    case "customer.subscription.deleted": {
      const sub = event.data.object as Stripe.Subscription;
      await upsertSubscription(sub);
      await revokeLicenses(sub.customer as string);
      break;
    }
    default:
      break;
  }

  return NextResponse.json({ received: true });
}

async function upsertSubscription(sub: Stripe.Subscription) {
  const { data: user } = await supabase
    .from("users")
    .select("id")
    .eq("stripe_customer", sub.customer as string)
    .maybeSingle();
  if (!user) return;

  const tier = sub.items.data[0]?.price.id === process.env.STRIPE_PRICE_BUILDER_MONTHLY ? "builder" : "pro";

  await supabase.from("subscriptions").upsert(
    {
      user_id: user.id,
      stripe_sub_id: sub.id,
      status: sub.status,
      tier,
      current_period_end: (sub as unknown as { current_period_end?: number }).current_period_end
        ? new Date((sub as unknown as { current_period_end: number }).current_period_end * 1000).toISOString()
        : null,
      cancel_at_period_end: sub.cancel_at_period_end,
    },
    { onConflict: "stripe_sub_id" },
  );
}

async function revokeLicenses(stripeCustomerId: string) {
  const { data: user } = await supabase
    .from("users")
    .select("id")
    .eq("stripe_customer", stripeCustomerId)
    .maybeSingle();
  if (!user) return;

  await supabase.from("licenses").update({ revoked: true }).eq("user_id", user.id);
}
