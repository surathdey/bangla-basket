import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, useWindowDimensions, Platform, Modal } from "react-native";
import { Image } from "expo-image";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useCart } from "@/src/cart";
import { BRAND } from "@/src/brand";
import { spacing, radius, shadows } from "@/src/theme";
import { LocationBanner } from "@/src/components/LocationBanner";
import { ShopAccountButton } from "@/src/components/ShopAccountButton";

const BLUE = "#1E5AA8";
const RED = "#D62828";
const GOLD = "#F2A81C";
const CREAM = "#FFF8F0";
const INK = "#1F2D45";

const CIRCLE_LOGO = require("@/assets/brand/logo-circle.png");

export type ShopNavKey = "home" | "groceries" | "spices" | "frozen-food" | "meal-plans" | "about" | "delivery";

/** Logo in a filled white circle — the solid background + border means there's
 *  never an "empty circle" flash while the bitmap decodes (fixes BUG-BB-003). */
export function ShopLogo({ size, border = 3 }: { size: number; border?: number }) {
  return (
    <View style={[styles.logoCircle, { width: size, height: size, borderRadius: size / 2, borderWidth: border }]}>
      <Image
        source={CIRCLE_LOGO}
        style={{ width: size - border * 2, height: size - border * 2 }}
        contentFit="contain"
        cachePolicy="memory-disk"
        priority="high"
      />
    </View>
  );
}

type Props = {
  active?: ShopNavKey;
  /** Home page passes scroll handlers so About/Delivery scroll to sections. */
  navHandlers?: { home?: () => void; about?: () => void; delivery?: () => void };
  /** Hide the thin red announcement strip (e.g. on checkout). */
  showAnnounce?: boolean;
};

/** One shared storefront header used on every /shop page. */
export function ShopHeader({ active, navHandlers, showAnnounce = true }: Props) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { count } = useCart();
  const { user } = useAuth();
  const loggedIn = !!user && user.role !== "guest";
  const isNarrow = width < 900;
  const contentWidth = Math.min(width, 1200);

  // Free-delivery ribbon text/visibility are admin-configurable (same source
  // the mobile app uses) — fetch so the web reflects admin changes too.
  const [ribbon, setRibbon] = useState<{ enabled: boolean; text: string }>({
    enabled: true, text: "Free delivery on orders over $150",
  });
  const [loyaltyEnabled, setLoyaltyEnabled] = useState(true);
  const [comingSoon, setComingSoon] = useState<{ label: string; msg: string } | null>(null);
  useEffect(() => {
    (async () => {
      const r = await api.get<{ delivery_ribbon_enabled?: boolean; delivery_ribbon_text?: string; loyalty_enabled?: boolean }>("/settings");
      if (r.ok) {
        setRibbon({
          enabled: r.data?.delivery_ribbon_enabled !== false,
          text: (r.data?.delivery_ribbon_text || "Free delivery on orders over $150").trim(),
        });
        setLoyaltyEnabled(r.data?.loyalty_enabled !== false);
      }
    })();
  }, []);
  const showRibbon = showAnnounce && ribbon.enabled && !!ribbon.text;

  const nav: { key: ShopNavKey; label: string; onPress: () => void }[] = [
    { key: "home", label: "Home", onPress: navHandlers?.home || (() => router.push("/shop")) },
    { key: "groceries", label: "Groceries", onPress: () => router.push("/shop/browse") },
    { key: "spices", label: "Spices", onPress: () => setComingSoon({ label: "Spices", msg: "Spices are coming soon to Bangla Basket." }) },
    { key: "frozen-food", label: "Frozen Food", onPress: () => setComingSoon({ label: "Frozen Food", msg: "Frozen food is coming soon to Bangla Basket." }) },
    { key: "meal-plans", label: "Meal Plans", onPress: () => router.push("/shop/meal-plans") },
    { key: "about", label: "About Us", onPress: navHandlers?.about || (() => router.push({ pathname: "/shop", params: { section: "about" } })) },
    { key: "delivery", label: "Delivery", onPress: navHandlers?.delivery || (() => router.push({ pathname: "/shop", params: { section: "delivery" } })) },
  ];

  return (
    <View style={styles.wrap}>
      {showRibbon && (
        <View style={[styles.announce, { paddingTop: insets.top }]} testID="shop-delivery-ribbon">
          <Text style={styles.announceText} numberOfLines={1}>🚚  {ribbon.text}</Text>
        </View>
      )}
      <LocationBanner topInset={showRibbon ? 0 : insets.top} />

      <View style={styles.nav}>
        <View style={[styles.navInner, { width: contentWidth }]}>
          <TouchableOpacity testID="shop-header-logo" style={styles.brandRow} onPress={() => router.push("/shop")}>
            <ShopLogo size={46} />
            <Text style={styles.brandName}>{BRAND.name}</Text>
          </TouchableOpacity>

          {!isNarrow && (
            <View style={styles.navLinks}>
              {nav.map(n => (
                <TouchableOpacity key={n.key} testID={`nav-${n.label}`} onPress={n.onPress} style={styles.navLinkBtn}>
                  <Text style={[styles.navLinkText, active === n.key && styles.navLinkActive]}>{n.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
          )}

          <View style={styles.navRight}>
            <ShopAccountButton compact={isNarrow} loyaltyEnabled={loyaltyEnabled} />
            {loggedIn && (
              <TouchableOpacity testID="shop-refer-btn" style={styles.navGhost} onPress={() => router.push("/shop/account")}>
                <Ionicons name="gift-outline" size={16} color={INK} />
                {!isNarrow && <Text style={styles.navGhostText}>Refer friend</Text>}
              </TouchableOpacity>
            )}
            <TouchableOpacity testID="home-cart-btn" style={styles.cartBtn} onPress={() => router.push("/shop/cart")}>
              <Ionicons name="cart" size={18} color="#fff" />
              {!isNarrow && <Text style={styles.cartBtnText}>Cart</Text>}
              {count > 0 && <View style={styles.cartDot}><Text style={styles.cartDotText}>{count}</Text></View>}
            </TouchableOpacity>
          </View>
        </View>

        {isNarrow && (Platform.OS === "web" ? (
          // Plain native horizontal scroller on web: the RN ScrollView's JS
          // responder layer + the sticky, centre-aligned header left this
          // ribbon stuck mid-scroll on iOS Safari (Home/Delivery unreachable
          // by finger). A plain overflow-x row is the standard mobile-web
          // tab-bar pattern and scrolls natively. Native apps keep ScrollView.
          <View style={styles.navScrollWeb}>
            {nav.map(n => (
              <TouchableOpacity key={n.key} testID={`nav-m-${n.label}`} onPress={n.onPress} style={[styles.navChip, active === n.key && styles.navChipOn]}>
                <Text style={[styles.navChipText, active === n.key && { color: "#fff" }]}>{n.label}</Text>
              </TouchableOpacity>
            ))}
          </View>
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.navScroll}>
            {nav.map(n => (
              <TouchableOpacity key={n.key} testID={`nav-m-${n.label}`} onPress={n.onPress} style={[styles.navChip, active === n.key && styles.navChipOn]}>
                <Text style={[styles.navChipText, active === n.key && { color: "#fff" }]}>{n.label}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        ))}
      </View>

      <Modal visible={comingSoon !== null} transparent animationType="fade" onRequestClose={() => setComingSoon(null)}>
        <View style={styles.csOverlay} testID="coming-soon-modal">
          <View style={styles.csCard}>
            <Text style={styles.csTitle}>COMING SOON</Text>
            <Text style={styles.csMsg}>{comingSoon?.msg}</Text>
            <TouchableOpacity testID="coming-soon-close" style={styles.csBtn} onPress={() => setComingSoon(null)}>
              <Text style={styles.csBtnText}>OK</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { ...(Platform.OS === "web" ? { position: "sticky" as any, top: 0, zIndex: 30 } : {}) },
  announce: { backgroundColor: RED, alignItems: "center", justifyContent: "center", paddingVertical: 7, paddingHorizontal: spacing.lg },
  announceText: { color: "#fff", fontSize: 12.5, fontWeight: "700", letterSpacing: 0.2 },

  logoCircle: { backgroundColor: "#fff", borderColor: BLUE, alignItems: "center", justifyContent: "center", overflow: "hidden" },

  nav: { backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: "#F0E6D8", alignItems: "center", ...shadows.soft },
  navInner: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: 10 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  brandName: { fontSize: 21, fontWeight: "900", color: INK, letterSpacing: -0.5 },
  navLinks: { flexDirection: "row", alignItems: "center", gap: 4 },
  navLinkBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
  navLinkText: { fontSize: 14.5, fontWeight: "700", color: INK },
  navLinkActive: { color: RED },
  navRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  navGhost: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, height: 40, borderRadius: radius.pill, borderWidth: 1, borderColor: "#E6D9C6" },
  navGhostText: { fontSize: 13, fontWeight: "700", color: INK },
  cartBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, height: 40, borderRadius: radius.pill, backgroundColor: RED },
  cartBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  cartDot: { position: "absolute", top: -4, right: -4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: GOLD, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  cartDotText: { color: "#1a1a1a", fontSize: 10, fontWeight: "900" },
  navScroll: { gap: 8, paddingHorizontal: spacing.lg, paddingBottom: 10, alignItems: "center" },
  // Web-only ribbon scroller: full width (never shrink-wrapped by the
  // centre-aligned header), native momentum scrolling, no scrollbar.
  navScrollWeb: {
    flexDirection: "row", gap: 8, alignItems: "center",
    width: "100%", overflowX: "auto", overflowY: "hidden",
    paddingHorizontal: spacing.lg, paddingBottom: 10,
    WebkitOverflowScrolling: "touch", scrollbarWidth: "none",
  } as any,
  navChip: { flexShrink: 0, paddingHorizontal: 14, height: 34, borderRadius: radius.pill, backgroundColor: CREAM, borderWidth: 1, borderColor: "#EBDFCE", alignItems: "center", justifyContent: "center" },
  navChipOn: { backgroundColor: RED, borderColor: RED },
  navChipText: { fontSize: 13, fontWeight: "700", color: INK },
  csOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", padding: spacing.lg },
  csCard: { backgroundColor: "#fff", borderRadius: 16, padding: 24, maxWidth: 360, width: "100%", alignItems: "center", gap: 10 },
  csTitle: { fontSize: 20, fontWeight: "900", color: INK, letterSpacing: 1 },
  csMsg: { fontSize: 14, color: INK, textAlign: "center" },
  csBtn: { backgroundColor: RED, paddingHorizontal: 28, paddingVertical: 10, borderRadius: radius.pill, marginTop: 6 },
  csBtnText: { color: "#fff", fontSize: 14, fontWeight: "800" },
});
