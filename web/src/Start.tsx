import { FileText, Upload, X } from "lucide-react";
import { useEffect, useId, useState, type DragEvent, type FormEvent } from "react";
import { api, type Case, type PatientType, type Sample } from "./api";
import { money } from "./format";
import { button, buttonQuiet, ErrorBox, input, linkish, ScreenTitle, Working } from "./ui";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";
const SAMPLE_TEXT: Record<string, { name: string; line: string }> = {
  maya: { name: "Maya", line: "Paying herself. A colonoscopy bill with several problems." },
  dev: { name: "Dev", line: "Insured. The hospital asks for more than his insurer says he owes." },
  clean: { name: "A clean bill", line: "Paying herself. Nothing wrong, to show what that looks like." },
};

export function Start({ onCase }: { onCase: (c: Case) => void }) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [patientType, setPatientType] = useState<PatientType>("self_pay");
  const [gfe, setGfe] = useState("");
  const [bill, setBill] = useState<File | null>(null);
  const [eob, setEob] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.samples().then(setSamples).catch(() => setSamples([]));
  }, []);

  async function run(work: () => Promise<Case>) {
    setBusy(true);
    setError(null);
    try {
      onCase(await work());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!bill) {
      setError("Add your itemized bill first: a PDF or a photo.");
      return;
    }
    const form = new FormData();
    form.set("patient_type", patientType);
    if (patientType === "self_pay" && gfe.trim()) form.set("gfe_total", gfe.replace(/[$,\s]/g, ""));
    form.set("bill", bill);
    if (patientType === "insured" && eob) form.set("eob", eob);
    void run(() => api.createCase(form));
  }

  if (busy)
    return (
      <Working
        label="Reading your bill… usually 30 to 60 seconds"
        detail="We copy every line, date, code and charge, then tidy the codes. Next you check what we read."
        seconds={45}
      />
    );

  return (
    <div className="space-y-10">
      <header className="space-y-3">
        <ScreenTitle>Is your hospital bill right?</ScreenTitle>
        <p className="text-lg text-ink-soft">
          ClaimGuard checks every line of an itemized hospital bill against public Medicare data, explains anything
          that looks wrong, and drafts the letters to fix it.
        </p>
      </header>

      {error && <ErrorBox message={error} />}

      <form onSubmit={submit} className="space-y-8" aria-labelledby="own-title" noValidate>
        <h2 id="own-title" className="sr-only">Check your own bill</h2>

        <fieldset className="space-y-3">
          <legend className="mb-2 text-lg font-semibold">Are you paying yourself or using insurance?</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["self_pay", "I'm paying myself", "No insurance for this visit, or you chose to pay cash."],
                ["insured", "I'm using insurance", "You'll add your insurer's Explanation of Benefits (EOB): the statement saying what you owe."],
              ] as const
            ).map(([value, label, hint]) => (
              <label
                key={value}
                className={`flex min-h-11 cursor-pointer gap-3 rounded-lg border p-4 ${
                  patientType === value ? "border-accent bg-accent-wash" : "border-rule bg-sheet"
                }`}
              >
                <input
                  type="radio" name="patient_type" value={value} checked={patientType === value}
                  onChange={() => setPatientType(value)} className="mt-1 size-5 shrink-0 accent-accent"
                />
                <span>
                  <span className="block font-semibold">{label}</span>
                  <span className="block text-ink-soft">{hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {patientType === "self_pay" && (
          <div className="space-y-2">
            <label htmlFor="gfe" className="block text-lg font-semibold">
              Your Good Faith Estimate total <span className="font-normal text-ink-soft">(if you have one)</span>
            </label>
            <details className="text-ink-soft">
              <summary className={`inline-flex min-h-11 items-center ${linkish}`}>What's a Good Faith Estimate?</summary>
              <p className="mt-1 max-w-prose">
                When you book care without insurance, the provider must give you a written estimate of the cost. If
                the bill comes in $400 or more above it, you can start a federal billing dispute within 120 days.
              </p>
            </details>
            <div className="relative max-w-xs">
              <span aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-soft">$</span>
              <input id="gfe" inputMode="decimal" autoComplete="off" value={gfe}
                     onChange={(e) => setGfe(e.target.value)} className={`${input} num pl-7`} placeholder="3,400.00" />
            </div>
          </div>
        )}

        <FileDrop id="bill" label="Your itemized hospital bill (required)" hint="PDF or a photo, up to 10 MB" file={bill} onFile={setBill} />
        {patientType === "insured" && (
          <FileDrop id="eob" label="Your insurer's EOB (optional)" hint="Explanation of Benefits, from your insurer. PDF or a photo. Without it we skip the EOB comparison." file={eob} onFile={setEob} />
        )}

        <div className="space-y-3">
          <button type="submit" className={button}>Read my bill</button>
          <p className="text-sm text-ink-soft">
            Please use the samples, or a bill you're comfortable sharing. Files are deleted after they're read.
          </p>
        </div>
      </form>

      <section aria-labelledby="samples-title" className="space-y-4 border-t border-rule pt-8">
        <div>
          <h2 id="samples-title" className="text-lg font-semibold">Or try a sample bill</h2>
          <p className="text-ink-soft">Made-up bills marked SAMPLE. Nothing to upload.</p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-3">
          {samples.map((s) => {
            const text = SAMPLE_TEXT[s.id] ?? { name: s.title, line: "" };
            return (
              <li key={s.id}>
                <button
                  type="button"
                  className={`${buttonQuiet} h-full w-full flex-col items-start justify-start text-left`}
                  onClick={() => run(() => api.createSample(s.id))}
                >
                  <span>Try {text.name}</span>
                  <span className="font-normal text-ink-soft">{text.line}</span>
                  {s.gfe_total && <span className="num font-normal text-ink-soft">Estimate {money(s.gfe_total)}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}

function FileDrop({ id, label, hint, file, onFile }: {
  id: string; label: string; hint: string; file: File | null; onFile: (f: File | null) => void;
}) {
  const [over, setOver] = useState(false);
  const hintId = useId();

  function drop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setOver(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  }

  return (
    <div className="space-y-2">
      <p className="text-lg font-semibold" id={`${id}-label`}>{label}</p>
      {file ? (
        <div className="flex items-center gap-3 rounded-lg border border-rule bg-sheet p-4">
          <FileText aria-hidden className="size-5 shrink-0 text-ink-soft" />
          <span className="min-w-0 flex-1 truncate">{file.name}</span>
          <button type="button" onClick={() => onFile(null)} className={`${buttonQuiet} px-3`} aria-label={`Remove ${file.name}`}>
            <X aria-hidden className="size-4" /> Remove
          </button>
        </div>
      ) : (
        <label
          htmlFor={id}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={drop}
          className={`flex min-h-28 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed p-5 text-center ${
            over ? "border-accent bg-accent-wash" : "border-rule-strong bg-sheet hover:bg-paper"
          } focus-within:outline focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-accent`}
        >
          <Upload aria-hidden className="size-6 text-accent" />
          <span className="font-semibold text-accent">Tap to choose a file</span>
          <span className="text-ink-soft" id={hintId}>or drag it here. {hint}</span>
          <input id={id} type="file" accept={ACCEPT} className="sr-only" aria-labelledby={`${id}-label`} aria-describedby={hintId}
                 onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        </label>
      )}
    </div>
  );
}
