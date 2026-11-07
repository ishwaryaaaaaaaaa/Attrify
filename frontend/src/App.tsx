import { useEffect } from "react";
import { StartScreen } from "./components/StartScreen";
import { Workspace } from "./components/Workspace";
import { useStore } from "./store";

export default function App() {
  const screen = useStore((s) => s.screen);
  const init = useStore((s) => s.init);
  useEffect(() => { void init(); }, [init]);
  if (screen === "loading") return <div className="start"><div className="skeleton" style={{ height: 120 }} /></div>;
  if (screen === "start") return <StartScreen />;
  return <Workspace />;
}
