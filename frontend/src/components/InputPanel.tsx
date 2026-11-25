import { useEffect, useState } from "react";
import { casePdfUrl, listCases, type TestCase } from "../api";

interface Props {
  busy: boolean;
  onCheckUpload: (contract: File, invoice: File) => void;
  onCheckCase: (caseId: string) => void;
}

type Mode = "upload" | "case";

export function InputPanel({ busy, onCheckUpload, onCheckCase }: Props) {
  const [mode, setMode] = useState<Mode>("case");
  return (
    <section className="card">
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={mode === "case"} onClick={() => setMode("case")}>
          Try a test case
        </button>
        <button role="tab" aria-selected={mode === "upload"} onClick={() => setMode("upload")}>
          Upload documents
        </button>
      </div>
      {mode === "case" ? (
        <CasePicker busy={busy} onCheck={onCheckCase} />
      ) : (
        <UploadForm busy={busy} onCheck={onCheckUpload} />
      )}
    </section>
  );
}

function CasePicker({ busy, onCheck }: { busy: boolean; onCheck: (id: string) => void }) {
  const [cases, setCases] = useState<TestCase[]>([]);
  const [selected, setSelected] = useState("case_002");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCases().then(setCases, (e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">Could not load the test cases: {error}</p>;
  const current = cases.find((c) => c.id === selected);

  return (
    <div className="panel">
      <p className="hint">
        30 sample trades with known answers. Some are clean; others have a problem planted on purpose.
      </p>
      <label className="field">
        <span>Test case</span>
        <select value={selected} onChange={(e) => setSelected(e.target.value)} disabled={busy}>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>
              {c.id} · {c.commodity} · {c.expected_issues === 0 ? "clean" : `${c.expected_issues} planted issue${c.expected_issues > 1 ? "s" : ""}`}
            </option>
          ))}
        </select>
      </label>
      {current && (
        <div className="case-info">
          <p>{current.description}</p>
          <p className="links">
            View: <a href={casePdfUrl(current.id, "contract")} target="_blank" rel="noreferrer">contract.pdf</a>
            {" · "}
            <a href={casePdfUrl(current.id, "invoice")} target="_blank" rel="noreferrer">invoice.pdf</a>
          </p>
        </div>
      )}
      <button className="primary" disabled={busy || !current} onClick={() => onCheck(selected)}>
        {busy ? "Checking…" : "Run check"}
      </button>
    </div>
  );
}

function UploadForm({ busy, onCheck }: { busy: boolean; onCheck: (contract: File, invoice: File) => void }) {
  const [contract, setContract] = useState<File | null>(null);
  const [invoice, setInvoice] = useState<File | null>(null);

  return (
    <div className="panel">
      <p className="hint">Upload a sales contract and the commercial invoice issued under it, both as PDFs with a text layer.</p>
      <div className="uploads">
        <FileSlot label="Sales contract" file={contract} onChange={setContract} disabled={busy} />
        <FileSlot label="Commercial invoice" file={invoice} onChange={setInvoice} disabled={busy} />
      </div>
      <button
        className="primary"
        disabled={busy || !contract || !invoice}
        onClick={() => contract && invoice && onCheck(contract, invoice)}
      >
        {busy ? "Checking…" : "Check documents"}
      </button>
    </div>
  );
}

function FileSlot(props: { label: string; file: File | null; onChange: (f: File | null) => void; disabled: boolean }) {
  return (
    <label className={`file-slot ${props.file ? "has-file" : ""}`}>
      <span className="slot-label">{props.label}</span>
      <span className="slot-file">{props.file ? props.file.name : "Choose a PDF…"}</span>
      <input
        type="file"
        accept="application/pdf,.pdf"
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.files?.[0] ?? null)}
      />
    </label>
  );
}
