function normalizeOrigin(value) {
  if (!value) return "";
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

function requestPermissionOrigin(details = {}) {
  return details.securityOrigin || details.requestingUrl || "";
}

function isAllowedAudioPermission(permission, requestOrigin, details = {}, dashboardOrigin = "") {
  if (normalizeOrigin(requestOrigin) !== normalizeOrigin(dashboardOrigin)) {
    return false;
  }
  if (permission === "audioCapture") {
    return true;
  }
  if (permission !== "media") {
    return false;
  }

  const mediaTypes = Array.isArray(details.mediaTypes) ? details.mediaTypes : null;
  if (mediaTypes) {
    return mediaTypes.length > 0 && mediaTypes.every((type) => type === "audio");
  }

  const mediaType = typeof details.mediaType === "string" ? details.mediaType : "";
  return !mediaType || mediaType === "audio" || mediaType === "unknown";
}

module.exports = {
  isAllowedAudioPermission,
  requestPermissionOrigin,
};
