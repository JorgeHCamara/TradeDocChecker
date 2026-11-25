import { useEffect, useState } from "react";
import { checkCase, checkUpload, type Report as ReportData } from "./api";
import { InputPanel } from "./components/InputPanel";
import { Report } from "./components/Report";

export default function App() {
  const [report, setReport] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(call: () => Promise<ReportData>) {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await call());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header>
        <h1>Trade Document Checker</h1>
        <p>
          Checks a commodity trade's commercial invoice against its sales contract. An LLM reads both PDFs;
          plain code compares them.
        </p>
      </header>
      <InputPanel
        busy={busy}
        onCheckCase={(id) => run(() => checkCase(id))}
        onCheckUpload={(contract, invoice) => run(() => checkUpload(contract, invoice))}
      />
      {busy && <Progress />}
      {error && (
        <section className="card error" role="alert">
          <strong>Check failed.</strong> {error}
        </section>
      )}
      {report && <Report report={report} />}
    </main>
  );
}

function Progress() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <section className="card progress" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <div>
        <strong>Reading both documents…</strong>
        <p className="hint">Usually takes 10–20 seconds. {seconds}s so far.</p>
      </div>
    </section>
  );
}
