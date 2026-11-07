import { useLayoutEffect, useState } from "react";

export function useSize(ref: React.RefObject<HTMLElement>) {
  const [size, setSize] = useState({ w: 600, h: 300 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [ref]);
  return size;
}
