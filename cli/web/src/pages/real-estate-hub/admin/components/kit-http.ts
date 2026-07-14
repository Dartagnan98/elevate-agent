export async function requireKitResponse(
  response: Response,
  fallback: string,
): Promise<Response> {
  if (response.ok) return response;

  let detail = "";
  if (response.status >= 400 && response.status < 500) {
    try {
      const payload = (await response.clone().json()) as {
        detail?: string | { message?: string };
        message?: string;
      };
      if (typeof payload.detail === "string") detail = payload.detail;
      else if (payload.detail && typeof payload.detail.message === "string") {
        detail = payload.detail.message;
      } else if (typeof payload.message === "string") detail = payload.message;
    } catch {
      try {
        detail = (await response.text()).trim();
      } catch {
        detail = "";
      }
    }
  }

  // Server errors can include exception text and local paths.  A short 4xx
  // setup message helps the realtor recover; implementation details do not.
  if (
    detail.length > 240
    || /(?:traceback|exception|\/Users\/|\/home\/|\\[A-Za-z0-9_.-]+\\)/i.test(detail)
    || /[\r\n]/.test(detail)
  ) {
    detail = "";
  }

  const suffix = detail ? ` ${detail}` : "";
  throw new Error(`${fallback} (${response.status}).${suffix}`.trim());
}

export function kitErrorMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message.trim() : "";
  return message || fallback;
}

export async function runKitRequests(
  requests: Array<{ request: () => Promise<Response>; fallback: string }>,
): Promise<void> {
  for (const item of requests) {
    const response = await item.request();
    await requireKitResponse(response, item.fallback);
  }
}
