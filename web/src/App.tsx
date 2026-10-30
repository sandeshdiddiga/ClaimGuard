import { useEffect, useState } from "react";
import { api, type Case } from "./api";
import { CheckPanel } from "./CheckPanel";
import { Confirm } from "./Confirm";
import { Letters } from "./Letters";
import { Results } from "./Results";
import { Start } from "./Start";
import { ErrorBox, ProgressLine, Working } from "./ui";

// The case lives in the address (#case=<id> or #case=<id>/letters) so a reload returns to the same place.
const HASH = /^#case=([0-9a-f]{32})(\/letters)?$/;

function readHash(): { id: string; letters: boolean } | null {
  const match = HASH.exec(window.location.hash);
  return match ? { id: match[1], letters: Boolean(match[2]) } : null;
}

export default function App() {
  const [data, setData] = useState<Case | null>(null);
  const [letters, setLetters] = useState(readHash()?.letters ?? false);
  const [loading, setLoading] = useState(readHash() !== null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const where = readHash();
    if (!where) return;
    api.getCase(where.id).then(setData).catch(() => {
      setError("We couldn't find that bill. Start again below.");
      window.location.hash = "";
    }).finally(() => setLoading(false));
  }, []);

  function go(next: Case, toLetters = false) {
    window.location.hash = `case=${next.id}${toLetters ? "/letters" : ""}`;
    setData(next);
    setLetters(toLetters);
    window.scrollTo(0, 0);
  }

  function restart() {
    window.location.hash = "";
    setData(null);
    setLetters(false);
    window.scrollTo(0, 0);
  }

  const step = !data ? 0 : data.stage === "confirm" ? 1 : letters ? 3 : 2;
  const width = !data ? "max-w-3xl" : data.stage === "confirm" ? "max-w-5xl" : letters ? "max-w-3xl" : "max-w-6xl";

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-sheet">
        <div className={`mx-auto px-4 pb-4 pt-4 sm:px-6 ${width}`}>
          <div className="mb-4 flex items-baseline justify-between gap-3">
            <button type="button" onClick={restart} className="-mx-1 rounded px-1 text-xl font-bold tracking-tight">
              ClaimGuard
            </button>
            <span className="text-sm text-ink-soft">A second look at your medical bill</span>
          </div>
          <ProgressLine current={step} />
        </div>
      </header>

      <main className={`mx-auto px-4 py-8 sm:px-6 ${width}`}>
        {error && <div className="mb-6"><ErrorBox message={error} /></div>}
        {loading ? <Working label="Opening your bill…" seconds={2} />
          : !data ? <Start onCase={(c) => go(c)} />
          : data.stage === "confirm" ? <Confirm data={data} onDone={(c) => go(c)} />
          : letters ? <Letters data={data} onBack={() => go(data)} onUpdate={setData} />
          : <Results data={data} onLetters={() => go(data, true)} onRestart={restart} onUpdate={setData} />}

        {data && data.stage === "results" && (
          <div className="mt-12">
            <CheckPanel data={data} />
          </div>
        )}
      </main>

      <footer className="border-t border-rule">
        <div className={`mx-auto space-y-1 px-4 py-6 text-sm text-ink-soft sm:px-6 ${width}`}>
          <p>ClaimGuard explains and drafts. It isn't legal or medical advice.</p>
          <p>Uses CMS public data only; no AMA CPT content.</p>
        </div>
      </footer>
    </div>
  );
}
