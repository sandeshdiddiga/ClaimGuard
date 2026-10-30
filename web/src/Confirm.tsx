import { CircleHelp, CircleMinus, Plus, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api, type Case, type Line } from "./api";
import { money, sumCharges } from "./format";
import { button, buttonQuiet, ErrorBox, input, Notice, ScreenTitle, Working } from "./ui";

interface Row extends Line {
  key: number;
}

// On a phone each line is a card with visible labels; from md up the same fields line up as a table.
const COLS = "md:grid md:grid-cols-[2.25rem_9.5rem_5.5rem_minmax(0,1fr)_4.5rem_7.5rem_2.75rem] md:items-start md:gap-2";

export function Confirm({ data, onDone }: { data: Case; onDone: (c: Case) => void }) {
  const [rows, setRows] = useState<Row[]>(() => data.lines.map((l, i) => ({ ...l, key: i })));
  const [nextKey, setNextKey] = useState(data.lines.length);
  const [billDate, setBillDate] = useState(data.bill_date ?? "");
  const [amountDue, setAmountDue] = useState(data.amount_due ?? "");
  const [gfe, setGfe] = useState(data.gfe_total ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (key: number, patch: Partial<Line>) =>
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  function addLine() {
    setRows((all) => [
      ...all,
      { key: nextKey, service_date: all.at(-1)?.service_date ?? null, code: "", modifier: null, description: "",
        units: 1, charge: "0.00", status: "needs_review", note: "New line: fill in each field from your bill." },
    ]);
    setNextKey(nextKey + 1);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const clean = (v: string) => v.replace(/[$,\s]/g, "") || null;
      const result = await api.confirm(data.id, {
        lines: rows.map(({ key: _key, ...line }) => ({
          ...line, charge: clean(line.charge) ?? "0", units: Number(line.units) || 1,
          modifier: line.modifier?.trim() || null, service_date: line.service_date || null,
        })),
        bill_date: billDate || null,
        amount_due: clean(amountDue),
        gfe_total: data.patient_type === "self_pay" ? clean(gfe) : null,
      });
      onDone(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  if (busy)
    return (
      <Working
        label="Checking every line against CMS data… a few seconds"
        detail="Duplicates, doses, Medicare's daily unit limits and drug prices, then a second look at anything worth asking about."
        seconds={6}
      />
    );

  const needsLook = rows.filter((r) => r.status === "needs_review").length;

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <ScreenTitle>Check the lines</ScreenTitle>
        <p className="text-lg text-ink-soft">
          Compare these with your bill and fix anything we misread. We check every line exactly as you confirm it.
        </p>
        {data.read_with === "pdfplumber" && (
          <p className="text-ink-soft">This bill was read from the text in the PDF.</p>
        )}
        {data.eob_note && <Notice message={data.eob_note} />}
        {data.eob && (
          <p className="num text-ink-soft">
            We read your EOB as: billed {money(data.eob.billed)}, plan allowed {money(data.eob.allowed)}, you owe{" "}
            {money(data.eob.patient_responsibility)}. If that's not what your EOB says, start over with a clearer copy.
          </p>
        )}
      </header>

      {error && <ErrorBox message={error} />}
      {needsLook > 0 && (
        <p className="flex gap-2 rounded-lg border border-ask-line bg-ask-bg p-4 text-ask">
          <CircleHelp aria-hidden className="mt-0.5 size-5 shrink-0" />
          <span><strong>{needsLook} {needsLook === 1 ? "line needs" : "lines need"} a look.</strong> They're highlighted below.</span>
        </p>
      )}

      <section aria-labelledby="totals-title" className="space-y-3">
        <h2 id="totals-title" className="text-lg font-semibold">From the top of your bill</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field id="bill-date" label="Bill date">
            <input id="bill-date" type="date" value={billDate} onChange={(e) => setBillDate(e.target.value)} className={input} />
          </Field>
          <Field id="amount-due" label="Balance due from you ($)">
            <input id="amount-due" inputMode="decimal" value={amountDue} onChange={(e) => setAmountDue(e.target.value)} className={`${input} num`} />
          </Field>
          {data.patient_type === "self_pay" && (
            <Field id="gfe" label="Good Faith Estimate ($)">
              <input id="gfe" inputMode="decimal" value={gfe} onChange={(e) => setGfe(e.target.value)} className={`${input} num`} />
            </Field>
          )}
        </div>
      </section>

      <section aria-labelledby="lines-title" className="space-y-3">
        <h2 id="lines-title" className="text-lg font-semibold">Charge lines</h2>
        <div aria-hidden className={`hidden px-3 text-sm font-semibold text-ink-soft ${COLS}`}>
          <span>Line</span><span>Date</span><span>Code</span><span>Description</span>
          <span className="text-right">Units</span><span className="text-right">Charge ($)</span><span />
        </div>
        <ol className="space-y-3 md:space-y-0 md:divide-y md:divide-rule md:rounded-lg md:border md:border-rule md:bg-sheet">
          {rows.map((r, i) => {
            const problem = r.status === "needs_review";
            const notChecked = r.code_class === "cpt_shaped";
            return (
              <li key={r.key} className={`rounded-lg border p-3 md:rounded-none md:border-0 md:px-3 md:py-2 ${problem ? "border-ask-line bg-ask-bg md:bg-ask-bg" : "border-rule bg-sheet"}`}>
                <div className={`grid grid-cols-2 gap-3 ${COLS}`}>
                  <p className="col-span-2 flex items-center justify-between font-semibold md:col-span-1 md:block md:pt-2.5">
                    <span><span className="md:sr-only">Line </span>{i + 1}</span>
                  </p>
                  <Cell id={`d${r.key}`} label="Date">
                    <input id={`d${r.key}`} type="date" value={r.service_date ?? ""} className={input}
                           onChange={(e) => change(r.key, { service_date: e.target.value || null })} />
                  </Cell>
                  <Cell id={`c${r.key}`} label="Code">
                    <input id={`c${r.key}`} value={r.code} maxLength={5} aria-invalid={problem || undefined}
                           className={`${input} uppercase ${problem ? "border-2 border-ask bg-sheet" : ""}`}
                           onChange={(e) => change(r.key, { code: e.target.value.toUpperCase(), status: "ok", note: null })} />
                  </Cell>
                  <div className="col-span-2 md:col-span-1">
                    <Cell id={`t${r.key}`} label="Description">
                      <input id={`t${r.key}`} value={r.description} className={input}
                             onChange={(e) => change(r.key, { description: e.target.value })} />
                    </Cell>
                  </div>
                  <Cell id={`u${r.key}`} label="Units">
                    <input id={`u${r.key}`} inputMode="numeric" value={r.units} className={`${input} num md:text-right`}
                           onChange={(e) => change(r.key, { units: Number(e.target.value.replace(/\D/g, "")) })} />
                  </Cell>
                  <Cell id={`p${r.key}`} label="Charge ($)">
                    <input id={`p${r.key}`} inputMode="decimal" value={r.charge} className={`${input} num md:text-right`}
                           onChange={(e) => change(r.key, { charge: e.target.value })} />
                  </Cell>
                  <div className="col-span-2 flex justify-end md:col-span-1 md:block">
                    <button type="button" aria-label={`Remove line ${i + 1}`}
                            className={`${buttonQuiet} border-transparent bg-transparent px-3 font-normal text-ink-soft md:w-11 md:border-rule-strong md:bg-sheet md:px-0`}
                            onClick={() => setRows((all) => all.filter((x) => x.key !== r.key))}>
                      <Trash2 aria-hidden className="size-4" /><span className="md:sr-only">Remove this line</span>
                    </button>
                  </div>
                </div>
                {(problem || notChecked) && (
                  <p className={`mt-2 flex gap-2 text-[0.9375rem] ${problem ? "text-ask" : "text-ctx"}`}>
                    {problem ? <CircleHelp aria-hidden className="mt-0.5 size-4 shrink-0" /> : <CircleMinus aria-hidden className="mt-0.5 size-4 shrink-0" />}
                    <span>{r.note ?? "Please check this line against your bill."}</span>
                  </p>
                )}
              </li>
            );
          })}
        </ol>
        <p className="num text-right text-ink-soft">
          Charges add up to <strong className="text-ink">{money(sumCharges(rows.map((r) => r.charge)))}</strong>
        </p>
      </section>

      <div className="flex flex-col-reverse gap-3 border-t border-rule pt-6 sm:flex-row sm:justify-between">
        <button type="button" className={buttonQuiet} onClick={addLine}>
          <Plus aria-hidden className="size-4" /> Add a missing line
        </button>
        <button type="button" className={button} onClick={submit} disabled={rows.length === 0}>
          These match my bill
        </button>
      </div>
    </div>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block font-semibold">{label}</label>
      {children}
    </div>
  );
}

/** A labelled cell: the label shows on a phone and is read (not shown) in the wide table. */
function Cell({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-semibold text-ink-soft md:sr-only">{label}</label>
      {children}
    </div>
  );
}
