import React, { useEffect } from "react";
import { CheckoutScreen } from "../cart";
import { track } from "@/src/analytics";

/** Desktop-web checkout page — renders the shared checkout with the full
 *  site header/footer and a centered, constrained layout. The mobile app
 *  keeps using /cart. */
export default function ShopCart() {
  // Anonymous launch analytics: this screen IS the shop cart + checkout,
  // so mounting it counts as both a page view and a cart view.
  useEffect(() => {
    track("page_view", { path: "/shop/cart" });
    track("cart_view");
  }, []);
  return <CheckoutScreen webShell />;
}
