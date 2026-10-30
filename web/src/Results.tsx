import { ArrowRight, ChevronDown, CircleCheck, CircleMinus } from "lucide-react";
import type { Case, EvidenceLine, Finding, Line } from "./api";
import { advice, CHECK_TITLE, DATA_LABEL, MODEL_NAME } from "./copy";
import { longDate, money } from "./format";
import { Contacts } from "./Contacts";
import { button, buttonQuiet, LevelTag, levelBox, linkish, Notice, ScreenTitle } from "./ui";

const ORDER = { red: 0, amber: 1, grey: 2 } as const;

/** An insured patient's billing-review item is shown as worth asking about: it adds nothing to what they owe. */
const shown = (f: Finding): Finding["level"] => (f.billing_review ? "amber" : f.level);

export function Results({ data, onLetters, onRestart, onUpdate }: { data: Case; onLetters: () => void; onRestart: () => void; onUpdate: (c: Case) => void }) {
  const results = data.results!;
  const findings = [...results.findings].sort((a, b) => ORDER[shown(a)] - ORDER[shown(b)]);
  const account = findings.filter((f) => f.line_numbers.length === 0);
  // Worth asking about: amber notes, and an insured patient's billing-review lines (red, but they add nothing).
  const asking = findings.filter((f) => f.level === "amber" || f.billing_review).length;
  // Each finding sits beside the first line it concerns; other lines it covers point back to it.
  const notesFor = (n: number) => findings.filter((f) => f.line_numbers[0] === n);
  const pointersFor = (n: number) => findings.filter((f) => f.line_numbers.indexOf(n) > 0);
  const needsLetters = findings.some((f) => (f.level === "red" || f.level === "amber") && !f.billing_review);

  return (
    <div className="space-y-12">
      <Summary data={data} asking={asking} />

      {account.length > 0 && (
        <section aria-labelledby="account-title" className="space-y-4">
          <h2 id="account-title" className="text-xl font-bold">About the whole bill</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {account.map((f, i) => <FindingNote key={`${f.check}${i}`} finding={f} />)}
          </div>
        </section>
      )}

      <section aria-labelledby="bill-title" className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="bill-title" className="text-xl font-bold">Your bill, line by line</h2>
          <p className="num text-ink-soft">
            {data.lines.length} lines · {money(results.total_charges)} in charges
          </p>
        </div>
        <p className="max-w-prose text-ink-soft">
          Notes sit beside the line they're about. <LegendInline />
        </p>

        <div aria-hidden className="hidden border-b border-rule-strong pb-2 text-sm font-semibold text-ink-soft lg:grid lg:grid-cols-[minmax(0,1fr)_25rem] lg:gap-8">
          <div className="grid grid-cols-[2.25rem_6rem_minmax(0,1fr)_3.5rem_6.5rem] gap-3">
            <span>Line</span><span>Code</span><span>Description</span><span className="text-right">Units</span><span className="text-right">Charge</span>
          </div>
          <span>Our notes</span>
        </div>

        <ol className="space-y-4 lg:space-y-0 lg:divide-y lg:divide-rule">
          {data.lines.map((line, i) => (
            <BillLine key={i} number={i + 1} line={line} notes={notesFor(i + 1)} pointers={pointersFor(i + 1)} />
          ))}
        </ol>
      </section>

      <Contacts data={data} onUpdate={onUpdate} />

      <section aria-labelledby="next-title" className="space-y-3 rounded-lg border border-rule bg-sheet p-5 sm:p-6">
        <h2 id="next-title" className="text-xl font-bold">Next: send letters</h2>
        {needsLetters ? (
          <>
            <p className="max-w-prose text-ink-soft">
              We've drafted letters from these findings. You read them, fill in your details and send them yourself.
            </p>
            <button type="button" className={button} onClick={onLetters}>
              See my letters <ArrowRight aria-hidden className="size-4" />
            </button>
          </>
        ) : (
          <p className="max-w-prose text-ink-soft">
            Nothing on this bill needs a letter. You can still call the billing office with any question.
          </p>
        )}
      </section>

      <button type="button" className={buttonQuiet} onClick={onRestart}>Check another bill</button>
    </div>
  );
}

function Summary({ data, asking }: { data: Case; asking: number }) {
  const r = data.results!;
  const count = r.likely_error_count;
  const over = r.gfe_overage !== null && !r.gfe_overage.startsWith("-") && r.gfe_overage !== "0.00" ? r.gfe_overage : null;
  const disputable = over !== null && r.deadline !== null;

  return (
    <header className="space-y-5">
      <ScreenTitle className="sr-only">What we found</ScreenTitle>
      {data.facility_name && <p className="text-ink-soft">{data.facility_name} · itemized bill{data.bill_date ? ` dated ${longDate(data.bill_date)}` : ""}</p>}
      <p className="max-w-4xl font-serif text-[1.75rem] font-semibold leading-snug sm:text-[2.125rem]">
        {count === 0 ? (
          <>We found no likely errors on this bill.</>
        ) : (
          <>
            We found {count} likely {count === 1 ? "error" : "errors"} totaling{" "}
            <span className="num whitespace-nowrap">{money(r.dollars_at_stake)}</span>.
          </>
        )}{" "}
        {over && disputable && (
          <>Your bill is also <span className="num whitespace-nowrap">{money(over)}</span> over your estimate.</>
        )}
      </p>
      {over && !disputable && (
        <p className="max-w-prose text-lg">
          Your bill is <span className="num font-semibold">{money(over)}</span> over your estimate. That's under the
          $400 needed to start a federal billing dispute.
        </p>
      )}
      {data.eob_note && <Notice message={data.eob_note} />}
      <dl className="flex flex-wrap gap-x-8 gap-y-3 border-y border-rule py-4">
        {r.deadline && (
          <div>
            <dt className="text-sm text-ink-soft">Dispute deadline</dt>
            <dd className="text-lg font-semibold">{longDate(r.deadline)}</dd>
          </div>
        )}
        <div>
          <dt className="text-sm text-ink-soft">Likely errors</dt>
          <dd className="num text-lg font-semibold">{money(r.dollars_at_stake)}</dd>
        </div>
        {over && (
          <div>
            <dt className="text-sm text-ink-soft">Over your estimate (shown separately)</dt>
            <dd className="num text-lg font-semibold">{money(over)}</dd>
          </div>
        )}
        <div>
          <dt className="text-sm text-ink-soft">Worth asking about</dt>
          <dd className="num text-lg font-semibold">{asking} {asking === 1 ? "line" : "lines"}</dd>
        </div>
      </dl>
    </header>
  );
}

function LegendInline() {
  return (
    <span>
      <strong className="text-err">Likely error</strong> means a rule says it's wrong;{" "}
      <strong className="text-ask">worth asking about</strong> means it needs an explanation;{" "}
      <strong className="text-ctx">for context</strong> is background, never counted.
    </span>
  );
}

function BillLine({ number, line, notes, pointers }: { number: number; line: Line; notes: Finding[]; pointers: Finding[] }) {
  const notChecked = line.code_class === "cpt_shaped";
  const strongest = notes.concat(pointers).reduce<Finding["level"] | null>(
    (best, f) => (best === null || ORDER[shown(f)] < ORDER[best] ? shown(f) : best), null,
  );
  const edge = strongest === "red" ? "border-l-err" : strongest === "amber" ? "border-l-ask" : "border-l-transparent";

  return (
    <li id={`line-${number}`} className="scroll-mt-6 rounded-lg border border-rule bg-sheet lg:grid lg:grid-cols-[minmax(0,1fr)_25rem] lg:gap-8 lg:rounded-none lg:border-0 lg:bg-transparent lg:py-4">
      <div className={`border-l-4 p-4 lg:p-0 lg:pl-3 ${edge}`}>
        {/* Phone: a compact card. */}
        <div className="lg:hidden">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="font-semibold">
              <span className="num">Line {number}</span>
              <span className="text-ink-soft"> · </span>
              <span className="tracking-wide">{line.code || "no code"}</span>
            </h3>
            <span className="num shrink-0 text-lg font-semibold">{money(line.charge)}</span>
          </div>
          <p className="mt-1 break-words">{line.description || "No description"}</p>
          <p className="num mt-0.5 text-[0.9375rem] text-ink-soft">
            {line.units} {line.units === 1 ? "unit" : "units"}{line.service_date ? ` · ${longDate(line.service_date)}` : ""}
          </p>
        </div>
        {/* Wide: one row of the bill table. */}
        <div className="hidden lg:grid lg:grid-cols-[2.25rem_6rem_minmax(0,1fr)_3.5rem_6.5rem] lg:gap-3">
          <h3 className="num font-semibold"><span className="sr-only">Line </span>{number}</h3>
          <p className="font-semibold tracking-wide"><span className="sr-only">Code </span>{line.code || "none"}</p>
          <p className="min-w-0 break-words">
            {line.description || "No description"}
            {line.service_date && <span className="block text-sm text-ink-soft">{longDate(line.service_date)}</span>}
          </p>
          <p className="num text-right"><span className="sr-only">Units </span>{line.units}</p>
          <p className="num text-right font-semibold"><span className="sr-only">Charge </span>{money(line.charge)}</p>
        </div>
        {notChecked && (
          <p className="mt-3 flex gap-2 text-[0.9375rem] text-ctx">
            <CircleMinus aria-hidden className="mt-0.5 size-4 shrink-0" />
            <span>
              <strong>Not checked.</strong> CPT codes need an AMA license, which this demo doesn't use. The charge is
              still counted in your totals.
            </span>
          </p>
        )}
      </div>

      <div className="space-y-3 border-t border-rule p-4 lg:border-0 lg:p-0">
        {notes.map((f, i) => <FindingNote key={`${f.check}${i}`} finding={f} />)}
        {pointers.map((f, i) => (
          <p key={`p${i}`} className="flex flex-wrap items-baseline gap-x-2 text-[0.9375rem]">
            <LevelTag level={shown(f)} />
            <span>
              {CHECK_TITLE[f.check]}:{" "}
              <a className={linkish} href={`#line-${f.line_numbers[0]}`}>see line {f.line_numbers[0]}</a>
            </span>
          </p>
        ))}
        {notes.length === 0 && pointers.length === 0 && (
          <p className="flex items-center gap-2 text-[0.9375rem] text-ink-soft">
            <CircleCheck aria-hidden className="size-4 shrink-0" /> Nothing to flag on this line.
          </p>
        )}
      </div>
    </li>
  );
}

function FindingNote({ finding: f }: { finding: Finding }) {
  if (f.level === "grey" && f.line_numbers.length > 0) return <ContextNote finding={f} />;
  const { why, todo } = advice(f);
  const counted = f.level === "red" && Number(f.dollars_at_stake) > 0;
  const context = f.level === "grey";
  return (
    <article className={`rounded-lg border p-4 ${levelBox(shown(f))}`} aria-label={`${CHECK_TITLE[f.check]}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <LevelTag level={shown(f)} />
        {counted && <span className="num font-semibold">{money(f.dollars_at_stake)} in question</span>}
        {f.check === "gfe" && f.overage && <span className="num font-semibold">{money(f.overage)} over</span>}
      </div>
      <h4 className="mt-1 font-semibold">
        {CHECK_TITLE[f.check]}
        {f.line_numbers.length > 1 && <span className="font-normal text-ink-soft"> · lines {f.line_numbers.join(" and ")}</span>}
      </h4>

      <dl className="mt-2 space-y-2 text-[0.9375rem] leading-relaxed sm:text-base">
        <div>
          <dt className="sr-only">What we found</dt>
          <dd className="text-ink">{f.wording}</dd>
        </div>
        <div>
          <dt className="inline font-semibold">Why it matters: </dt>
          <dd className="inline">{why}</dd>
        </div>
        {!(context && todo === "Nothing to do.") && (
          <div>
            <dt className="inline font-semibold">What to do: </dt>
            <dd className="inline">{todo}</dd>
          </div>
        )}
        {f.judge_reason && (
          <div className="border-t border-black/10 pt-2">
            <dt className="inline font-semibold">Second look ({MODEL_NAME["nvidia/Nemotron-3-Ultra-550b-a55b"]}): </dt>
            <dd className="inline">
              {f.judge_decision === "downgrade" ? "moved to context. " : "kept as worth asking about. "}
              “{f.judge_reason}”
            </dd>
          </div>
        )}
      </dl>

      <Rule finding={f} />
    </article>
  );
}

/** "For context" notes are background: a quiet margin note, not a card competing with the errors. */
function ContextNote({ finding: f }: { finding: Finding }) {
  const { why, todo } = advice(f);
  return (
    <article aria-label={CHECK_TITLE[f.check]} className="border-l-2 border-ctx-line pl-3 text-[0.9375rem] leading-relaxed">
      <p className="flex flex-wrap items-baseline gap-x-2">
        <LevelTag level="grey" />
        <span className="font-semibold">
          {CHECK_TITLE[f.check]}
          {f.line_numbers.length > 1 && <span className="font-normal text-ink-soft"> · lines {f.line_numbers.join(" and ")}</span>}
        </span>
      </p>
      <p className="mt-1">{f.wording}</p>
      <p className="mt-1 text-ink-soft">
        <span className="font-semibold">Why it matters:</span> {why}
        {todo !== "Nothing to do." && <> <span className="font-semibold">What to do:</span> {todo}</>}
      </p>
      <Rule finding={f} quiet />
    </article>
  );
}

function Rule({ finding: f, quiet = false }: { finding: Finding; quiet?: boolean }) {
  const e = f.evidence;
  const rows = [...Object.entries(e.data_row), ...Object.entries(e.computed ?? {})].filter(([, v]) => v !== null && v !== "");
  return (
    <details className={quiet ? "mt-0.5" : "mt-3 border-t border-black/10 pt-1"}>
      <summary className={`inline-flex min-h-11 items-center gap-1.5 ${linkish}`}>
        Show the rule <ChevronDown aria-hidden className="chev size-4" />
      </summary>
      <div className="space-y-3 pb-1 text-[0.9375rem]">
        <p>{e.rule}</p>
        {rows.length > 0 && (
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">The data behind this note</caption>
            <tbody>
              {rows.map(([k, v]) => (
                <tr key={k} className="border-t border-black/10 align-top">
                  <th scope="row" className="py-1.5 pr-3 font-normal text-ink-soft">{DATA_LABEL[k] ?? k.replace(/_/g, " ")}</th>
                  <td className="num break-words py-1.5">{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {e.bill_lines.length > 1 && <BillLines lines={e.bill_lines} />}
        <p>
          Source:{" "}
          {e.source_url ? (
            <a className={linkish} href={e.source_url} target="_blank" rel="noreferrer">
              {e.source_name}<span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : (
            e.source_name
          )}
        </p>
      </div>
    </details>
  );
}

function BillLines({ lines }: { lines: EvidenceLine[] }) {
  return (
    <p className="text-ink-soft">
      Lines: {lines.map((l) => `${l.line_number} (${l.code}, ${l.units} ${l.units === 1 ? "unit" : "units"}, ${money(l.charge)})`).join("; ")}
    </p>
  );
}
