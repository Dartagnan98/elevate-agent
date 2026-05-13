import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import {
  findUserByStripeCustomer,
  revokeLicensesForUser,
  updateUserSubscription,
} from "@/lib/store";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const secretKey = process.env.STRIPE_SECRET_KEY || "";
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET || "";
  if (!secretKey || !webhookSecret) {
    return NextResponse.json({ error: "stripe webhook is not configured" }, { status: 503 });
  }

  const stripe = new Stripe(secretKey, {
    apiVersion: "2025-03-31.basil" as Stripe.LatestApiVersion,
  });
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
  const user = findUserByStripeCustomer(sub.customer as string);
  if (!user) return;

  const tier = sub.items.data[0]?.price.id === process.env.STRIPE_PRICE_BUILDER_MONTHLY ? "builder" : "pro";

  updateUserSubscription(user.id, {
    status: ["active", "trialing"].includes(sub.status)
      ? (sub.status as "active" | "trialing")
      : sub.status === "past_due"
        ? "past_due"
        : "canceled",
    tier,
    current_period_end: (sub as unknown as { current_period_end?: number }).current_period_end
      ? new Date((sub as unknown as { current_period_end: number }).current_period_end * 1000).toISOString()
      : null,
  });
}

async function revokeLicenses(stripeCustomerId: string) {
  const user = findUserByStripeCustomer(stripeCustomerId);
  if (!user) return;

  revokeLicensesForUser(user.id);
}
