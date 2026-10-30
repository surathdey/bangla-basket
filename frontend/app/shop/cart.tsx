import React from "react";
import { CheckoutScreen } from "../cart";

/** Desktop-web checkout page — renders the shared checkout with the full
 *  site header/footer and a centered, constrained layout. The mobile app
 *  keeps using /cart. */
export default function ShopCart() {
  return <CheckoutScreen webShell />;
}
