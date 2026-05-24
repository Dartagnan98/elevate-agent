import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import {
  findUserById,
  findUserByStripeCustomer,
  logAdminAction,
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
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;
      // Pin stripe_customer onto the user as soon as checkout completes —
      // the subscription event arrives shortly after and the join works
      // because they share the same customer id.
      const userId = (session.client_reference_id ||
        (session.metadata?.elevate_user_id as string | undefined)) as string | null;
      if (userId && session.customer) {
        const fresh = await findUserById(userId);
        if (fresh && !fresh.stripe_customer) {
          await updateUserSubscription(userId, {
            stripe_customer: session.customer as string,
          });
        }
        await logAdminAction({
          actor_user_id: userId,
          target_user_id: userId,
          action: "billing.checkout_completed",
          payload: { session_id: session.id, customer: session.customer },
        });
      }
      break;
    }
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
  const user = await findUserByStripeCustomer(sub.customer as string);
  if (!user) return;

  const tier = sub.items.data[0]?.price.id === process.env.STRIPE_PRICE_BUILDER_MONTHLY ? "builder" : "pro";

  await updateUserSubscription(user.id, {
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
  const user = await findUserByStripeCustomer(stripeCustomerId);
  if (!user) return;

  await revokeLicensesForUser(user.id);
}
