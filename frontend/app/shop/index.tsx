import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView,
  useWindowDimensions, Platform,
} from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCart } from "@/src/cart";
import { api } from "@/src/api";
import { mediaUrl } from "@/src/utils/backendUrl";
import { BRAND } from "@/src/brand";
import { spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";
import { useComingSoon } from "@/src/hooks/use-coming-soon";
import { usePricingLocation } from "@/src/location";
import { ShopHeader } from "@/src/components/ShopHeader";
import { ShopFooter } from "@/src/components/ShopFooter";
import { PriceGate } from "@/src/components/PriceGate";
import type { Grocery } from "../(tabs)/groceries";

type AnytimeItem = { item_id: string; name: string; description?: string; price_cents: number; image_url?: string };

// —— Retail portal palette (derived from the logo: navy blue, red, gold) ——
const BLUE = "#1E5AA8";        // lightened brand blue
const RED = "#D62828";         // logo red — primary CTAs / sale
const GOLD = "#F2A81C";        // gold accent
const CREAM = "#FFF8F0";       // warm retail background
const INK = "#1F2D45";         // headings on light
const MUTE = "#6B7280";        // muted text

const CIRCLE_LOGO = require("@/assets/brand/logo-circle.png");
const HERO_IMG = require("@/assets/brand/hero-fresh.jpg");
const TILE_GROCERY = require("@/assets/brand/tile-grocery.jpg");
const TILE_MEAL = require("@/assets/brand/tile-meal.jpg");
const TILE_THALI = require("@/assets/brand/tile-thali.jpg");

function LogoCircle({ size, border = 3 }: { size: number; border?: number }) {
  return (
    <View style={[styles.logoCircle, { width: size, height: size, borderRadius: size / 2, borderWidth: border }]}>
      <Image source={CIRCLE_LOGO} style={{ width: size - border * 2, height: size - border * 2 }} contentFit="contain" />
    </View>
  );
}

export default function ShopHome() {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { add } = useCart();
  const [featured, setFeatured] = useState<Grocery[]>([]);  const [anytime, setAnytime] = useState<AnytimeItem[]>([]);
  const comingSoon = useComingSoon();
  const { postal, gated, showHelp } = usePricingLocation();
  const isNarrow = width < 900;
  const contentWidth = Math.min(width, 1200);

  const scrollRef = useRef<ScrollView>(null);
  const aboutY = useRef(0);
  const deliveryY = useRef(0);

  useEffect(() => {
    (async () => {
      const [fr, ar] = await Promise.all([
        api.get<{ items: Grocery[] }>(`/grocery?featured=true&limit=12${postal ? `&postal=${encodeURIComponent(postal)}` : ""}`),
        api.get<AnytimeItem[]>("/menu/anytime"),
      ]);
      setFeatured(fr.ok ? fr.data.items || [] : []);
      setAnytime(ar.ok ? ar.data || [] : []);
    })();
  }, [postal]);

  const goBrowse = (category?: string) =>
    router.push(category ? { pathname: "/shop/browse", params: { category } } : "/shop/browse");
  const goMealPlans = () => router.push("/shop/meal-plans");

  const scrollTo = (y: number) => scrollRef.current?.scrollTo({ y: Math.max(0, y - 70), animated: true });

  const onAddFeatured = (g: Grocery) => {
    if (g.has_variants) { router.push(`/shop/product/${g.item_id}`); return; }
    add({ kind: "grocery" as any, ref_id: g.item_id, name: g.title, price_cents: g.price_cents, image_url: g.image_url, category: g.category, subcategory: (g as any).subcategory });
  };

  const onAddAnytime = (it: AnytimeItem) =>
    add({ kind: "menu" as any, ref_id: it.item_id, name: it.name, price_cents: it.price_cents, image_url: it.image_url });

  return (
    <View style={{ flex: 1, backgroundColor: CREAM }}>
      <ShopHeader
        active="home"
        navHandlers={{
          home: () => scrollRef.current?.scrollTo({ y: 0, animated: true }),
          about: () => scrollTo(aboutY.current),
          delivery: () => scrollTo(deliveryY.current),
        }}
      />

      <ScrollView ref={scrollRef} contentContainerStyle={{ paddingBottom: 40 + insets.bottom, alignItems: "center" }}>
        {/* HERO */}
        <View style={{ width: "100%", alignItems: "center", backgroundColor: BLUE }}>
          <View style={styles.hero}>
            <Image source={HERO_IMG} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
            <LinearGradient colors={["rgba(30,90,168,0.5)", "rgba(62,134,214,0.34)"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={StyleSheet.absoluteFill} />
            <View style={[styles.heroInner, { width: contentWidth, flexDirection: isNarrow ? "column" : "row", paddingVertical: isNarrow ? spacing.xl : 56 }]}>
              <View style={[styles.heroLogoWrap, isNarrow && { marginBottom: spacing.lg }]}>
                <LogoCircle size={isNarrow ? 168 : 250} border={6} />
              </View>
              <View style={[styles.heroText, { alignItems: isNarrow ? "center" : "flex-start" }]}>
                <View style={styles.heroBadge}><Text style={styles.heroBadgeText}>HALAL · FRESH · DELIVERED</Text></View>
                <Text testID="hero-title" style={[styles.heroTitle, { fontSize: isNarrow ? 30 : 46, textAlign: isNarrow ? "center" : "left" }]}>Your neighbourhood halal grocery — delivered.</Text>
                <Text style={[styles.heroSub, { textAlign: isNarrow ? "center" : "left" }]}>Fresh meat, fish, sweets & everyday groceries. Free delivery on orders over $150 across {BRAND.region.serviceArea}.</Text>
                <View style={[styles.heroBtns, { justifyContent: isNarrow ? "center" : "flex-start" }]}>
                  <TouchableOpacity testID="hero-order-now" style={styles.ctaPrimary} onPress={() => goBrowse()}>
                    <Text style={styles.ctaPrimaryText}>Order Now</Text>
                    <Ionicons name="arrow-forward" size={18} color="#fff" />
                  </TouchableOpacity>
                  <TouchableOpacity testID="hero-mealplans" style={styles.ctaGhost} onPress={goMealPlans}>
                    <Text style={styles.ctaGhostText}>Explore Meal Plans</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>
          </View>
        </View>

        {/* TWO TILES */}
        <View style={[styles.section, { width: contentWidth }]}>
          <View style={[styles.tileRow, isNarrow && { flexDirection: "column" }]}>
            <TouchableOpacity testID="tile-grocery" activeOpacity={0.9} style={styles.tile} onPress={() => goBrowse()}>
              <Image source={TILE_GROCERY} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
              <LinearGradient colors={["rgba(30,90,168,0.1)", "rgba(30,90,168,0.8)"]} start={{ x: 0, y: 0 }} end={{ x: 0, y: 1 }} style={StyleSheet.absoluteFill} />
              <View style={styles.tileBody}>
                <View style={styles.tileIcon}><Ionicons name="basket" size={26} color="#fff" /></View>
                <Text style={styles.tileTitle}>Halal Meat, Fish & Grocery</Text>
                <Text style={styles.tileSub}>Daily groceries, fresh cuts & seafood</Text>
                <View style={styles.tileCta}><Text style={styles.tileCtaText}>Shop now</Text><Ionicons name="arrow-forward" size={15} color="#fff" /></View>
              </View>
            </TouchableOpacity>
            <TouchableOpacity testID="tile-mealplan" activeOpacity={0.9} style={styles.tile} onPress={goMealPlans}>
              <Image source={TILE_MEAL} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
              <LinearGradient colors={["rgba(214,40,40,0.1)", "rgba(191,30,30,0.82)"]} start={{ x: 0, y: 0 }} end={{ x: 0, y: 1 }} style={StyleSheet.absoluteFill} />
              <View style={styles.tileBody}>
                <View style={styles.tileIcon}><Ionicons name="restaurant" size={26} color="#fff" /></View>
                <Text style={styles.tileTitle}>Meal Plans</Text>
                <Text style={styles.tileSub}>Weekly cooked meals & party combos</Text>
                <View style={styles.tileCta}><Text style={styles.tileCtaText}>Explore plans</Text><Ionicons name="arrow-forward" size={15} color="#fff" /></View>
              </View>
            </TouchableOpacity>
            <TouchableOpacity testID="tile-thali" activeOpacity={0.9} style={styles.tile} onPress={() => router.push("/shop/thali")}>
              <Image source={TILE_THALI} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
              <LinearGradient colors={["rgba(242,168,28,0.12)", "rgba(201,120,10,0.82)"]} start={{ x: 0, y: 0 }} end={{ x: 0, y: 1 }} style={StyleSheet.absoluteFill} />
              <View style={styles.tileBody}>
                <View style={styles.tileIcon}><Ionicons name="fast-food" size={26} color="#fff" /></View>
                <Text style={styles.tileTitle}>Thali Party Order</Text>
                <Text style={styles.tileSub}>Bulk thalis for parties & events</Text>
                <View style={styles.tileCta}><Text style={styles.tileCtaText}>Order thalis</Text><Ionicons name="arrow-forward" size={15} color="#fff" /></View>
              </View>
            </TouchableOpacity>
          </View>
        </View>

        {/* BEST SELLERS */}
        {featured.length > 0 && (
          <View style={[styles.section, { width: contentWidth }]}>
            <View style={styles.sectionHead}>
              <View>
                <Text style={styles.kicker}>HANDPICKED</Text>
                <Text style={styles.sectionTitle}>Best Sellers & New Items</Text>
              </View>
              <TouchableOpacity onPress={() => goBrowse()}><Text style={styles.seeAll}>See all →</Text></TouchableOpacity>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.md, paddingHorizontal: spacing.lg }}>
              {featured.map((g) => (
                <TouchableOpacity key={g.item_id} testID={`featured-${g.item_id}`} activeOpacity={0.85} style={styles.fCard} onPress={() => router.push(`/shop/product/${g.item_id}`)}>
                  <View style={styles.fImgWrap}>
                    {g.image_url ? <Image source={{ uri: mediaUrl(g.image_url) }} style={styles.fImg} contentFit="cover" transition={200} /> : <View style={[styles.fImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="image-outline" size={26} color={MUTE} /></View>}
                    {g.compare_at_cents > g.price_cents && <View style={styles.saleTag}><Text style={styles.saleTagText}>SALE</Text></View>}
                  </View>
                  <View style={{ padding: spacing.md, gap: 4 }}>
                    <Text style={styles.fName} numberOfLines={2}>{g.title}</Text>
                    <PriceGate compact><Text style={styles.fPrice}>{g.has_variants ? "from " : ""}{centsToCAD(g.price_cents)}</Text></PriceGate>
                    {gated ? (
                      <TouchableOpacity testID={`featured-enable-loc-${g.item_id}`} style={[styles.fAdd, styles.fAddComing]} onPress={showHelp}>
                        <Ionicons name="location-outline" size={14} color={INK} />
                        <Text style={[styles.fAddText, { color: INK }]}>Enable location</Text>
                      </TouchableOpacity>
                    ) : (
                      <TouchableOpacity testID={`featured-add-${g.item_id}`} disabled={comingSoon} style={[styles.fAdd, comingSoon && styles.fAddComing]} onPress={() => !comingSoon && onAddFeatured(g)}>
                        <Ionicons name={comingSoon ? "time-outline" : (g.has_variants ? "options-outline" : "cart")} size={14} color={comingSoon ? MUTE : "#fff"} />
                        <Text style={[styles.fAddText, comingSoon && { color: MUTE }]}>{comingSoon ? "Coming soon" : (g.has_variants ? "Options" : "Add")}</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        )}

        {/* ALWAYS AVAILABLE */}
        {anytime.length > 0 && (
          <View style={[styles.section, { width: contentWidth }]} testID="shop-anytime">
            <View style={styles.sectionHead}>
              <View>
                <Text style={styles.kicker}>ORDER ANY TIME</Text>
                <Text style={styles.sectionTitle}>Always Available</Text>
              </View>
              <TouchableOpacity testID="shop-anytime-mealplans" onPress={goMealPlans}><Text style={styles.seeAll}>Meal plans →</Text></TouchableOpacity>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.md, paddingHorizontal: spacing.lg }}>
              {anytime.map((it) => (
                <View key={it.item_id} testID={`shop-anytime-${it.item_id}`} style={styles.fCard}>
                  <View style={styles.fImgWrap}>
                    {it.image_url ? <Image source={{ uri: mediaUrl(it.image_url) }} style={styles.fImg} contentFit="cover" transition={200} /> : <View style={[styles.fImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="fast-food-outline" size={26} color={MUTE} /></View>}
                  </View>
                  <View style={{ padding: spacing.md, gap: 4 }}>
                    <Text style={styles.fName} numberOfLines={2}>{it.name}</Text>
                    <Text style={styles.fPrice}>{centsToCAD(it.price_cents)}</Text>
                    <TouchableOpacity testID={`shop-anytime-add-${it.item_id}`} style={styles.fAdd} onPress={() => onAddAnytime(it)}>
                      <Ionicons name="cart" size={14} color="#fff" />
                      <Text style={styles.fAddText}>Add</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ))}
            </ScrollView>
          </View>
        )}

        {/* ABOUT US */}
        <View onLayout={e => (aboutY.current = e.nativeEvent.layout.y)} style={[styles.section, { width: contentWidth }]}>
          <View style={styles.aboutCard}>
            <Text style={styles.kicker}>ABOUT US</Text>
            <Text style={styles.aboutTitle}>Bringing home the taste of Bengal to {BRAND.region.serviceArea}</Text>
            <Text style={styles.aboutText}>{BRAND.name} is your trusted online halal grocery — sourcing fresh fish, meat, sweets, spices and daily essentials the community loves, and delivering them straight to your door.</Text>
            <View style={[styles.perkRow, isNarrow && { flexDirection: "column" }]}>
              {[["shield-checkmark", "100% Halal Certified"], ["leaf", "Fresh, Quality Sourced"], ["pricetags", "Everyday Low Prices"], ["heart", "Community Trusted"]].map(([ic, t]) => (
                <View key={t} style={styles.perk}>
                  <View style={styles.perkIcon}><Ionicons name={ic as any} size={20} color={BLUE} /></View>
                  <Text style={styles.perkText}>{t}</Text>
                </View>
              ))}
            </View>
          </View>
        </View>

        {/* DELIVERY */}
        <View onLayout={e => (deliveryY.current = e.nativeEvent.layout.y)} style={[styles.section, { width: contentWidth }]}>
          <View style={styles.deliveryCard}>
            <View style={{ flex: 1, gap: 8 }}>
              <Text style={[styles.kicker, { color: GOLD }]}>DELIVERY</Text>
              <Text style={styles.deliveryTitle}>Fast, careful delivery across the GTA</Text>
              <View style={{ gap: 8, marginTop: 6 }}>
                {[["cube-outline", "Free delivery on orders over $150"], ["time-outline", "Choose a convenient delivery slot at checkout"], ["snow-outline", "Frozen & fresh items packed cold"], ["location-outline", `Serving ${BRAND.region.serviceArea}`]].map(([ic, t]) => (
                  <View key={t} style={styles.dRow}>
                    <Ionicons name={ic as any} size={18} color="#fff" />
                    <Text style={styles.dText}>{t}</Text>
                  </View>
                ))}
              </View>
              <TouchableOpacity testID="delivery-cta" style={styles.deliveryCta} onPress={() => goBrowse()}>
                <Text style={styles.deliveryCtaText}>Start your order</Text>
                <Ionicons name="arrow-forward" size={16} color={BLUE} />
              </TouchableOpacity>
            </View>
          </View>
        </View>

        {/* SKIP THE HASSLE */}
        <View style={[styles.section, { width: contentWidth }]}>
          <View style={[styles.hassle, isNarrow && { flexDirection: "column" }]}>
            <View style={styles.hassleLeft}>
              <Text style={styles.kicker}>WHY {BRAND.name.toUpperCase()}</Text>
              <Text style={styles.hassleTitle}>Skip the grocery store hassle</Text>
              <Text style={styles.hassleSub}>Save time, eat better. Get fresh, halal-certified ingredients delivered straight to your door — no lines, no parking, no stress.</Text>
              <TouchableOpacity testID="hassle-cta" style={styles.hassleCta} onPress={() => goBrowse()}>
                <Text style={styles.hassleCtaText}>Start shopping now</Text>
                <Ionicons name="arrow-forward" size={16} color="#fff" />
              </TouchableOpacity>
            </View>
            <View style={[styles.hassleRight, isNarrow && { width: "100%", height: 220 }]}>
              <Image source={HERO_IMG} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
            </View>
          </View>
        </View>

        {/* FOOTER */}
        <ShopFooter />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  announce: { backgroundColor: RED, alignItems: "center", justifyContent: "center", paddingVertical: 7, paddingHorizontal: spacing.lg },
  announceText: { color: "#fff", fontSize: 12.5, fontWeight: "700", letterSpacing: 0.2 },

  logoCircle: { backgroundColor: "#fff", borderColor: BLUE, alignItems: "center", justifyContent: "center", overflow: "hidden" },

  nav: { backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: "#F0E6D8", alignItems: "center", ...(Platform.OS === "web" ? { position: "sticky" as any, top: 0, zIndex: 20 } : {}), ...shadows.soft },
  navInner: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: 10 },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  brandName: { fontSize: 21, fontWeight: "900", color: INK, letterSpacing: -0.5 },
  navLinks: { flexDirection: "row", alignItems: "center", gap: 4 },
  navLinkBtn: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
  navLinkText: { fontSize: 14.5, fontWeight: "700", color: INK },
  navRight: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  navGhost: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, height: 40, borderRadius: radius.pill, borderWidth: 1, borderColor: "#E6D9C6" },
  navGhostText: { fontSize: 13, fontWeight: "700", color: INK },
  cartBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, height: 40, borderRadius: radius.pill, backgroundColor: RED },
  cartBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  cartDot: { position: "absolute", top: -4, right: -4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: GOLD, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  cartDotText: { color: "#1a1a1a", fontSize: 10, fontWeight: "900" },
  navScroll: { gap: 8, paddingHorizontal: spacing.lg, paddingBottom: 10, alignItems: "center" },
  navChip: { paddingHorizontal: 14, height: 34, borderRadius: radius.pill, backgroundColor: CREAM, borderWidth: 1, borderColor: "#EBDFCE", alignItems: "center", justifyContent: "center" },
  navChipText: { fontSize: 13, fontWeight: "700", color: INK },

  hero: { width: "100%", alignItems: "center", overflow: "hidden", minHeight: 340, justifyContent: "center" },
  heroInner: { alignItems: "center", paddingHorizontal: spacing.lg, gap: spacing.xl },
  heroLogoWrap: { alignItems: "center", justifyContent: "center" },
  heroText: { flex: 1, gap: spacing.md, maxWidth: 640 },
  heroBadge: { backgroundColor: "rgba(255,255,255,0.2)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill },
  heroBadgeText: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  heroTitle: { color: "#fff", fontWeight: "900", letterSpacing: -0.8, lineHeight: Platform.OS === "web" ? undefined : 40 },
  heroSub: { color: "rgba(255,255,255,0.95)", fontSize: 16, maxWidth: 540 },
  heroBtns: { flexDirection: "row", gap: spacing.md, marginTop: spacing.sm, flexWrap: "wrap" },
  ctaPrimary: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: RED, paddingHorizontal: 26, height: 54, borderRadius: radius.pill, ...shadows.card },
  ctaPrimaryText: { color: "#fff", fontWeight: "900", fontSize: 16 },
  ctaGhost: { flexDirection: "row", alignItems: "center", paddingHorizontal: 24, height: 54, borderRadius: radius.pill, borderWidth: 2, borderColor: "#fff", backgroundColor: "rgba(255,255,255,0.12)" },
  ctaGhostText: { color: "#fff", fontWeight: "800", fontSize: 15 },

  quickRow: { gap: 8, paddingHorizontal: spacing.lg, paddingVertical: 14 },
  quickChip: { flexShrink: 0, paddingHorizontal: 16, height: 38, borderRadius: radius.pill, backgroundColor: CREAM, borderWidth: 1, borderColor: "#EBDFCE", alignItems: "center", justifyContent: "center" },
  quickChipText: { fontSize: 13.5, fontWeight: "800", color: BLUE },

  section: { paddingHorizontal: spacing.lg, marginTop: spacing.xl },
  tileRow: { flexDirection: "row", gap: spacing.lg },
  tile: { flex: 1, minHeight: 210, borderRadius: radius.xl, overflow: "hidden", backgroundColor: BLUE, ...shadows.card },
  tileBody: { flex: 1, padding: spacing.xl, justifyContent: "flex-end", gap: 6 },
  tileIcon: { width: 48, height: 48, borderRadius: radius.pill, backgroundColor: "rgba(255,255,255,0.24)", alignItems: "center", justifyContent: "center", marginBottom: 6 },
  tileTitle: { color: "#fff", fontSize: 22, fontWeight: "900", letterSpacing: -0.4 },
  tileSub: { color: "rgba(255,255,255,0.92)", fontSize: 14 },
  tileCta: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8 },
  tileCtaText: { color: "#fff", fontWeight: "800", fontSize: 14 },

  sectionHead: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between", paddingHorizontal: spacing.lg, marginBottom: spacing.md },
  kicker: { color: RED, letterSpacing: 2, fontSize: 11, fontWeight: "900" },
  sectionTitle: { fontSize: 24, fontWeight: "900", color: INK, letterSpacing: -0.5, marginTop: 2 },
  seeAll: { color: BLUE, fontWeight: "800" },
  fCard: { width: 190, backgroundColor: "#fff", borderRadius: radius.lg, borderWidth: 1, borderColor: "#F0E6D8", overflow: "hidden", ...shadows.soft },
  fImgWrap: { width: "100%", aspectRatio: 1, backgroundColor: CREAM },
  fImg: { width: "100%", height: "100%" },
  saleTag: { position: "absolute", top: 8, left: 8, backgroundColor: RED, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  saleTagText: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  fName: { fontSize: 13, fontWeight: "700", color: INK, minHeight: 34 },
  fPrice: { fontSize: 16, fontWeight: "800", color: BLUE },
  fAdd: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, backgroundColor: RED, borderRadius: radius.pill, paddingVertical: 9, marginTop: 4 },
  fAddComing: { backgroundColor: "#F0E6D8" },
  fAddText: { color: "#fff", fontSize: 12, fontWeight: "800" },

  aboutCard: { backgroundColor: "#fff", borderRadius: radius.xl, borderWidth: 1, borderColor: "#F0E6D8", padding: spacing.xl, gap: 8, ...shadows.soft },
  aboutTitle: { fontSize: 26, fontWeight: "900", color: INK, letterSpacing: -0.5, maxWidth: 640 },
  aboutText: { fontSize: 15, color: MUTE, lineHeight: 22, maxWidth: 680 },
  perkRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.md, flexWrap: "wrap" },
  perk: { flex: 1, minWidth: 200, flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: CREAM, borderRadius: radius.md, padding: spacing.md },
  perkIcon: { width: 40, height: 40, borderRadius: radius.pill, backgroundColor: "#E9F1FB", alignItems: "center", justifyContent: "center" },
  perkText: { fontSize: 14, fontWeight: "800", color: INK, flex: 1 },

  deliveryCard: { backgroundColor: BLUE, borderRadius: radius.xl, padding: spacing.xl, overflow: "hidden", ...shadows.card },
  deliveryTitle: { fontSize: 26, fontWeight: "900", color: "#fff", letterSpacing: -0.5 },
  dRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  dText: { color: "rgba(255,255,255,0.95)", fontSize: 15, fontWeight: "600" },
  deliveryCta: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fff", alignSelf: "flex-start", paddingHorizontal: 20, height: 48, borderRadius: radius.pill, marginTop: spacing.md },
  deliveryCtaText: { color: BLUE, fontWeight: "900", fontSize: 15 },

  hassle: { flexDirection: "row", borderRadius: radius.xl, overflow: "hidden", minHeight: 260, backgroundColor: BLUE, ...shadows.card },
  hassleLeft: { flex: 1, padding: spacing.xl, gap: 10, justifyContent: "center" },
  hassleRight: { flex: 1, backgroundColor: CREAM },
  hassleTitle: { color: "#fff", fontSize: 30, fontWeight: "900", letterSpacing: -0.5 },
  hassleSub: { color: "rgba(255,255,255,0.92)", fontSize: 15, lineHeight: 22, maxWidth: 460 },
  hassleCta: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: RED, alignSelf: "flex-start", paddingHorizontal: 22, height: 50, borderRadius: radius.pill, marginTop: 8 },
  hassleCtaText: { color: "#fff", fontWeight: "900", fontSize: 15 },

  footer: { backgroundColor: "#fff", borderTopWidth: 1, borderTopColor: "#F0E6D8", alignItems: "center", paddingVertical: spacing.xl, marginTop: spacing.xl },
  footBrand: { fontSize: 20, fontWeight: "900", color: INK, marginTop: 6 },
  footText: { fontSize: 13, color: MUTE },
  footLinks: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap", justifyContent: "center" },
  footLink: { color: BLUE, fontWeight: "700", fontSize: 13 },
  footDot: { color: MUTE },
  footCopy: { fontSize: 12, color: MUTE, marginTop: 10 },
});
