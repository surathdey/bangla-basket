import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, ActivityIndicator,
  useWindowDimensions, Platform,
} from "react-native";
import { Image, ImageBackground } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "@/src/api";
import { useCart } from "@/src/cart";
import { mediaUrl } from "@/src/utils/backendUrl";
import { spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";
import { ShopHeader } from "@/src/components/ShopHeader";
import { ShopFooter } from "@/src/components/ShopFooter";

const BLUE = "#1E5AA8";
const RED = "#D62828";
const GOLD = "#F2A81C";
const CREAM = "#FFF8F0";
const INK = "#1F2D45";
const MUTE = "#6B7280";
const VEG = "#1A8917";
const NONVEG = "#B3402F";

const HERO_BANNER = "/api/files/bongconnekt/banners/hero-meal.png";

/** Human label for the current week ("Week of Mon, Oct 3") derived from the
 *  live date so it never goes stale, independent of the admin menu title. */
function currentWeekLabel(): string {
  const now = new Date();
  const monday = new Date(now);
  const dow = now.getDay(); // Sun=0..Sat=6
  const diff = (dow === 0 ? -6 : 1) - dow; // back to Monday
  monday.setDate(now.getDate() + diff);
  return `Week of ${monday.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}`;
}

type MenuItem = {
  item_id: string; name: string; description?: string; price_cents: number;
  image_url?: string; veg_type?: string; is_featured?: boolean;
};
type WeeklyPkg = {
  name: string; description?: string; image_url?: string; pricing_mode?: string;
  pick_count: number; price_cents: number; max_per_dish?: number;
  veg_price_cents?: number; mixed_price_cents?: number; nonveg_price_cents?: number;
  veg_pick_count?: number; nonveg_pick_count?: number; mixed_veg_count?: number; mixed_nonveg_count?: number;
};
type WeeklyMenu = {
  menu_id: string; title: string; package_enabled?: boolean; package?: WeeklyPkg | null;
  alacarte_enabled?: boolean;
  items: MenuItem[]; complimentary_items?: MenuItem[];
};

export default function ShopMealPlans() {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { add } = useCart();
  const [menu, setMenu] = useState<WeeklyMenu | null>(null);
  const [loading, setLoading] = useState(true);

  const isNarrow = width < 900;
  const contentWidth = Math.min(width, 1200);

  useEffect(() => {
    (async () => {
      const r = await api.get<WeeklyMenu>("/menu/current");
      setMenu(r.ok ? r.data : null);
      setLoading(false);
    })();
  }, []);

  const pkg = menu?.package;
  const isComp = pkg?.pricing_mode === "composition";
  const build = () => menu && router.push(`/menu/package/${menu.menu_id}?from=shop`);

  // Fixed bundle: flat price, pick_count == every dish, max 1 each — the
  // bundle IS all dishes, so there is nothing to pick. The page itself
  // becomes the order page (old-app layout): dishes listed below with
  // disabled steppers, one "Order this week's plan" button, no second click.
  const fixedItems = menu?.items || [];
  const isFixedBundle = !isComp && !!pkg && (pkg.pick_count || 0) > 0
    && fixedItems.length === pkg.pick_count && (pkg.max_per_dish || 0) === 1;
  const fixedVeg = fixedItems.filter(i => (i.veg_type || "vegetarian") === "vegetarian");
  const fixedNonVeg = fixedItems.filter(i => (i.veg_type || "vegetarian") !== "vegetarian");
  const orderFixed = () => {
    if (!menu || !pkg || !isFixedBundle) return;
    const ids = fixedItems.map(i => i.item_id);
    const names = fixedItems.map(i => i.name);
    add({
      kind: "weekly_package",
      ref_id: menu.menu_id,
      name: pkg.name,
      price_cents: pkg.price_cents,
      image_url: pkg.image_url || "",
      package_selections: ids,
      package_selection_names: names,
      package_pick_count: ids.length,
      weekly_menu_id: menu.menu_id,
      selection_labels: [{ title: "This week's plan", items: names }],
    });
    router.push("/shop/cart");
  };
  const primaryAction = isFixedBundle ? orderFixed : build;
  const primaryLabel = isFixedBundle ? "Order this week's plan" : "Build your plan";

  const vegItems = (menu?.items || []).filter(i => (i.veg_type || "vegetarian") === "vegetarian");
  const nonVegItems = (menu?.items || []).filter(i => (i.veg_type || "vegetarian") !== "vegetarian");
  // Package-only menus (alacarte off) have no à la carte listings: the dish
  // sections below would show $0 dishes, so they stay hidden and the page
  // shows only the package card. Old menus without the flag keep sections.
  const showDishes = menu?.alacarte_enabled ?? true;

  const tiers = pkg && isComp ? [
    { label: `${pkg.veg_pick_count || pkg.pick_count} Veg`, price: pkg.veg_price_cents || 0 },
    ...(pkg.mixed_veg_count && pkg.mixed_nonveg_count
      ? [{ label: `${pkg.mixed_veg_count} Veg + ${pkg.mixed_nonveg_count} Non-Veg`, price: pkg.mixed_price_cents || 0 }]
      : []),
    { label: `${pkg.nonveg_pick_count || pkg.pick_count} Non-Veg`, price: pkg.nonveg_price_cents || 0 },
  ] : [];

  // Fixed-bundle dish row (old-app layout): photo, name, description, and a
  // DISABLED stepper showing 1 — the dish is included, it cannot be picked.
  const FixedDishRow = ({ it }: { it: MenuItem }) => {
    const isVeg = (it.veg_type || "vegetarian") === "vegetarian";
    return (
      <View style={styles.fixedRow} testID={`mp-fixed-${it.item_id}`}>
        <View style={styles.fixedImgWrap}>
          {it.image_url
            ? <Image source={{ uri: mediaUrl(it.image_url) }} style={styles.fixedImg} contentFit="cover" transition={200} />
            : <View style={[styles.fixedImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="image-outline" size={24} color={MUTE} /></View>}
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View style={[styles.vegMark, { borderColor: isVeg ? VEG : NONVEG }]}>
              <View style={[styles.vegDot, { backgroundColor: isVeg ? VEG : NONVEG }]} />
            </View>
            <Text style={styles.dishName} numberOfLines={1}>{it.name}</Text>
          </View>
          {!!it.description && <Text style={styles.dishDesc} numberOfLines={2}>{it.description}</Text>}
          <Text style={styles.fixedIncluded}>Included in this week's plan</Text>
        </View>
        <View style={[styles.fixedStepper, { opacity: 0.45 }]}>
          <View style={styles.fixedStepBtn}><Text style={styles.fixedStepText}>−</Text></View>
          <Text style={styles.fixedQty}>1</Text>
          <View style={styles.fixedStepBtn}><Text style={styles.fixedStepText}>+</Text></View>
        </View>
      </View>
    );
  };

  const DishCard = ({ it }: { it: MenuItem }) => {
    const isVeg = (it.veg_type || "vegetarian") === "vegetarian";
    return (
      <View style={styles.dish} testID={`mp-dish-${it.item_id}`}>
        <View style={styles.dishImgWrap}>
          {it.image_url
            ? <Image source={{ uri: mediaUrl(it.image_url) }} style={styles.dishImg} contentFit="cover" transition={200} />
            : <View style={[styles.dishImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="image-outline" size={24} color={MUTE} /></View>}
        </View>
        <View style={{ padding: spacing.md, gap: 4 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View style={[styles.vegMark, { borderColor: isVeg ? VEG : NONVEG }]}>
              <View style={[styles.vegDot, { backgroundColor: isVeg ? VEG : NONVEG }]} />
            </View>
            <Text style={styles.dishName} numberOfLines={1}>{it.name}</Text>
          </View>
          {!!it.description && <Text style={styles.dishDesc} numberOfLines={2}>{it.description}</Text>}
          <Text style={styles.dishPrice}>À la carte {centsToCAD(it.price_cents)}</Text>
        </View>
      </View>
    );
  };

  return (
    <View style={{ flex: 1, backgroundColor: CREAM }}>
      <ShopHeader active="meal-plans" />

      <ScrollView contentContainerStyle={{ paddingBottom: 48 + insets.bottom, alignItems: "center" }}>
        {/* HERO BANNER */}
        <View style={{ width: "100%", alignItems: "center", backgroundColor: BLUE }}>
          <View style={styles.hero}>
            <ImageBackground source={{ uri: mediaUrl(HERO_BANNER) }} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
            <LinearGradient colors={["rgba(20,45,90,0.82)", "rgba(20,45,90,0.35)"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={StyleSheet.absoluteFill} />
            <View style={[styles.heroInner, { width: contentWidth }]}>
              <Text style={styles.crumb} onPress={() => router.push("/shop")}>← Back to home</Text>
              <View style={styles.heroBadge}><Text style={styles.heroBadgeText}>WEEKLY MEAL PLAN · {currentWeekLabel().toUpperCase()}</Text></View>
              <Text testID="mp-hero-title" style={[styles.heroTitle, { fontSize: isNarrow ? 30 : 44 }]}>
                Freshly cooked meals, delivered weekly.
              </Text>
              <Text style={styles.heroSub}>
                Build your own combo from this week&apos;s home-style Bengali menu — choose veg, non-veg or a mix.
              </Text>
              {pkg && (
                <TouchableOpacity testID="mp-hero-build" style={styles.ctaPrimary} onPress={primaryAction}>
                  <Text style={styles.ctaPrimaryText}>{primaryLabel}</Text>
                  <Ionicons name="arrow-forward" size={18} color="#fff" />
                </TouchableOpacity>
              )}
            </View>
          </View>
        </View>

        {loading ? (
          <ActivityIndicator color={BLUE} size="large" style={{ marginTop: 60 }} />
        ) : !pkg || !menu?.package_enabled ? (
          <View style={[styles.section, { width: contentWidth, alignItems: "center", paddingTop: 60 }]}>
            <Ionicons name="restaurant-outline" size={40} color={MUTE} />
            <Text style={styles.emptyTitle}>No meal plan is available this week.</Text>
            <Text style={styles.emptySub}>Please check back soon — or shop fresh groceries meanwhile.</Text>
            <TouchableOpacity style={styles.ctaPrimary} onPress={() => router.push("/shop/browse")}>
              <Text style={styles.ctaPrimaryText}>Shop groceries</Text>
              <Ionicons name="arrow-forward" size={18} color="#fff" />
            </TouchableOpacity>
          </View>
        ) : (
          <>
            {/* COMBO CARD */}
            <View style={[styles.section, { width: contentWidth }]}>
              <View style={styles.comboCard}>
                <Text style={styles.kicker}>{menu.title}</Text>
                <Text style={styles.comboName}>{pkg.name}</Text>
                <Text style={styles.comboDesc}>{pkg.description}</Text>
                {!isComp && (
                  <Text style={styles.flatPrice}>{centsToCAD(pkg.price_cents)} · for all {pkg.pick_count} items</Text>
                )}
                {isComp && (
                  <View style={[styles.tierRow, isNarrow && { flexDirection: "column" }]}>
                    {tiers.map(t => (
                      <View key={t.label} style={styles.tier} testID={`mp-tier-${t.label}`}>
                        <Text style={styles.tierLabel}>{t.label}</Text>
                        <Text style={styles.tierPrice}>{centsToCAD(t.price)}</Text>
                      </View>
                    ))}
                  </View>
                )}
                <TouchableOpacity testID="mp-combo-build" style={styles.ctaPrimaryDark} onPress={primaryAction}>
                  <Text style={styles.ctaPrimaryText}>{primaryLabel}</Text>
                  <Ionicons name="arrow-forward" size={18} color="#fff" />
                </TouchableOpacity>
              </View>
            </View>

            {/* COMPLIMENTARY */}
            {(menu.complimentary_items?.length ?? 0) > 0 && (
              <View style={[styles.section, { width: contentWidth }]}>
                <View style={styles.compCard}>
                  <View style={styles.compHead}>
                    <View style={styles.freeBadge}><Ionicons name="gift" size={11} color="#fff" /><Text style={styles.freeBadgeText}>FREE</Text></View>
                    <Text style={styles.compHeadText}>Complimentary this week — included with every plan</Text>
                  </View>
                  <View style={styles.compRow}>
                    {menu.complimentary_items!.map(c => (
                      <View key={c.item_id} style={styles.compItem} testID={`mp-comp-${c.item_id}`}>
                        {c.image_url
                          ? <Image source={{ uri: mediaUrl(c.image_url) }} style={styles.compImg} contentFit="cover" />
                          : <View style={[styles.compImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="gift-outline" size={20} color={GOLD} /></View>}
                        <Text style={styles.compName} numberOfLines={1}>{c.name}</Text>
                      </View>
                    ))}
                  </View>
                </View>
              </View>
            )}

            {/* VEGETARIAN */}
            {showDishes && !isFixedBundle && vegItems.length > 0 && (
              <View style={[styles.section, { width: contentWidth }]}>
                <View style={styles.groupHead}>
                  <View style={[styles.vegMark, { borderColor: VEG }]}><View style={[styles.vegDot, { backgroundColor: VEG }]} /></View>
                  <Text style={styles.groupHeadText}>Vegetarian</Text>
                  <Text style={styles.groupHeadCount}>{vegItems.length} dishes</Text>
                </View>
                <View style={styles.grid}>{vegItems.map(it => <DishCard key={it.item_id} it={it} />)}</View>
              </View>
            )}

            {/* NON-VEGETARIAN */}
            {showDishes && !isFixedBundle && nonVegItems.length > 0 && (
              <View style={[styles.section, { width: contentWidth }]}>
                <View style={styles.groupHead}>
                  <View style={[styles.vegMark, { borderColor: NONVEG }]}><View style={[styles.vegDot, { backgroundColor: NONVEG }]} /></View>
                  <Text style={styles.groupHeadText}>Non-Vegetarian</Text>
                  <Text style={styles.groupHeadCount}>{nonVegItems.length} dishes</Text>
                </View>
                <View style={styles.grid}>{nonVegItems.map(it => <DishCard key={it.item_id} it={it} />)}</View>
              </View>
            )}

            {/* FIXED BUNDLE: every dish below, pickers disabled, one order button */}
            {isFixedBundle && (
              <>
                {fixedVeg.length > 0 && (
                  <View style={[styles.section, { width: contentWidth }]}>
                    <View style={styles.groupHead}>
                      <View style={[styles.vegMark, { borderColor: VEG }]}><View style={[styles.vegDot, { backgroundColor: VEG }]} /></View>
                      <Text style={styles.groupHeadText}>Vegetarian</Text>
                      <Text style={styles.groupHeadCount}>{fixedVeg.length} dishes</Text>
                    </View>
                    <View style={{ gap: spacing.md }}>{fixedVeg.map(it => <FixedDishRow key={it.item_id} it={it} />)}</View>
                  </View>
                )}
                {fixedNonVeg.length > 0 && (
                  <View style={[styles.section, { width: contentWidth }]}>
                    <View style={styles.groupHead}>
                      <View style={[styles.vegMark, { borderColor: NONVEG }]}><View style={[styles.vegDot, { backgroundColor: NONVEG }]} /></View>
                      <Text style={styles.groupHeadText}>Non-Vegetarian</Text>
                      <Text style={styles.groupHeadCount}>{fixedNonVeg.length} dishes</Text>
                    </View>
                    <View style={{ gap: spacing.md }}>{fixedNonVeg.map(it => <FixedDishRow key={it.item_id} it={it} />)}</View>
                  </View>
                )}
              </>
            )}

            {/* BOTTOM CTA */}
            <View style={[styles.section, { width: contentWidth, alignItems: "center" }]}>
              <TouchableOpacity testID="mp-bottom-build" style={styles.ctaPrimaryDark} onPress={primaryAction}>
                <Text style={styles.ctaPrimaryText}>{isFixedBundle ? `Order this week's plan · ${centsToCAD(pkg.price_cents)}` : primaryLabel}</Text>
                <Ionicons name="arrow-forward" size={18} color="#fff" />
              </TouchableOpacity>
            </View>
          </>
        )}
        <ShopFooter />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  nav: { backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: "#F0E6D8", alignItems: "center", paddingBottom: 10, ...(Platform.OS === "web" ? { position: "sticky" as any, top: 0, zIndex: 20 } : {}), ...shadows.soft },
  navInner: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  logo: { width: 44, height: 44, borderRadius: 22, backgroundColor: "#fff", borderWidth: 2, borderColor: BLUE },
  brandName: { fontSize: 20, fontWeight: "900", color: INK, letterSpacing: -0.5 },
  navRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  navGhost: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, height: 40, borderRadius: radius.pill, borderWidth: 1, borderColor: "#E6D9C6" },
  navGhostText: { fontSize: 13, fontWeight: "700", color: INK },
  cartBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, height: 40, borderRadius: radius.pill, backgroundColor: RED },
  cartBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  cartDot: { position: "absolute", top: -4, right: -4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: GOLD, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  cartDotText: { color: "#1a1a1a", fontSize: 10, fontWeight: "900" },

  hero: { width: "100%", alignItems: "center", overflow: "hidden", minHeight: 320, justifyContent: "center" },
  heroInner: { paddingHorizontal: spacing.lg, paddingVertical: 44, gap: spacing.md, maxWidth: 720 },
  crumb: { color: "rgba(255,255,255,0.9)", fontWeight: "700", fontSize: 13 },
  heroBadge: { alignSelf: "flex-start", backgroundColor: "rgba(255,255,255,0.2)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill },
  heroBadgeText: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  heroTitle: { color: "#fff", fontWeight: "900", letterSpacing: -0.8, lineHeight: Platform.OS === "web" ? undefined : 40, maxWidth: 640 },
  heroSub: { color: "rgba(255,255,255,0.95)", fontSize: 16, maxWidth: 560 },
  ctaPrimary: { flexDirection: "row", alignItems: "center", gap: 8, alignSelf: "flex-start", backgroundColor: RED, paddingHorizontal: 26, height: 54, borderRadius: radius.pill, marginTop: spacing.sm, ...shadows.card },
  ctaPrimaryDark: { flexDirection: "row", alignItems: "center", gap: 8, alignSelf: "flex-start", backgroundColor: BLUE, paddingHorizontal: 26, height: 52, borderRadius: radius.pill, marginTop: spacing.md, ...shadows.card },
  ctaPrimaryText: { color: "#fff", fontWeight: "900", fontSize: 16 },

  section: { paddingHorizontal: spacing.lg, marginTop: spacing.xl },
  kicker: { color: RED, letterSpacing: 2, fontSize: 11, fontWeight: "900" },
  comboCard: { backgroundColor: "#fff", borderRadius: radius.xl, borderWidth: 1, borderColor: "#F0E6D8", padding: spacing.xl, gap: 8, ...shadows.soft },
  comboName: { fontSize: 28, fontWeight: "900", color: INK, letterSpacing: -0.5, marginTop: 2 },
  comboDesc: { fontSize: 15, color: MUTE, lineHeight: 22, maxWidth: 720 },
  flatPrice: { fontSize: 22, fontWeight: "900", color: BLUE, marginTop: 6 },
  tierRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.md },
  tier: { flex: 1, minWidth: 150, backgroundColor: CREAM, borderRadius: radius.lg, borderWidth: 1, borderColor: "#EBDFCE", paddingVertical: spacing.md, alignItems: "center", gap: 4 },
  tierLabel: { fontSize: 14, fontWeight: "800", color: INK },
  tierPrice: { fontSize: 20, fontWeight: "900", color: BLUE },

  compCard: { backgroundColor: "#FFFBEF", borderRadius: radius.xl, borderWidth: 1, borderColor: "#F3E4C0", padding: spacing.lg, gap: spacing.md },
  compHead: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  freeBadge: { flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: VEG, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  freeBadgeText: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 0.5 },
  compHeadText: { fontSize: 14, fontWeight: "800", color: INK, flexShrink: 1 },
  compRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  compItem: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fff", borderRadius: radius.pill, borderWidth: 1, borderColor: "#F3E4C0", paddingRight: 14, paddingVertical: 4, paddingLeft: 4 },
  compImg: { width: 40, height: 40, borderRadius: 20, backgroundColor: CREAM },
  compName: { fontSize: 14, fontWeight: "700", color: INK },

  groupHead: { flexDirection: "row", alignItems: "center", gap: 8, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: "#F0E6D8", marginBottom: spacing.md },
  groupHeadText: { fontSize: 18, fontWeight: "900", color: INK, letterSpacing: -0.3 },
  groupHeadCount: { fontSize: 12, fontWeight: "700", color: MUTE, marginLeft: "auto" },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  dish: { flexGrow: 1, flexBasis: 220, minWidth: 200, maxWidth: 300, backgroundColor: "#fff", borderRadius: radius.lg, borderWidth: 1, borderColor: "#F0E6D8", overflow: "hidden", ...shadows.soft },
  dishImgWrap: { width: "100%", aspectRatio: 16 / 10, backgroundColor: CREAM },
  dishImg: { width: "100%", height: "100%" },
  dishName: { fontSize: 15, fontWeight: "800", color: INK, flex: 1 },
  dishDesc: { fontSize: 12.5, color: MUTE, lineHeight: 18, minHeight: 36 },
  dishPrice: { fontSize: 13, fontWeight: "700", color: BLUE, marginTop: 2 },

  fixedRow: { flexDirection: "row", gap: spacing.md, alignItems: "center", backgroundColor: "#fff", borderRadius: radius.lg, borderWidth: 1, borderColor: "#F0E6D8", padding: spacing.md, ...shadows.soft },
  fixedImgWrap: { width: 96, height: 96, borderRadius: radius.md, overflow: "hidden", backgroundColor: CREAM },
  fixedImg: { width: "100%", height: "100%" },
  fixedIncluded: { fontSize: 12, fontWeight: "700", color: VEG, marginTop: 2 },
  fixedStepper: { flexDirection: "row", alignItems: "center", gap: 10 },
  fixedStepBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: CREAM, borderWidth: 1, borderColor: "#EBDFCE", alignItems: "center", justifyContent: "center" },
  fixedStepText: { fontSize: 18, fontWeight: "800", color: MUTE },
  fixedQty: { fontSize: 16, fontWeight: "900", color: INK },

  vegMark: { width: 16, height: 16, borderRadius: 3, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  vegDot: { width: 7, height: 7, borderRadius: 4 },

  emptyTitle: { fontSize: 18, fontWeight: "800", color: INK, marginTop: spacing.md, textAlign: "center" },
  emptySub: { fontSize: 14, color: MUTE, marginTop: 4, marginBottom: spacing.md, textAlign: "center" },
});
