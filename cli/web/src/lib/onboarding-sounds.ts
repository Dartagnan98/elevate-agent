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
 * Rising sweep — used while onboarding is loading / seeding and on
 * welcome -> wizard transitions. Pitch sweeps from ~80 Hz up to ~1600 Hz
 * over `durationSeconds`, with a filtered noise layer riding underneath
 * for build-up texture. Returns a `stop()` handle so the caller can cut
 * the riser short (fading it out) when loading actually completes.
 */
export function playOnboardingRiser(
  durationSeconds = 2.4,
): { stop: () => void } {
  const ac = getCtx();
  if (!ac) return { stop: () => {} };
  const now = ac.currentTime;
  const end = now + durationSeconds;

  const master = ac.createGain();
  master.gain.setValueAtTime(0, now);
  master.gain.linearRampToValueAtTime(0.05, now + 0.35);
  master.gain.linearRampToValueAtTime(0.07, end - 0.15);
  master.gain.exponentialRampToValueAtTime(0.0001, end);
  master.connect(ac.destination);

  const osc = ac.createOscillator();
  osc.type = "sawtooth";
  osc.frequency.setValueAtTime(80, now);
  osc.frequency.exponentialRampToValueAtTime(1600, end);

  const filter = ac.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(220, now);
  filter.frequency.exponentialRampToValueAtTime(4000, end);
  filter.Q.value = 6;

  const oscGain = ac.createGain();
  oscGain.gain.value = 0.4;
  osc.connect(filter).connect(oscGain).connect(master);
  osc.start(now);
  osc.stop(end + 0.05);

  const noiseBufferSize = Math.floor(ac.sampleRate * durationSeconds);
  const noiseBuffer = ac.createBuffer(1, noiseBufferSize, ac.sampleRate);
  const noiseData = noiseBuffer.getChannelData(0);
  for (let i = 0; i < noiseBufferSize; i++) {
    noiseData[i] = Math.random() * 2 - 1;
  }
  const noise = ac.createBufferSource();
  noise.buffer = noiseBuffer;
  const noiseFilter = ac.createBiquadFilter();
  noiseFilter.type = "bandpass";
  noiseFilter.frequency.setValueAtTime(400, now);
  noiseFilter.frequency.exponentialRampToValueAtTime(6000, end);
  noiseFilter.Q.value = 0.7;
  const noiseGain = ac.createGain();
  noiseGain.gain.setValueAtTime(0, now);
  noiseGain.gain.linearRampToValueAtTime(0.18, now + 0.4);
  noiseGain.gain.linearRampToValueAtTime(0.32, end - 0.1);
  noiseGain.gain.exponentialRampToValueAtTime(0.0001, end);
  noise.connect(noiseFilter).connect(noiseGain).connect(master);
  noise.start(now);
  noise.stop(end + 0.05);

  let stopped = false;
  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      const stopAt = ac.currentTime;
      try {
        master.gain.cancelScheduledValues(stopAt);
        master.gain.setValueAtTime(master.gain.value, stopAt);
        master.gain.exponentialRampToValueAtTime(0.0001, stopAt + 0.25);
        osc.stop(stopAt + 0.3);
        noise.stop(stopAt + 0.3);
      } catch {
        // already stopped
      }
    },
  };
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
