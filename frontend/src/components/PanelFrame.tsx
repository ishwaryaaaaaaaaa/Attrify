import { Maximize2, Minimize2 } from "lucide-react";
import { ReactNode, useEffect } from "react";
import { useStore } from "../store";

type PanelKey = "history" | "table" | "graph";

export function PanelFrame({ letter, title, id, children, scroll = true }: { letter: string; title: string; id?: PanelKey; children: ReactNode; scroll?: boolean }) {
  const maxPanel = useStore((s) => s.maxPanel);
  const setMax = useStore((s) => s.setMaxPanel);
  const maxed = id !== undefined && maxPanel === id;

  useEffect(() => {
    if (!maxed) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMax(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [maxed, setMax]);

  return (
    <section className={`panel${maxed ? " maxed" : ""}`} aria-label={title}>
      <div className="tab"><span className="badge">{letter}</span>{title}</div>
      {id && (
        <button className="expand" aria-label={maxed ? `Close ${title} full width` : `Open ${title} full width`} title={maxed ? "Close (Esc)" : "Full width"} onClick={() => setMax(maxed ? null : id)}>
          {maxed ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
      )}
      <div className="panel-body" style={scroll ? undefined : { padding: 0, overflow: "hidden" }}>{children}</div>
    </section>
  );
}
