"use strict";

const packageJson = require("./package.json");
const { resolveReleaseProfile } = require("./src/release-profile");

module.exports = () => {
  const profile = resolveReleaseProfile(process.env.ELEVATE_RELEASE_CHANNEL);
  const base = structuredClone(packageJson.build);
  return {
    ...base,
    appId: profile.appId,
    productName: profile.productName,
    artifactName: `${profile.artifactPrefix}-\${version}-\${os}-\${arch}.\${ext}`,
    protocols: [{ name: profile.productName, schemes: [profile.protocolScheme] }],
    extraMetadata: {
      ...(base.extraMetadata || {}),
      name: profile.packageName,
      elevateReleaseChannel: profile.channel,
      elevateSourceReceiptId: process.env.ELEVATE_SOURCE_RECEIPT_ID || undefined,
    },
    publish: (base.publish || []).map((entry) => ({ ...entry, channel: profile.channel })),
    dmg: { ...(base.dmg || {}), title: profile.productName },
  };
};
