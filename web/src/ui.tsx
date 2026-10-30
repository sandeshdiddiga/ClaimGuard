import { CircleAlert, CircleHelp, Info } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Level } from "./api";
import { LEVEL_WORD } from "./copy";

export const STEPS = ["Your bill", "Check the lines", "What we found", "Send letters"] as const;

/** Four steps as a simple line. The current one is named for screen readers with aria-current. */
export function ProgressLine({ current }: { current: number }) {
  return (
    <nav aria-label="Progress">
      <ol className="flex gap-1.5 sm:gap-3">
        {STEPS.map((label, i) => {
          const state = i < current ? "done" : i === current ? "current" : "todo";
          return (
            <li key={label} className="min-w-0 flex-1" aria-current={state === "current" ? "step" : undefined}>
              <span
                aria-hidden
                className={`block h-1 rounded-full ${state === "todo" ? "bg-rule" : "bg-accent"}`}
              />
              <span
                className={`mt-1.5 block text-[0.8125rem] leading-tight sm:text-sm ${
                  state === "current" ? "font-semibold text-ink" : "text-ink-soft"
                }`}
              >
                <span className="sr-only">{`Step ${i + 1} of ${STEPS.length}: `}</span>
                {label}
                {state === "done" && <span className="sr-only"> (done)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** What is happening and roughly how long it takes: a quiet line that fills over the usual time, never a spinner. */
export function Working({ label, detail, seconds }: { label: string; detail?: string; seconds: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed((Date.now() - started) / 1000), 250);
    return () => window.clearInterval(timer);
  }, []);
  const share = Math.min(0.92, elapsed / seconds); // never claims to be finished
  return (
    <div role="status" aria-live="polite" className="rounded-lg border border-rule bg-sheet p-5">
      <p className="text-lg font-semibold">{label}</p>
      {detail && <p className="mt-1 text-ink-soft">{detail}</p>}
      <div aria-hidden className="mt-4 h-1.5 overflow-hidden rounded-full bg-rule">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${Math.round(share * 100)}%`, transition: "width 250ms linear" }}
        />
      </div>
      <p aria-hidden className="num mt-2 text-sm text-ink-soft">{Math.floor(elapsed)} s</p>
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <p role="alert" className="flex gap-2 rounded-lg border border-err-line bg-err-bg p-4 text-err">
      <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
      <span>{message}</span>
    </p>
  );
}

/** A non-blocking note: something was skipped, nothing is wrong with the rest. */
export function Notice({ message }: { message: string }) {
  return (
    <p role="status" className="flex gap-2 rounded-lg border border-rule-strong bg-sheet p-4 text-ink">
      <Info aria-hidden className="mt-0.5 size-5 shrink-0 text-ink-soft" />
      <span><strong>Note:</strong> {message}</span>
    </p>
  );
}

/** A heading that takes focus when its screen appears, so keyboard and screen-reader users land on it. */
export function ScreenTitle({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <h1 ref={ref} tabIndex={-1} className={`text-[1.75rem] font-bold leading-tight tracking-tight outline-none sm:text-3xl ${className}`}>
      {children}
    </h1>
  );
}

const LEVEL_STYLE: Record<Level, { box: string; text: string; Icon: typeof CircleAlert }> = {
  red: { box: "border-err-line bg-err-bg", text: "text-err", Icon: CircleAlert },
  amber: { box: "border-ask-line bg-ask-bg", text: "text-ask", Icon: CircleHelp },
  grey: { box: "border-ctx-line bg-ctx-bg", text: "text-ctx", Icon: Info },
};

export function levelBox(level: Level): string {
  return LEVEL_STYLE[level].box;
}

/** A status is never colour alone: always the word and its icon too. */
export function LevelTag({ level }: { level: Level }) {
  const { text, Icon } = LEVEL_STYLE[level];
  return (
    <span className={`inline-flex items-center gap-1.5 font-semibold ${text}`}>
      <Icon aria-hidden className="size-[1.125rem] shrink-0" strokeWidth={2.25} />
      {LEVEL_WORD[level]}
    </span>
  );
}

const press = "transition-[background-color,transform] duration-150 ease-out active:scale-[0.98]";
export const button =
  `inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-accent px-5 py-2.5 font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60 ${press}`;
export const buttonQuiet =
  `inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-rule-strong bg-sheet px-4 py-2.5 font-semibold text-ink hover:bg-paper disabled:cursor-not-allowed disabled:opacity-60 ${press}`;
export const linkish = "font-semibold text-accent underline decoration-1 underline-offset-[3px] hover:text-accent-strong";
export const input =
  "block min-h-11 w-full rounded-md border border-rule-strong bg-sheet px-3 py-2 text-base text-ink placeholder:text-ink-soft";
