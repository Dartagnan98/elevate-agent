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
  const src = `${assetBasePath}/${sequence}/ozzie-${sequence}-${size}.webp`;

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
