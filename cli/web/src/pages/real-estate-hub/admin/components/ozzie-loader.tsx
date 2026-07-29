import "./ozzie-loader.css";
import type { CSSProperties } from "react";

type OzzieSequence = "waiting" | "thinking";
type OzzieSize = 64 | 96 | 128 | 160 | 256 | 320;

type OzzieLoaderProps = {
  label?: string;
  sequence?: OzzieSequence;
  size?: OzzieSize;
  showDots?: boolean;
  assetBasePath?: string;
};

export function OzzieLoader({
  label = "AI agent is thinking",
  sequence = "waiting",
  size = 96,
  showDots = true,
  assetBasePath = "/ozzie-loader",
}: OzzieLoaderProps) {
  // Display size is `size`, but always FETCH a high-res variant (>=256) and let
  // CSS downscale it. The small webp variants (64/96/128) are both pixelated and
  // carry a white-square artifact in the top-left corner; the 256 source is clean
  // and sharp. Decoupling asset resolution from display size fixes both.
  const assetSize: OzzieSize = size >= 256 ? size : 256;
  const src = `${assetBasePath}/${sequence}/ozzie-${sequence}-${assetSize}.webp`;

  return (
    <span
      className="ozzie-loader"
      role="status"
      aria-label={label}
      style={{ "--ozzie-size": `${size}px` } as CSSProperties}
    >
      <img className="ozzie-loader__image" src={src} alt="" />
      {showDots ? (
        <span className="ozzie-loader__dots" aria-hidden="true">
          <span className="ozzie-loader__dot" />
          <span className="ozzie-loader__dot" />
          <span className="ozzie-loader__dot" />
          <span className="ozzie-loader__cursor" />
        </span>
      ) : null}
    </span>
  );
}
