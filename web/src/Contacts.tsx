import { Building2, ExternalLink, Phone } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type Case } from "./api";
import { button, buttonQuiet, input, linkish } from "./ui";

const LINK_LABEL = { billing: "Billing page", assistance: "Financial assistance policy" } as const;

/**
 * "Hospital contacts": where to send the letters, found on the web (docs/SPEC.md section 7). It runs once when the
 * results first appear, searches only the hospital's name, and never blocks anything: a failure is just a sentence.
 * The demo toggle looks up a real hospital instead, because the sample bills use an invented one.
 */
export function Contacts({ data, onUpdate }: { data: Case; onUpdate: (c: Case) => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [demo, setDemo] = useState(false);
  const [name, setName] = useState("");
  const started = useRef(false);
  const lookup = data.lookup;

  async function run(hospital?: string) {
    setBusy(true);
    setProblem(null);
    try {
      onUpdate(await api.lookup(data.id, hospital));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (lookup !== null || started.current) return;
    started.current = true;
    void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.id]);

  return (
    <section aria-labelledby="contacts-title" className="space-y-4 rounded-lg border border-rule bg-sheet p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <Building2 aria-hidden className="mt-1 size-5 shrink-0 text-accent" />
        <div className="min-w-0 space-y-1">
          <h2 id="contacts-title" className="text-xl font-bold">Hospital contacts</h2>
          {lookup?.hospital_name && <p className="text-ink-soft">Searched for: {lookup.hospital_name}</p>}
        </div>
      </div>

      <div aria-live="polite">
        {busy ? (
          <p role="status" className="text-lg">
            Looking up the billing office… usually 10–20 seconds. Only the hospital's name is searched.
          </p>
        ) : lookup?.status === "found" ? (
          <div className="space-y-3">
            <p className="font-semibold">{lookup.verify_note}</p>
            <dl className="space-y-2">
              {lookup.phone && (
                <div className="flex items-start gap-2">
                  <Phone aria-hidden className="mt-1 size-4 shrink-0 text-ink-soft" />
                  <div>
                    <dt className="text-sm text-ink-soft">Billing office phone</dt>
                    <dd className="num font-semibold">{lookup.phone}</dd>
                  </div>
                </div>
              )}
              {lookup.address && (
                <div>
                  <dt className="text-sm text-ink-soft">Mailing address (used on your letters)</dt>
                  <dd className="font-semibold">{lookup.address}</dd>
                </div>
              )}
            </dl>
            {lookup.links.length > 0 && (
              <ul className="space-y-1">
                {lookup.links.map((link) => (
                  <li key={link.url}>
                    <span className="text-sm text-ink-soft">{LINK_LABEL[link.kind]}: </span>
                    <a className={`inline-flex min-h-11 items-center gap-1.5 break-all ${linkish}`} href={link.url} target="_blank" rel="noreferrer">
                      {link.title}
                      <ExternalLink aria-hidden className="size-4 shrink-0" />
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : lookup ? (
          <p className="max-w-prose text-lg">{lookup.message}</p>
        ) : problem ? null : (
          <p className="text-ink-soft">Checking for the hospital's billing office.</p>
        )}
        {problem && (
          <p role="alert" className="max-w-prose text-lg">
            We couldn't run the lookup. Your letters are not affected; use the address printed on your statement.{" "}
            <button type="button" className={linkish} onClick={() => void run()}>Try again</button>
          </p>
        )}
      </div>

      <div className="border-t border-rule pt-3">
        <button
          type="button"
          className={`inline-flex min-h-11 items-center ${linkish}`}
          aria-expanded={demo}
          aria-controls="contacts-demo"
          onClick={() => setDemo(!demo)}
        >
          Demo: look up a real hospital
        </button>
        {demo && (
          <form
            id="contacts-demo"
            className="mt-2 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) void run(name.trim());
            }}
          >
            <p className="max-w-prose text-ink-soft">
              The sample bills name an invented hospital. Type a real one to see the lookup work; the letters will be
              addressed to it.
            </p>
            <div>
              <label htmlFor="demo-hospital" className="block font-semibold">Hospital name</label>
              <input
                id="demo-hospital" className={`${input} mt-1 max-w-md`} value={name} maxLength={120}
                autoComplete="off" onChange={(e) => setName(e.target.value)}
              />
            </div>
            <button type="submit" className={busy || !name.trim() ? buttonQuiet : button} disabled={busy || !name.trim()}>
              Look it up
            </button>
          </form>
        )}
      </div>
    </section>
  );
}
