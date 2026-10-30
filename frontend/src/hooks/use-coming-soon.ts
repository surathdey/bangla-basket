// Global "grocery coming soon" flag. When the store owner flips this on in
// Admin → Settings, grocery items stay visible but can't be bought yet — every
// Add / Add-to-cart button shows a disabled "Coming soon" label instead.
import { useEffect, useState } from "react";
import { api } from "@/src/api";

export function useComingSoon(): boolean {
  const [coming, setComing] = useState(false);
  useEffect(() => {
    (async () => {
      const r = await api.get<{ grocery_coming_soon?: boolean }>("/settings");
      if (r.ok) setComing(!!r.data?.grocery_coming_soon);
    })();
  }, []);
  return coming;
}
