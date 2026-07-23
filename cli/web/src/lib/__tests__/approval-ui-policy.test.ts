import { describe, expect, it } from "vitest";

import type { StatusResponse } from "@/lib/api";
import {
  approvalChoicesForPolicy,
  approvalSurfacePolicyForStatus,
  filterApprovalSettingsSchema,
  permissionModeAvailable,
} from "@/lib/approval-ui-policy";

function statusFor(channel?: string): StatusResponse {
  return {
    beta_runtime: channel
      ? ({ releaseChannel: channel } as StatusResponse["beta_runtime"])
      : undefined,
  } as StatusResponse;
}

describe("approval UI policy", () => {
  it("fails closed until runtime status is known", () => {
    expect(approvalSurfacePolicyForStatus(undefined)).toBe("restricted");
    expect(approvalSurfacePolicyForStatus(null)).toBe("restricted");
  });

  it("restricts only the exact lowercase Realtor Beta receipt", () => {
    expect(approvalSurfacePolicyForStatus(statusFor("beta"))).toBe("restricted");
    expect(approvalSurfacePolicyForStatus(statusFor())).toBe("standard");
    expect(approvalSurfacePolicyForStatus(statusFor("Beta"))).toBe("standard");
  });

  it("offers every explicit exact-Beta mode and one-request decisions", () => {
    expect(permissionModeAvailable("default", "restricted")).toBe(true);
    expect(permissionModeAvailable("plan", "restricted")).toBe(true);
    expect(permissionModeAvailable("acceptEdits", "restricted")).toBe(true);
    expect(permissionModeAvailable("bypassPermissions", "restricted")).toBe(true);
    expect(approvalChoicesForPolicy("restricted")).toEqual(["once", "deny"]);
  });

  it("leaves the Stable controls unchanged", () => {
    expect(permissionModeAvailable("acceptEdits", "standard")).toBe(true);
    expect(permissionModeAvailable("bypassPermissions", "standard")).toBe(true);
    expect(approvalChoicesForPolicy("standard")).toEqual([
      "once",
      "session",
      "always",
      "deny",
    ]);
  });

  it("removes approval persistence and bypass settings only while restricted", () => {
    const schema = {
      "approvals.mode": { options: ["ask", "yolo", "deny"] },
      "approvals.permission_mode": {
        options: ["default", "plan", "bypassPermissions"],
      },
      command_allowlist: { type: "list" },
      "display.theme": { type: "select" },
    };

    expect(filterApprovalSettingsSchema(schema, "restricted")).toEqual({
      "display.theme": { type: "select" },
    });
    expect(filterApprovalSettingsSchema(schema, "standard")).toBe(schema);
  });
});
