import { useEffect, useState } from "react";

/**
 * Returns a copy of `value` that only updates after `delay` ms have elapsed
 * without further changes. Use to throttle work driven by a rapidly-changing
 * input — e.g. a search box that would otherwise fire one request per keystroke.
 */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
