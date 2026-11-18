/**
 * OffersPopup — the 4 current Bangla Basket offers, shown on homepage load.
 *
 * Deliberately styled ONLY with the site's own theme tokens (src/theme.ts):
 * System fonts, brand navy/gold, site radii/spacing/shadows. No new font,
 * no new palette — the pop-up must look like it belongs to banglabasket.ca.
 *
 * Behaviour: shows on homepage / shop / login load (once per browser
 * session — dismissal is remembered in sessionStorage); closes via X,
 * backdrop tap, or Esc (web). "Shop now" closes it and goes to /shop
 * (if already on /shop it just closes). No "Maybe later" — the only
 * call-to-action is "Shop now".
 */
import React, { useEffect } from "react";
import {
  Modal,
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Pressable,
  Image,
  ScrollView,
  Platform,
  useWindowDimensions,
} from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter, usePathname } from "expo-router";
import { colors, radius, spacing, shadows, fonts } from "@/src/theme";

const IMG_GROCERY = require("@/assets/offers/grocery.jpg");
const IMG_HILSA = require("@/assets/offers/hilsa.jpg");
const IMG_THALI = require("@/assets/offers/thali.jpg");
const IMG_REFERRAL = require("@/assets/offers/referral.jpg");

type Offer = {
  key: string;
  img: any;
  badge: string;
  badgeFree: boolean;
  title: string;
  sub: string;
  steps?: boolean;
};

const OFFERS: Offer[] = [
  {
    key: "first20",
    img: IMG_GROCERY,
    badge: "20% OFF",
    badgeFree: false,
    title: "Flat 20% OFF your first grocery order",
    sub: "First-time buyers only. Auto-applied at checkout — weekly meal excluded, guests excluded.",
  },
  {
    key: "hilsa",
    img: IMG_HILSA,
    badge: "FREE",
    badgeFree: true,
    title: "4pc Hilsa FREE with your first Weekly Meal ($59.99)",
    sub: "Order your first weekly meal and get 4 pieces of hilsa on us.",
  },
  {
    key: "fifthfree",
    img: IMG_THALI,
    badge: "FREE",
    badgeFree: true,
    title: "5th Weekly Meal FREE",
    sub: "Order 4 weekly meals in a row and your 5th is on us.",
    steps: true,
  },
  {
    key: "referral",
    img: IMG_REFERRAL,
    badge: "10% OFF",
    badgeFree: false,
    title: "Referral Bonus — you both get 10% off",
    sub: "Invite a friend. When they order, you both get 10% off — once per pair.",
  },
];

export function OffersPopup({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const { width } = useWindowDimensions();
  const isNarrow = width < 480;

  // Esc closes the pop-up (web only).
  useEffect(() => {
    if (!visible || Platform.OS !== "web") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, onClose]);

  // "Shop now" — the only call-to-action. Goes to /shop; if the visitor
  // is already on /shop it just closes the pop-up.
  const shopNow = () => {
    onClose();
    if (pathname && pathname.startsWith("/shop")) return;
    router.push("/shop");
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.center}>
        <Pressable
          style={styles.backdrop}
          onPress={onClose}
          testID="offers-backdrop"
          accessibilityLabel="Close offers"
        />
        <View style={[styles.card, isNarrow && styles.cardNarrow]} testID="offers-popup">
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Special offers</Text>
              <Text style={styles.subtitle}>Save on your first order — and every week after.</Text>
            </View>
            <TouchableOpacity
              onPress={onClose}
              testID="offers-close"
              style={styles.closeBtn}
              accessibilityLabel="Close"
              hitSlop={8}
            >
              <Ionicons name="close" size={22} color={colors.text} />
            </TouchableOpacity>
          </View>

          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.list}>
            {OFFERS.map((o) => (
              <View key={o.key} style={styles.offer} testID={`offer-${o.key}`}>
                <View style={styles.imgWrap}>
                  <Image source={o.img} style={styles.offerImg} resizeMode="cover" />
                  <View style={[styles.badgeOnImg, o.badgeFree ? styles.badgeFree : styles.badgeOff]}>
                    <Text style={styles.badgeText}>{o.badge}</Text>
                  </View>
                </View>
                <View style={styles.offerBody}>
                  <Text style={styles.offerTitle}>{o.title}</Text>
                  <Text style={styles.offerSub}>{o.sub}</Text>
                  {o.steps && (
                    <View style={styles.steps} testID="offer-fifthfree-steps">
                      {[1, 2, 3, 4].map((n) => (
                        <React.Fragment key={n}>
                          <View style={styles.stepDot}>
                            <Text style={styles.stepNum}>{n}</Text>
                          </View>
                          {n < 4 && <View style={styles.stepLine} />}
                        </React.Fragment>
                      ))}
                      <Ionicons
                        name="arrow-forward"
                        size={16}
                        color={colors.textMuted}
                        style={{ marginHorizontal: 4 }}
                      />
                      <View style={[styles.badge, styles.badgeFree]}>
                        <Text style={styles.badgeText}>FREE</Text>
                      </View>
                    </View>
                  )}
                </View>
              </View>
            ))}
          </ScrollView>

          <View style={styles.footer}>
            <TouchableOpacity
              onPress={shopNow}
              testID="offers-shop-now"
              style={styles.primaryBtn}
              activeOpacity={0.9}
            >
              <Text style={styles.primaryBtnText}>Shop now</Text>
              <Ionicons name="arrow-forward" size={16} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.terms}>
              First-order 20% applies to groceries only and is auto-applied at checkout. Hilsa is free
              with your first weekly meal. Your 5th weekly meal is free after 4 consecutive weekly meals.
              Referral 10% applies to you and your friend, once per pair.
            </Text>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: "rgba(1,24,56,0.55)",
  },
  card: {
    width: "92%",
    maxWidth: 520,
    maxHeight: "88%",
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    overflow: "hidden",
    // Must sit above the backdrop (same stacking context, both z-index
    // auto would leave the absolutely-positioned backdrop on top and the
    // card's buttons unclickable). The card is position:relative, so this
    // zIndex puts it above the backdrop.
    zIndex: 1,
    ...shadows.card,
  },
  cardNarrow: { width: "94%" },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
  },
  title: {
    fontFamily: fonts.heading,
    fontSize: 22,
    fontWeight: "800",
    color: colors.text,
    letterSpacing: -0.3,
  },
  subtitle: {
    fontFamily: fonts.body,
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 18,
    marginTop: 4,
  },
  closeBtn: {
    width: 44,
    height: 44,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceAlt,
    alignItems: "center",
    justifyContent: "center",
  },
  list: { paddingHorizontal: spacing.lg, gap: spacing.md, paddingBottom: spacing.md },
  offer: {
    flexDirection: "row",
    gap: spacing.md,
    backgroundColor: colors.background,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  imgWrap: { width: 88, height: 88, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surfaceAlt },
  offerImg: { width: "100%", height: "100%" },
  badgeOnImg: {
    position: "absolute",
    top: 6,
    left: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  badgeFree: { backgroundColor: colors.success },
  badgeOff: { backgroundColor: colors.primary },
  badgeText: {
    fontFamily: fonts.body,
    color: "#fff",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.5,
  },
  offerBody: { flex: 1, gap: 4 },
  offerTitle: {
    fontFamily: fonts.heading,
    fontSize: 15,
    fontWeight: "800",
    color: colors.text,
    lineHeight: 19,
  },
  offerSub: { fontFamily: fonts.body, fontSize: 12.5, color: colors.textMuted, lineHeight: 17 },
  steps: { flexDirection: "row", alignItems: "center", marginTop: 6 },
  stepDot: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.chipBg,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  stepNum: { fontFamily: fonts.body, fontSize: 12, fontWeight: "800", color: colors.primary },
  stepLine: { width: 10, height: 1, backgroundColor: colors.border },
  footer: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg, paddingTop: spacing.sm, gap: spacing.sm },
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.primary,
    height: 50,
    borderRadius: radius.pill,
  },
  primaryBtnText: { fontFamily: fonts.body, color: "#fff", fontSize: 15, fontWeight: "800" },
  terms: {
    fontFamily: fonts.body,
    fontSize: 11,
    color: colors.textMuted,
    lineHeight: 15,
    textAlign: "center",
  },
});
