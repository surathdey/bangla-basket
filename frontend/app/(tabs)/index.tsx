import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ImageBackground,
  ActivityIndicator, RefreshControl, Image, Platform, useWindowDimensions,
} from "react-native";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/auth";
import { useCart } from "@/src/cart";
import { api } from "@/src/api";
import { mediaUrl } from "@/src/utils/backendUrl";
import { colors, spacing, radius, shadows } from "@/src/theme";
import { centsToCAD, isOrderingWindow, upcomingDeliveryDates } from "@/src/utils/format";
import { LocationBanner } from "@/src/components/LocationBanner";
import { PriceGate } from "@/src/components/PriceGate";

const CIRCLE_LOGO = require("@/assets/brand/logo-circle.png");

type MenuItem = {
  item_id: string; name: string; description: string;
  price_cents: number; image_url: string; category: string; tags: string[]; is_featured: boolean;
};
type WeeklyPkg = {
  package_id?: string; name: string; description?: string; price_cents: number;
  pick_count: number; eligible_master_ids: string[]; image_url?: string;
};
type Compl = { item_id: string; name: string; description: string; image_url: string; category: string; };
type WeeklyMenu = {
  menu_id: string; week_start: string; title: string; items: MenuItem[];
  alacarte_enabled?: boolean; package_enabled?: boolean; package?: WeeklyPkg | null;
  complimentary_items?: Compl[];
};
type Grocery = { item_id: string; title: string; price_cents: number; image_url: string; has_variants?: boolean; };

export default function HomeScreen() {
  const { user } = useAuth();
  const { add, count } = useCart();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const [current, setCurrent] = useState<WeeklyMenu | null>(null);
  const [upcoming, setUpcoming] = useState<WeeklyMenu[]>([]);
  const [bestSellers, setBestSellers] = useState<Grocery[]>([]);
  const [newItems, setNewItems] = useState<Grocery[]>([]);
  const [anytime, setAnytime] = useState<MenuItem[]>([]);
  const [orderingDays, setOrderingDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [deliveryDays, setDeliveryDays] = useState<number[]>([5, 6]);
  const [sections, setSections] = useState<{ best: boolean; newItems: boolean }>({ best: true, newItems: true });
  // Tagline shown in the customer hero — explains the "order all week,
  // deliver on X" model in one line. Configurable per tenant via
  // Admin → Settings → home_hero_tagline.
  const [heroTitle, setHeroTitle] = useState<string>("Your neighbourhood halal grocery — delivered.");
  const [heroSubtitle, setHeroSubtitle] = useState<string>("Fresh meat, fish, sweets & everyday groceries, delivered to your door.");
  const [ribbon, setRibbon] = useState<{ enabled: boolean; text: string }>({ enabled: true, text: "Free delivery on orders over $150" });
  const [locBanner, setLocBanner] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const window = isOrderingWindow(orderingDays);
  const deliveryDrops = upcomingDeliveryDates(deliveryDays);

  const load = async () => {
    const [c, u, best, fresh, st, any] = await Promise.all([
      api.get<WeeklyMenu>("/menu/current"),
      api.get<WeeklyMenu[]>("/menu/upcoming"),
      api.get<{ items: Grocery[] }>("/grocery?featured=true&limit=10"),
      api.get<{ items: Grocery[] }>("/grocery?sort=newest&limit=10"),
      api.get<{ ordering_days?: number[]; delivery_days?: number[]; home_hero_tagline?: string; home_hero_title?: string; home_hero_subtitle?: string; delivery_ribbon_enabled?: boolean; delivery_ribbon_text?: string; home_best_sellers_enabled?: boolean; home_new_items_enabled?: boolean; location_banner_enabled?: boolean }>("/settings"),
      api.get<MenuItem[]>("/menu/anytime"),
    ]);
    if (c.ok) setCurrent(c.data);
    if (u.ok) setUpcoming(Array.isArray(u.data) ? u.data : []);
    if (best.ok) setBestSellers(Array.isArray((best.data as any)?.items) ? (best.data as any).items : []);
    if (fresh.ok) setNewItems(Array.isArray((fresh.data as any)?.items) ? (fresh.data as any).items : []);
    if (any.ok) setAnytime(Array.isArray(any.data) ? any.data : []);
    if (st.ok) {
      if (Array.isArray(st.data?.ordering_days)) setOrderingDays(st.data.ordering_days as number[]);
      if (Array.isArray(st.data?.delivery_days)) setDeliveryDays(st.data.delivery_days as number[]);
      if (typeof st.data?.home_hero_title === "string" && st.data.home_hero_title.trim()) {
        setHeroTitle(st.data.home_hero_title.trim());
      }
      if (typeof st.data?.home_hero_subtitle === "string" && st.data.home_hero_subtitle.trim()) {
        setHeroSubtitle(st.data.home_hero_subtitle.trim());
      }
      setRibbon({
        enabled: st.data?.delivery_ribbon_enabled !== false,
        text: (st.data?.delivery_ribbon_text || "Free delivery on orders over $150").trim(),
      });
      setSections({
        best: st.data?.home_best_sellers_enabled !== false,
        newItems: st.data?.home_new_items_enabled !== false,
      });
      setLocBanner(st.data?.location_banner_enabled === true);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  // Auto-live updates: while the Home screen is mounted, re-fetch the menu every
  // 15s so admin changes (complimentary / always-available / visibility) show up
  // without the customer manually refreshing.
  useEffect(() => {
    const id = setInterval(() => { load(); }, 15000);
    return () => clearInterval(id);
  }, []);

  const onRefresh = async () => {
    setRefreshing(true); await load(); setRefreshing(false);
  };

  const featured = current?.items?.filter(i => i.is_featured).slice(0, 3) || [];
  const rest = current?.items?.filter(i => !i.is_featured) || [];

  if (loading) {
    return (
      <View style={styles.centerFill}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <LocationBanner enabled={locBanner} topInset={insets.top} />
      {ribbon.enabled && !!ribbon.text && (
        <View style={[styles.ribbon, { paddingTop: (locBanner ? 6 : insets.top + 6) }]} testID="home-delivery-ribbon">
          <Ionicons name="bicycle" size={14} color="#fff" />
          <Text style={styles.ribbonText} numberOfLines={1}>{ribbon.text}</Text>
        </View>
      )}
      <ScrollView
        testID="home-scroll"
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: 120 + insets.bottom }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        {/* Hero */}
        <ImageBackground
          source={require("@/assets/brand/hero-fresh.jpg")}
          style={[styles.hero, { paddingTop: (ribbon.enabled || locBanner) ? 14 : insets.top + 12 }]}
          resizeMode="cover"
        >
          <LinearGradient colors={["rgba(0,0,0,0.25)", "rgba(0,0,0,0.85)"]} style={StyleSheet.absoluteFill} />
          <SafeAreaView edges={(ribbon.enabled || locBanner) ? [] : ["top"]} style={{ position: "absolute", top: 0, left: 0, right: 0 }}>
            <View style={styles.topRow}>
              <View>
                <Text style={styles.hello} testID="home-hello">Namaskar,</Text>
                <Text style={styles.userName}>{user?.name?.split(" ")[0] || "Friend"}</Text>
              </View>
              <TouchableOpacity
                testID="home-cart-button"
                style={styles.cartBtn}
                onPress={() => router.push("/(tabs)/orders")}
              >
                <Ionicons name="bag-handle-outline" size={22} color="#fff" />
                {count > 0 && <View style={styles.cartDot}><Text style={styles.cartDotText}>{count}</Text></View>}
              </TouchableOpacity>
            </View>
          </SafeAreaView>

          <View style={styles.heroBottom}>
            <Image source={CIRCLE_LOGO} style={styles.heroLogo} resizeMode="contain" />
            <Text style={styles.heroTitle} testID="home-hero-brand" numberOfLines={3}>{heroTitle}</Text>
            <Text style={styles.heroSubtitle} testID="home-hero-tagline">{heroSubtitle}</Text>
            <View style={styles.chipRow}>
              <View style={[styles.windowChip, { backgroundColor: window.open ? colors.success : "#444" }]}>
                <Ionicons name={window.open ? "checkmark-circle" : "time"} size={14} color="#fff" />
                <Text style={styles.windowChipText}>{window.note}</Text>
              </View>
              {deliveryDrops.length > 0 && (
                <View style={[styles.windowChip, styles.deliveryChip]} testID="home-next-delivery">
                  <Ionicons name="bicycle" size={14} color="#fff" />
                  <Text style={styles.deliveryChipText}>Next delivery · {deliveryDrops.map(d => d.label).join("  &  ")}</Text>
                </View>
              )}
            </View>
          </View>
        </ImageBackground>

        {/* Weekly Package hero */}
        {current?.package_enabled && current.package && (
          <TouchableOpacity
            testID="home-pkg-hero"
            activeOpacity={0.9}
            onPress={() => router.push(`/menu/package/${current.menu_id}`)}
            style={styles.pkgHomeHero}
          >
            <ImageBackground
              source={{ uri: mediaUrl(current.package.image_url || current.items?.[0]?.image_url) }}
              style={styles.pkgHomeHeroImg}
              imageStyle={{ borderRadius: radius.xl }}
            >
              <LinearGradient
                colors={["rgba(0,0,0,0.15)", "rgba(0,0,0,0.85)"]}
                style={[StyleSheet.absoluteFill, { borderRadius: radius.xl }]}
              />
              <View style={styles.pkgHomeHeroBadge}>
                <Ionicons name="gift" size={11} color="#fff" />
                <Text style={styles.pkgHomeHeroBadgeText}>WEEKLY COMBO</Text>
              </View>
              <View style={styles.pkgHomeHeroBody}>
                <Text style={styles.pkgHomeHeroName}>{current.package.name}</Text>
                <Text style={styles.pkgHomeHeroSub} numberOfLines={2}>
                  {current.package.description || `Build your combo — pick ${current.package.pick_count} dishes.`}
                </Text>
                {(current.complimentary_items?.length ?? 0) > 0 && (
                  <View style={styles.comboComp} testID="home-combo-complimentary">
                    <View style={styles.comboCompHead}>
                      <View style={styles.freeBadge}>
                        <Ionicons name="gift" size={10} color="#fff" />
                        <Text style={styles.freeBadgeText}>FREE</Text>
                      </View>
                      <Text style={styles.comboCompLabel}>COMPLIMENTARY THIS WEEK</Text>
                    </View>
                    <Text style={styles.comboCompNames} numberOfLines={2}>
                      {current.complimentary_items!.slice(0, 3).map((c) => c.name).join("   •   ")}
                    </Text>
                  </View>
                )}
                <View style={styles.pkgHomeHeroRow}>
                  {(() => {
                    const p: any = current.package;
                    const isComp = p.pricing_mode === "composition";
                    const minP = isComp
                      ? Math.min(p.veg_price_cents || 0, p.mixed_price_cents || 0, p.nonveg_price_cents || 0)
                      : p.price_cents;
                    return (
                      <View>
                        <Text style={styles.pkgHomeHeroPrice}>{isComp ? `from ${centsToCAD(minP)}` : centsToCAD(p.price_cents)}</Text>
                        <Text style={styles.pkgHomeHeroPriceSub}>{isComp ? `pick ${p.pick_count} · by veg / non-veg mix` : `pick ${p.pick_count} dishes · flat price`}</Text>
                      </View>
                    );
                  })()}
                  <View style={styles.pkgHomeHeroCta}>
                    <Text style={styles.pkgHomeHeroCtaText}>Build combo</Text>
                    <Ionicons name="arrow-forward" size={14} color="#fff" />
                  </View>
                </View>
              </View>
            </ImageBackground>
          </TouchableOpacity>
        )}

        {/* Shop Grocery tile — jump straight into the grocery catalog (below the Weekly Meal Plan) */}
        <TouchableOpacity
          testID="home-shop-grocery-tile"
          activeOpacity={0.9}
          onPress={() => router.push("/(tabs)/groceries")}
          style={styles.shopTile}
        >
          <ImageBackground
            source={require("@/assets/brand/tile-grocery.jpg")}
            style={styles.shopTileImg}
            imageStyle={{ borderRadius: radius.xl }}
          >
            <LinearGradient colors={["rgba(1,24,56,0.12)", "rgba(1,24,56,0.85)"]} style={[StyleSheet.absoluteFill, { borderRadius: radius.xl }]} />
            <View style={styles.shopTileBody}>
              <View style={styles.shopTileIcon}><Ionicons name="basket" size={22} color="#fff" /></View>
              <Text style={styles.shopTileTitle}>Shop Grocery</Text>
              <Text style={styles.shopTileSub}>Halal meat, fish, sweets &amp; everyday essentials</Text>
              <View style={styles.shopTileCta}>
                <Text style={styles.shopTileCtaText}>Shop now</Text>
                <Ionicons name="arrow-forward" size={14} color="#fff" />
              </View>
            </View>
          </ImageBackground>
        </TouchableOpacity>

        {/* Thali Party Order tile — bulk thalis for parties & events */}
        <TouchableOpacity
          testID="home-thali-tile"
          activeOpacity={0.9}
          onPress={() => router.push("/thali")}
          style={styles.shopTile}
        >
          <ImageBackground
            source={require("@/assets/brand/tile-thali.jpg")}
            style={styles.shopTileImg}
            imageStyle={{ borderRadius: radius.xl }}
          >
            <LinearGradient colors={["rgba(242,168,28,0.12)", "rgba(201,120,10,0.85)"]} style={[StyleSheet.absoluteFill, { borderRadius: radius.xl }]} />
            <View style={styles.shopTileBody}>
              <View style={styles.shopTileIcon}><Ionicons name="fast-food" size={22} color="#fff" /></View>
              <Text style={styles.shopTileTitle}>Thali Party Order</Text>
              <Text style={styles.shopTileSub}>Bulk thalis for parties &amp; events</Text>
              <View style={styles.shopTileCta}>
                <Text style={styles.shopTileCtaText}>Order thalis</Text>
                <Ionicons name="arrow-forward" size={14} color="#fff" />
              </View>
            </View>
          </ImageBackground>
        </TouchableOpacity>

        {anytime.length > 0 && (
          <View style={styles.section} testID="home-anytime">
            <View style={styles.sectionHead}>
              <Text style={styles.sectionTitle}>Always Available</Text>
              <TouchableOpacity testID="home-anytime-viewmenu" onPress={() => router.push("/(tabs)/menu")}>
                <Text style={styles.sectionLink}>See menu →</Text>
              </TouchableOpacity>
            </View>
            <Text style={styles.anytimeHint}>Order any time — biryani, rolls, breads &amp; more.</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: spacing.xl, gap: spacing.lg }}>
              {anytime.map((it) => (
                <TouchableOpacity
                  key={it.item_id}
                  testID={`home-anytime-card-${it.item_id}`}
                  style={styles.aaCard}
                  activeOpacity={0.9}
                  onPress={() => add({ kind: "menu", ref_id: it.item_id, name: it.name, price_cents: it.price_cents, image_url: it.image_url })}
                >
                  <Image source={{ uri: mediaUrl(it.image_url) }} style={styles.aaImg} />
                  <View style={styles.aaBody}>
                    <Text style={styles.aaName} numberOfLines={1}>{it.name}</Text>
                    <Text style={styles.aaDesc} numberOfLines={2}>{it.description}</Text>
                    <View style={styles.aaFoot}>
                      <Text style={styles.aaPrice}>{centsToCAD(it.price_cents)}</Text>
                      <View style={styles.addBtn}>
                        <Ionicons name="add" size={14} color="#fff" />
                        <Text style={styles.addBtnText}>Add</Text>
                      </View>
                    </View>
                  </View>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        )}


        {/* Featured strip */}
        {(current?.alacarte_enabled ?? true) && (
        <View style={styles.section}>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionTitle}>{"Chef\u2019s Featured"}</Text>
            <TouchableOpacity testID="home-view-menu" onPress={() => router.push("/(tabs)/menu")}>
              <Text style={styles.sectionLink}>See all →</Text>
            </TouchableOpacity>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: spacing.xl, gap: spacing.lg }}>
            {featured.map((f) => (
              <TouchableOpacity
                key={f.item_id}
                testID={`featured-card-${f.item_id}`}
                style={styles.featCard}
                activeOpacity={0.9}
                onPress={() => add({ kind: "menu", ref_id: f.item_id, name: f.name, price_cents: f.price_cents, image_url: f.image_url })}
              >
                <ImageBackground source={{ uri: mediaUrl(f.image_url) }} style={styles.featImg} imageStyle={{ borderRadius: radius.xl }}>
                  <LinearGradient colors={["transparent", "rgba(0,0,0,0.75)"]} style={[StyleSheet.absoluteFill, { borderRadius: radius.xl }]} />
                  <View style={styles.featBody}>
                    <Text style={styles.featName} numberOfLines={2}>{f.name}</Text>
                    <View style={styles.featRow}>
                      <Text style={styles.featPrice}>{centsToCAD(f.price_cents)}</Text>
                      <View style={styles.featAdd}><Ionicons name="add" size={16} color="#fff" /></View>
                    </View>
                  </View>
                </ImageBackground>
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
        )}

        {/* This week grid */}
        {(current?.alacarte_enabled ?? true) && (
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { paddingHorizontal: spacing.xl }]}>{"This week\u2019s table"}</Text>
          <View style={styles.grid}>
            {rest.map((it) => (
              <TouchableOpacity
                key={it.item_id}
                testID={`menu-card-${it.item_id}`}
                style={styles.gridCard}
                activeOpacity={0.9}
                onPress={() => add({ kind: "menu", ref_id: it.item_id, name: it.name, price_cents: it.price_cents, image_url: it.image_url })}
              >
                <Image source={{ uri: mediaUrl(it.image_url) }} style={styles.gridImg} />
                <View style={styles.gridBody}>
                  <Text style={styles.gridName} numberOfLines={1}>{it.name}</Text>
                  <Text style={styles.gridDesc} numberOfLines={2}>{it.description}</Text>
                  <View style={styles.gridFoot}>
                    <Text style={styles.gridPrice}>{centsToCAD(it.price_cents)}</Text>
                    <View style={styles.addBtn}>
                      <Ionicons name="add" size={14} color="#fff" />
                      <Text style={styles.addBtnText}>Add</Text>
                    </View>
                  </View>
                </View>
              </TouchableOpacity>
            ))}
          </View>
        </View>
        )}

        {/* Best Sellers — featured groceries */}
        {sections.best && bestSellers.length > 0 && (
          <View style={styles.section} testID="home-best-sellers">
            <View style={styles.sectionHead}>
              <Text style={styles.sectionTitle}>Best Sellers</Text>
              <TouchableOpacity testID="home-best-sellers-all" onPress={() => router.push("/(tabs)/groceries")}>
                <Text style={styles.sectionLink}>See all →</Text>
              </TouchableOpacity>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: spacing.xl, gap: spacing.lg }}>
              {bestSellers.map((g) => (
                <TouchableOpacity
                  key={g.item_id}
                  testID={`home-best-${g.item_id}`}
                  style={styles.gCard}
                  activeOpacity={0.9}
                  onPress={() => router.push(`/grocery/${g.item_id}`)}
                >
                  <Image source={{ uri: mediaUrl(g.image_url) }} style={styles.gImg} />
                  <View style={styles.gBody}>
                    <Text style={styles.gName} numberOfLines={2}>{g.title}</Text>
                    <PriceGate compact><Text style={styles.gPrice}>{g.has_variants ? "from " : ""}{centsToCAD(g.price_cents)}</Text></PriceGate>
                  </View>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        )}

        {/* New Items — most recently added groceries */}
        {sections.newItems && newItems.length > 0 && (
          <View style={styles.section} testID="home-new-items">
            <View style={styles.sectionHead}>
              <Text style={styles.sectionTitle}>New Items</Text>
              <TouchableOpacity testID="home-new-items-all" onPress={() => router.push("/(tabs)/groceries")}>
                <Text style={styles.sectionLink}>See all →</Text>
              </TouchableOpacity>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: spacing.xl, gap: spacing.lg }}>
              {newItems.map((g) => (
                <TouchableOpacity
                  key={g.item_id}
                  testID={`home-new-${g.item_id}`}
                  style={styles.gCard}
                  activeOpacity={0.9}
                  onPress={() => router.push(`/grocery/${g.item_id}`)}
                >
                  <View style={styles.newBadge}><Text style={styles.newBadgeText}>NEW</Text></View>
                  <Image source={{ uri: mediaUrl(g.image_url) }} style={styles.gImg} />
                  <View style={styles.gBody}>
                    <Text style={styles.gName} numberOfLines={2}>{g.title}</Text>
                    <PriceGate compact><Text style={styles.gPrice}>{g.has_variants ? "from " : ""}{centsToCAD(g.price_cents)}</Text></PriceGate>
                  </View>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        )}

        {/* Upcoming weeks */}
        {upcoming.length > 0 && (
          <View style={styles.section}>
            <Text style={[styles.sectionTitle, { paddingHorizontal: spacing.xl }]}>Coming up next</Text>
            <View style={{ paddingHorizontal: spacing.xl, gap: spacing.md }}>
              {upcoming.map((w) => (
                <View key={w.menu_id} style={styles.upWeek} testID={`upcoming-week-${w.week_start}`}>
                  <View style={styles.upDot} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.upDate}>Week of {w.week_start}</Text>
                    <Text style={styles.upTitle}>{w.title}</Text>
                    <Text style={styles.upItems} numberOfLines={1}>
                      {w.items.slice(0, 3).map(i => i.name).join(" · ")}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          </View>
        )}

        <View style={{ height: 20 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  centerFill: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background },
  hero: { height: 380, justifyContent: "flex-end" },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.xl },
  hello: { color: "rgba(255,255,255,0.85)", fontSize: 12, letterSpacing: 2, fontWeight: "600" },
  userName: { color: "#fff", fontSize: 22, fontWeight: "700", marginTop: 2 },
  cartBtn: {
    width: 44, height: 44, borderRadius: radius.pill,
    backgroundColor: "rgba(255,255,255,0.18)",
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.25)",
  },
  cartDot: {
    position: "absolute", top: 4, right: 4, minWidth: 18, height: 18,
    borderRadius: 9, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center", paddingHorizontal: 4,
  },
  cartDotText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  heroBottom: { padding: spacing.xl, gap: spacing.sm },
  heroLogo: { width: 76, height: 76, borderRadius: 38, backgroundColor: "#fff", borderWidth: 3, borderColor: "#1E5AA8", marginBottom: 6 },
  heroTitle: { color: "#fff", fontSize: 30, fontWeight: "900", letterSpacing: -0.6, lineHeight: 34 },
  heroSubtitle: { color: "rgba(255,255,255,0.9)", fontSize: 14, lineHeight: 20, marginTop: 2, maxWidth: 340 },
  ribbon: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#D62828", paddingBottom: 8, paddingHorizontal: spacing.lg },
  ribbonText: { color: "#fff", fontSize: 12.5, fontWeight: "800", letterSpacing: 0.2 },
  windowChip: {
    alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, marginTop: 8,
  },
  windowChipText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  deliveryChip: { backgroundColor: "rgba(255,255,255,0.18)", borderWidth: 1, borderColor: "rgba(255,255,255,0.35)" },
  deliveryChipText: { color: "#fff", fontSize: 12, fontWeight: "700" },

  section: { marginTop: spacing.xl + 8 },
  // Home Package Hero
  pkgHomeHero: { marginHorizontal: spacing.xl, marginTop: spacing.xl, borderRadius: radius.xl, overflow: "hidden", ...shadows.card },
  pkgHomeHeroImg: { width: "100%", minHeight: 240, justifyContent: "space-between" },
  pkgHomeHeroBadge: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.primary, margin: spacing.md, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  pkgHomeHeroBadgeText: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 2 },
  pkgHomeHeroBody: { padding: spacing.lg, gap: 6 },
  pkgHomeHeroName: { color: "#fff", fontSize: 22, fontWeight: "800", letterSpacing: -0.3 },
  pkgHomeHeroSub: { color: "rgba(255,255,255,0.85)", fontSize: 12, lineHeight: 16 },
  comboComp: { marginTop: 10, gap: 6, backgroundColor: "rgba(0,0,0,0.45)", borderRadius: radius.md, borderWidth: 1, borderColor: "rgba(255,255,255,0.18)", padding: 10 },
  comboCompHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  freeBadge: { flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: colors.success, paddingHorizontal: 7, paddingVertical: 3, borderRadius: radius.pill },
  freeBadgeText: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  comboCompLabel: { color: colors.primary, fontSize: 10, fontWeight: "900", letterSpacing: 1.5 },
  comboCompNames: { color: "#fff", fontSize: 14, fontWeight: "800", lineHeight: 19 },
  pkgHomeHeroRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 },
  pkgHomeHeroPrice: { color: "#fff", fontSize: 22, fontWeight: "800" },
  pkgHomeHeroPriceSub: { color: "rgba(255,255,255,0.7)", fontSize: 11 },
  pkgHomeHeroCta: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.pill },
  pkgHomeHeroCtaText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.xl, marginBottom: spacing.md },
  sectionTitle: { fontSize: 22, fontWeight: "800", color: colors.text, letterSpacing: -0.3 },
  sectionLink: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  anytimeHint: { color: colors.textMuted, fontSize: 12, paddingHorizontal: spacing.xl, marginBottom: spacing.md, marginTop: -spacing.xs },

  featCard: { width: 240, height: 300, borderRadius: radius.xl, overflow: "hidden", ...shadows.card },
  featImg: { flex: 1, justifyContent: "flex-end" },
  aaCard: { width: 240, backgroundColor: colors.surface, borderRadius: radius.xl, overflow: "hidden", borderWidth: 1, borderColor: colors.border, ...shadows.card },
  aaImg: { width: "100%", height: 150, backgroundColor: colors.surfaceAlt },
  aaBody: { padding: spacing.md, gap: 4 },
  aaName: { fontSize: 15, fontWeight: "800", color: colors.text },
  aaDesc: { fontSize: 12, color: colors.textMuted, lineHeight: 16, minHeight: 32 },
  aaFoot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  aaPrice: { color: colors.primary, fontWeight: "800", fontSize: 15 },
  featBody: { padding: spacing.lg, gap: 8 },
  featName: { color: "#fff", fontSize: 18, fontWeight: "700", lineHeight: 22 },
  featRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  featPrice: { color: colors.primary, fontSize: 16, fontWeight: "800" },
  featAdd: { width: 32, height: 32, borderRadius: radius.pill, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },

  grid: { flexDirection: "row", flexWrap: "wrap", paddingHorizontal: spacing.lg, gap: spacing.md, marginTop: 4 },
  gridCard: {
    flexGrow: 1, flexBasis: "45%", minWidth: 150, borderRadius: radius.lg,
    backgroundColor: colors.surface, overflow: "hidden", ...shadows.soft,
    borderWidth: 1, borderColor: colors.border,
  },
  gridImg: { width: "100%", height: 110, backgroundColor: colors.surfaceAlt },
  gridBody: { padding: spacing.md, gap: 4 },
  gridName: { fontSize: 14, fontWeight: "700", color: colors.text },
  gridDesc: { fontSize: 11, color: colors.textMuted, lineHeight: 15, height: 30 },
  gridFoot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 },
  gridPrice: { color: colors.primary, fontWeight: "800", fontSize: 14 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: colors.primary, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill },
  addBtnText: { color: "#fff", fontSize: 11, fontWeight: "700" },

  // Shop Grocery tile (between hero and weekly package)
  shopTile: { marginHorizontal: spacing.xl, marginTop: spacing.xl, borderRadius: radius.xl, overflow: "hidden", ...shadows.card },
  shopTileImg: { width: "100%", minHeight: 180, justifyContent: "flex-end" },
  shopTileBody: { padding: spacing.lg, gap: 5 },
  shopTileIcon: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: "rgba(255,255,255,0.22)", alignItems: "center", justifyContent: "center", marginBottom: 4 },
  shopTileTitle: { color: "#fff", fontSize: 24, fontWeight: "900", letterSpacing: -0.4 },
  shopTileSub: { color: "rgba(255,255,255,0.9)", fontSize: 13 },
  shopTileCta: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  shopTileCtaText: { color: "#fff", fontWeight: "800", fontSize: 14 },

  // Grocery product cards (Best Sellers / New Items)
  gCard: { width: 160, backgroundColor: colors.surface, borderRadius: radius.lg, overflow: "hidden", borderWidth: 1, borderColor: colors.border, ...shadows.soft },
  gImg: { width: "100%", height: 130, backgroundColor: colors.surfaceAlt },
  gBody: { padding: spacing.md, gap: 4 },
  gName: { fontSize: 13, fontWeight: "700", color: colors.text, minHeight: 34 },
  gPrice: { color: colors.primary, fontWeight: "800", fontSize: 14 },
  newBadge: { position: "absolute", top: 8, left: 8, zIndex: 2, backgroundColor: colors.secondary, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  newBadgeText: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 1 },

  upWeek: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.md,
    padding: spacing.md, borderRadius: radius.lg, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  upDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.secondary, marginTop: 6 },
  upDate: { color: colors.textMuted, fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  upTitle: { color: colors.text, fontSize: 15, fontWeight: "700", marginTop: 2 },
  upItems: { color: colors.textMuted, fontSize: 12, marginTop: 2 },
});
