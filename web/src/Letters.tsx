import { ArrowLeft, Check, Copy, Download, MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Case, type Letter } from "./api";
import { button, buttonQuiet, ErrorBox, linkish, ScreenTitle, Working } from "./ui";

export function Letters({ data, onBack, onUpdate }: { data: Case; onBack: () => void; onUpdate: (c: Case) => void }) {
  const [letters, setLetters] = useState<Letter[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.letters(data.id)
      .then(async (found) => {
        if (!live) return;
        setLetters(found);
        onUpdate(await api.getCase(data.id)); // the call log now includes the letter paragraphs
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Something went wrong. Please try again."));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.id]);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <button type="button" onClick={onBack} className={`inline-flex min-h-11 items-center gap-1.5 ${linkish}`}>
          <ArrowLeft aria-hidden className="size-4" /> Back to what we found
        </button>
        <ScreenTitle>Send letters</ScreenTitle>
        <p className="text-lg text-ink-soft">
          Read each letter, fill in the parts in [brackets], then send it yourself. ClaimGuard never sends anything for
          you.
        </p>
      </header>

      <section aria-labelledby="to-title" className="flex gap-3 rounded-lg border border-rule bg-sheet p-5">
        <MapPin aria-hidden className="mt-0.5 size-5 shrink-0 text-accent" />
        <div>
          <h2 id="to-title" className="font-semibold">Send these to</h2>
          {data.lookup?.status === "found" && data.lookup.address ? (
            <>
              <p>{data.lookup.hospital_name}, billing office</p>
              <p>{data.lookup.address}</p>
              {data.lookup.phone && <p className="num">{data.lookup.phone}</p>}
              <p className="text-ink-soft">
                {data.lookup.verify_note} Keep a copy of everything you send.
              </p>
            </>
          ) : (
            <>
              <p>{data.facility_name ? `${data.facility_name}, billing office` : "The billing office named on your bill"}</p>
              <p className="text-ink-soft">
                We didn't find an address. Use the billing address printed on your statement, and keep a copy of
                everything you send.
              </p>
            </>
          )}
        </div>
      </section>

      {error && <ErrorBox message={error} />}
      {!letters && !error && (
        <Working
          label="Writing your letters… usually 10–20 seconds"
          detail="Every amount, date and line comes from the findings. Only the opening paragraph is written for you."
          seconds={15}
        />
      )}
      {letters && letters.length === 0 && <p className="text-lg">Nothing on this bill needs a letter.</p>}

      {letters?.map((letter) => <LetterCard key={letter.kind} letter={letter} />)}
    </div>
  );
}

function LetterCard({ letter }: { letter: Letter }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(letter.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section aria-labelledby={`${letter.kind}-title`} className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${letter.kind}-title`} className="text-xl font-bold">{letter.title}</h2>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonQuiet} onClick={copy}>
            {copied ? <Check aria-hidden className="size-4" /> : <Copy aria-hidden className="size-4" />}
            {copied ? "Copied" : "Copy text"}
          </button>
          <a href={letter.pdf_url} download className={button}>
            <Download aria-hidden className="size-4" /> Download PDF
          </a>
        </div>
      </div>
      <p role="status" aria-live="polite" className="sr-only">{copied ? `${letter.title} copied` : ""}</p>
      <article
        aria-label={`Preview: ${letter.title}`}
        className="letter rounded-sm border border-rule bg-white px-5 py-6 shadow-[0_1px_2px_rgba(29,27,24,0.06),0_6px_20px_rgba(29,27,24,0.05)] sm:px-10 sm:py-10"
        // The server's own letter template, every value autoescaped; only headings and blanks are adjusted here.
        dangerouslySetInnerHTML={{ __html: preview(letter.body_html) }}
      />
    </section>
  );
}

/** Letter headings sit under this page's heading; the [blanks] the patient fills in are marked. */
function preview(body: string): string {
  return body
    .replace(/<h1>/g, "<h3>")
    .replace(/<\/h1>/g, "</h3>")
    .replace(/\[([^\]<]+)\]/g, "<mark>[$1]</mark>");
}
