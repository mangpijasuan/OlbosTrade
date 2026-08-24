/**
 * Gamified mission row — reward pill, title stack, meta badge, bottom progress.
 * Inspired by mobile earn/task UIs; reused across Alpha Edge and Copilot Queue.
 */
import React from "react";

export interface MissionReward {
  prefix?: string;
  value: string;
  tone?: string;
}

export interface MissionMeta {
  label: string;
  tone?: string;
  icon?: React.ReactNode;
}

export interface MissionProgress {
  value: number;
  tone?: string;
  label?: string;
}

export interface MissionCardProps {
  reward?: MissionReward;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  meta?: MissionMeta;
  progress?: MissionProgress;
  selected?: boolean;
  onClick?: () => void;
  actions?: React.ReactNode;
  className?: string;
  variant?: "default" | "compact";
  as?: "button" | "div";
  disabled?: boolean;
  "aria-label"?: string;
  "aria-pressed"?: boolean;
  children?: React.ReactNode;
}

export default function MissionCard({
  reward,
  title,
  subtitle,
  meta,
  progress,
  selected,
  onClick,
  actions,
  className = "",
  variant = "default",
  as = onClick ? "button" : "div",
  disabled,
  "aria-label": ariaLabel,
  "aria-pressed": ariaPressed,
  children,
}: MissionCardProps) {
  const pct = progress != null ? Math.min(100, Math.max(0, progress.value)) : null;
  const progressTone = progress?.tone ?? "var(--green)";

  const classes = [
    "mission-card",
    variant === "compact" ? "mission-card--compact" : "",
    selected ? "mission-card--selected" : "",
    onClick && as === "button" ? "mission-card--interactive" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const body = (
    <>
      <div className="mission-card__row">
        {reward && (
          <div
            className="mission-card__reward"
            style={reward.tone ? { borderColor: `${reward.tone}88`, color: reward.tone } : undefined}
          >
            {reward.prefix && <span className="mission-card__reward-prefix">{reward.prefix}</span>}
            <span className="mission-card__reward-value">{reward.value}</span>
          </div>
        )}
        <div className="mission-card__content">
          <div className="mission-card__title">{title}</div>
          {subtitle && <div className="mission-card__subtitle">{subtitle}</div>}
        </div>
        {meta && (
          <div
            className="mission-card__meta"
            style={meta.tone ? { borderColor: `${meta.tone}55`, color: meta.tone } : undefined}
          >
            {meta.icon && <span className="mission-card__meta-icon">{meta.icon}</span>}
            <span>{meta.label}</span>
          </div>
        )}
      </div>
      {children}
      {actions && <div className="mission-card__actions">{actions}</div>}
      {pct != null && (
        <div
          className="mission-card__progress"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={progress?.label ?? "Progress"}
        >
          <div className="mission-card__progress-fill" style={{ width: `${pct}%`, background: progressTone }} />
        </div>
      )}
    </>
  );

  if (as === "button") {
    return (
      <button
        type="button"
        className={classes}
        onClick={onClick}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-pressed={ariaPressed}
      >
        {body}
      </button>
    );
  }

  return <div className={classes}>{body}</div>;
}

export function MissionCardSkeleton({ className = "" }: { className?: string }) {
  return (
    <div className={`mission-card mission-card--skeleton ${className}`.trim()} aria-hidden>
      <div className="mission-card__row">
        <div className="mission-card__reward mission-card__shimmer" />
        <div className="mission-card__content" style={{ flex: 1 }}>
          <div className="mission-card__shimmer" style={{ height: 14, width: "40%", marginBottom: 8 }} />
          <div className="mission-card__shimmer" style={{ height: 10, width: "65%" }} />
        </div>
        <div className="mission-card__meta mission-card__shimmer" style={{ width: 48, minHeight: 28 }} />
      </div>
    </div>
  );
}
