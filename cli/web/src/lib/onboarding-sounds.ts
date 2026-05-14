/**
 * Web Audio sound cues for the admin onboarding flow.
 *
 * No assets — everything is synthesized via the Web Audio API. Sounds are
 * subtle (peak gain <= 0.06) so they don't startle on default volume.
 *
 * Lazy AudioContext: created on first play, reused thereafter. iOS/macOS
 * Safari require an explicit user gesture before the context can produce
 * sound; calling these from a button click handler satisfies that.
 */

let ctx: AudioContext | null = null;
let muted = false;

function getCtx(): AudioContext | null {
  if (muted) return null;
  if (typeof window === "undefined") return null;
  if (!ctx) {
    try {
      const Ctor = (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
      if (!Ctor) return null;
      ctx = new Ctor();
    } catch {
      return null;
    }
  }
  if (ctx.state === "suspended") {
    void ctx.resume().catch(() => {});
  }
  return ctx;
}

export function setOnboardingSoundsMuted(value: boolean) {
  muted = value;
}

/** Soft ambient swell — used on welcome -> wizard and wizard -> seeding. */
export function playOnboardingSwell() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;

  const master = ac.createGain();
  master.gain.setValueAtTime(0, now);
  master.gain.linearRampToValueAtTime(0.06, now + 0.18);
  master.gain.exponentialRampToValueAtTime(0.0001, now + 1.4);
  master.connect(ac.destination);

  const fundamentals = [196, 261.63, 392];
  fundamentals.forEach((freq, idx) => {
    const osc = ac.createOscillator();
    osc.type = idx === 2 ? "triangle" : "sine";
    osc.frequency.setValueAtTime(freq, now);

    const gain = ac.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(idx === 2 ? 0.35 : 0.5, now + 0.2 + idx * 0.05);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.3);

    osc.connect(gain).connect(master);
    osc.start(now);
    osc.stop(now + 1.45);
  });
}

/** Tiny tick — used on Continue button. */
export function playOnboardingClick() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;

  const osc = ac.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(880, now);
  osc.frequency.exponentialRampToValueAtTime(660, now + 0.08);

  const gain = ac.createGain();
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.04, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.1);

  osc.connect(gain).connect(ac.destination);
  osc.start(now);
  osc.stop(now + 0.12);
}

/**
 * Cinematic whoosh — plays `/sounds/onboarding-whoosh.wav` (Foundation
 * Ocular Whooshes - "Dark Air"). Fired on Start onboarding / Continue
 * transitions to give the welcome -> wizard motion a cinematic edge
 * over the synthesized swell alone.
 */
export function playOnboardingWhoosh() {
  if (muted || typeof window === "undefined") return;
  try {
    const audio = new Audio("/sounds/onboarding-whoosh.wav");
    audio.volume = 0.55;
    void audio.play().catch(() => {});
  } catch {
    // audio unavailable - silent fail
  }
}

/** Two-note chime — used when seeding completes and admin is ready. */
export function playOnboardingChime() {
  const ac = getCtx();
  if (!ac) return;
  const now = ac.currentTime;

  const notes: Array<[number, number]> = [
    [523.25, 0],     // C5
    [659.25, 0.16],  // E5
    [783.99, 0.32],  // G5
  ];

  notes.forEach(([freq, offset]) => {
    const osc = ac.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(freq, now + offset);

    const gain = ac.createGain();
    gain.gain.setValueAtTime(0, now + offset);
    gain.gain.linearRampToValueAtTime(0.05, now + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.5);

    osc.connect(gain).connect(ac.destination);
    osc.start(now + offset);
    osc.stop(now + offset + 0.55);
  });
}
