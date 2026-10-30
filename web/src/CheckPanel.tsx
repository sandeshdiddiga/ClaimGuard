import { ChevronDown } from "lucide-react";
import type { Case } from "./api";
import { MODEL_NAME, STEP_NAME } from "./copy";
import { linkish } from "./ui";

export function CheckPanel({ data }: { data: Case }) {
  const sources = new Map<string, string | null>();
  data.results?.findings.forEach((f) => sources.set(f.evidence.source_name, f.evidence.source_url));

  return (
    <details className="rounded-lg border border-rule bg-sheet">
      <summary className="flex min-h-11 items-center justify-between gap-3 px-5 py-4 text-lg font-semibold">
        How this was checked
        <ChevronDown aria-hidden className="chev size-5 shrink-0 text-ink-soft" />
      </summary>
      <div className="space-y-5 border-t border-rule px-5 pb-5 pt-4">
        <p className="max-w-prose">
          Every check and every dollar figure is worked out by ordinary code from public CMS data. The models read
          your bill, take a second look at lines worth asking about, and write the opening paragraph of each letter.
          They never decide whether something is an error or calculate an amount.
        </p>

        {data.calls.length === 0 ? (
          <p>No models were used for this bill: it was read from the PDF's text and checked by rules alone.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse text-left">
              <caption className="sr-only">Each model call for this bill</caption>
              <thead>
                <tr className="border-b border-rule-strong text-sm text-ink-soft">
                  <th scope="col" className="py-2 pr-3 font-semibold">Step</th>
                  <th scope="col" className="py-2 pr-3 font-semibold">Model</th>
                  <th scope="col" className="py-2 pr-3 text-right font-semibold">Time</th>
                  <th scope="col" className="py-2 text-right font-semibold">Tokens in / out</th>
                </tr>
              </thead>
              <tbody>
                {data.calls.map((c, i) => (
                  <tr key={i} className="border-b border-rule align-top">
                    <td className="py-2 pr-3">
                      {STEP_NAME[c.step] ?? c.step}
                      {!c.ok && <span className="block text-sm text-err">Failed, retried or fell back</span>}
                    </td>
                    <td className="py-2 pr-3">
                      {MODEL_NAME[c.model] ?? c.model}
                      <span className="block break-all text-sm text-ink-soft">{c.model}</span>
                    </td>
                    <td className="num py-2 pr-3 text-right">{(c.latency_ms / 1000).toFixed(1)} s</td>
                    <td className="num py-2 text-right">{c.prompt_tokens ?? "—"} / {c.completion_tokens ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-sm text-ink-soft">All model calls run on Nebius Token Factory and are logged without any text from your bill.</p>
        {data.calls.some((c) => c.step === "search_web") && (
          <p className="text-sm text-ink-soft">
            The hospital lookup sends Tavily only the hospital's name. Nothing from your bill or your estimate is searched.
          </p>
        )}

        {sources.size > 0 && (
          <div>
            <h3 className="font-semibold">Data used</h3>
            <ul className="mt-1 space-y-1">
              {[...sources].map(([name, url]) => (
                <li key={name}>
                  {url ? <a className={linkish} href={url} target="_blank" rel="noreferrer">{name}</a> : name}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
