import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  FlatList, TextInput, ScrollView, useWindowDimensions, Platform,
} from "react-native";
import { Image, ImageBackground } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCart } from "@/src/cart";
import { api } from "@/src/api";
import { mediaUrl } from "@/src/utils/backendUrl";
import { BRAND } from "@/src/brand";
import { colors, spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";
import { useComingSoon } from "@/src/hooks/use-coming-soon";
import { usePricingLocation } from "@/src/location";
import { PriceGate } from "@/src/components/PriceGate";
import { ShopHeader } from "@/src/components/ShopHeader";
import { ShopFooter } from "@/src/components/ShopFooter";
import { FishSubcatNote } from "@/src/components/FishSubcatNote";
import type { Grocery } from "../(tabs)/groceries";

const HERO_GROCERY = "/api/uploads/banners/hero-grocery.jpg";
const BLUE = "#1E5AA8";
type Cat = { category: string; count: number };

export default function ShopBrowse() {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { add } = useCart();
  const params = useLocalSearchParams<{ category?: string; q?: string }>();
  const comingSoon = useComingSoon();
  const { postal, gated, showHelp } = usePricingLocation();

  const [cats, setCats] = useState<Cat[]>([]);
  const [active, setActive] = useState<string>(params.category || "All");
  // Auto-centre the selected category chip in its horizontal scroller.
  const chipScrollRef = useRef<ScrollView>(null);
  const chipLayouts = useRef<Record<string, { x: number; w: number }>>({});
  const centerChip = useCallback((key: string) => {
    const l = chipLayouts.current[key];
    if (l && chipScrollRef.current) {
      chipScrollRef.current.scrollTo({ x: Math.max(0, l.x - width / 2 + l.w / 2), animated: true });
    }
  }, [width]);
  useEffect(() => { centerChip(active); }, [active, centerChip]);
  const [subcats, setSubcats] = useState<{ subcategory: string; count: number }[]>([]);
  const [activeSub, setActiveSub] = useState<string>("All");
  const [items, setItems] = useState<Grocery[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState(params.q || "");
  const [query, setQuery] = useState(params.q || "");

  const cols = width > 1180 ? 4 : width > 860 ? 3 : 2;
  const contentWidth = Math.min(width, 1200);

  useEffect(() => {
    (async () => {
      const r = await api.get<{ total: number; categories: Cat[] }>("/grocery/categories");
      if (r.ok) setCats(r.data.categories || []);
    })();
  }, []);

  const fetchPage = useCallback(async (pg: number, cat: string, sub: string, q: string, replace: boolean) => {
    if (pg === 1) setLoading(true); else setLoadingMore(true);
    const p = new URLSearchParams({ page: String(pg), limit: "24" });
    if (cat && cat !== "All") p.set("category", cat);
    if (sub && sub !== "All") p.set("subcategory", sub);
    if (q) p.set("q", q);
    if (postal) p.set("postal", postal);
    const r = await api.get<{ items: Grocery[]; pages: number; total: number }>(`/grocery?${p.toString()}`);
    if (r.ok) {
      setItems(prev => replace ? r.data.items : [...prev, ...r.data.items]);
      setPages(r.data.pages); setTotal(r.data.total); setPage(pg);
    }
    setLoading(false); setLoadingMore(false);
  }, [postal]);

  useEffect(() => {
    setActiveSub("All");
    if (!active || active === "All") { setSubcats([]); return; }
    (async () => {
      const r = await api.get<{ subcategories: { subcategory: string; count: number }[] }>(`/grocery/subcategories?category=${encodeURIComponent(active)}`);
      setSubcats(r.ok ? (r.data.subcategories || []) : []);
    })();
  }, [active]);

  useEffect(() => { fetchPage(1, active, activeSub, query, true); }, [active, activeSub, query, fetchPage]);

  const chips = useMemo(() => [{ category: "All", count: total } as Cat, ...cats], [cats, total]);

  const onAdd = (g: Grocery) => {
    if (g.has_variants) { router.push(`/shop/product/${g.item_id}`); return; }
    add({ kind: "grocery" as any, ref_id: g.item_id, name: g.title, price_cents: g.price_cents, image_url: g.image_url, category: g.category, subcategory: (g as any).subcategory });
  };

  const Card = ({ g }: { g: Grocery }) => (
    <TouchableOpacity testID={`browse-card-${g.item_id}`} style={[styles.card, { width: `${100 / cols}%` }]} activeOpacity={0.85} onPress={() => router.push(`/shop/product/${g.item_id}`)}>
      <View style={styles.cardInner}>
        <View style={styles.imgWrap}>
          {g.image_url ? <Image source={{ uri: mediaUrl(g.image_url) }} style={styles.img} contentFit="cover" transition={200} /> : <View style={[styles.img, styles.imgEmpty]}><Ionicons name="image-outline" size={26} color={colors.textMuted} /></View>}
          {g.compare_at_cents > g.price_cents && <View style={styles.saleTag}><Text style={styles.saleTagText}>SALE</Text></View>}
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.cardName} numberOfLines={2}>{g.title}</Text>
          <View style={styles.priceRow}>
            <PriceGate compact>
              <Text style={styles.price}>{g.has_variants ? "from " : ""}{centsToCAD(g.price_cents)}</Text>
              {g.compare_at_cents > g.price_cents && <Text style={styles.compare}>{centsToCAD(g.compare_at_cents)}</Text>}
            </PriceGate>
          </View>
          {gated ? (
            <TouchableOpacity testID={`browse-enable-loc-${g.item_id}`} style={[styles.addBtn, styles.comingBtn]} onPress={showHelp}>
              <Ionicons name="location-outline" size={15} color={colors.primary} />
              <Text style={[styles.addBtnText, { color: colors.primary }]}>Enable location</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity testID={`browse-add-${g.item_id}`} disabled={comingSoon} style={[styles.addBtn, comingSoon && styles.comingBtn]} onPress={() => !comingSoon && onAdd(g)}>
              <Ionicons name={comingSoon ? "time-outline" : (g.has_variants ? "options-outline" : "cart")} size={15} color={comingSoon ? colors.textMuted : "#fff"} />
              <Text style={[styles.addBtnText, comingSoon && styles.comingBtnText]}>{comingSoon ? "Coming soon" : (g.has_variants ? "Options" : "Add to cart")}</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    </TouchableOpacity>
  );

  const Header = (
    <View style={{ alignItems: "center" }}>
      {/* HERO BANNER */}
      <View style={{ width: "100%", alignItems: "center", backgroundColor: BLUE }}>
        <View style={styles.hero}>
          <ImageBackground source={{ uri: mediaUrl(HERO_GROCERY) }} style={StyleSheet.absoluteFill} contentFit="cover" transition={300} />
          <LinearGradient colors={["rgba(20,45,90,0.82)", "rgba(20,45,90,0.32)"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0 }} style={StyleSheet.absoluteFill} />
          <View style={[styles.heroInner, { width: contentWidth }]}>
            <Text style={styles.heroCrumb} onPress={() => router.push("/shop")}>← Back to home</Text>
            <View style={styles.heroBadge}><Text style={styles.heroBadgeText}>HALAL · FRESH · DELIVERED</Text></View>
            <Text testID="browse-hero-title" style={styles.heroTitle}>{active === "All" ? "Fresh Halal Groceries" : active}</Text>
            <Text style={styles.heroSub} numberOfLines={2}>Fresh meat, fish, sweets & everyday essentials — delivered across {BRAND.region.serviceArea}.</Text>
          </View>
        </View>
      </View>
      <View style={{ width: contentWidth, paddingHorizontal: spacing.lg }}>
        <View style={styles.searchBar}>
          <Ionicons name="search" size={18} color={colors.textMuted} />
          <TextInput testID="browse-search" value={search} onChangeText={setSearch} onSubmitEditing={() => setQuery(search.trim())} returnKeyType="search" placeholder="Search products…" placeholderTextColor={colors.textMuted} style={styles.searchInput} />
          {!!search && <TouchableOpacity onPress={() => { setSearch(""); setQuery(""); }}><Ionicons name="close-circle" size={18} color={colors.textMuted} /></TouchableOpacity>}
        </View>
        <ScrollView ref={chipScrollRef} horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
          {chips.map((c) => {
            const on = active === c.category;
            return (
              <TouchableOpacity
                key={c.category}
                testID={`browse-chip-${c.category}`}
                onLayout={(e) => {
                  chipLayouts.current[c.category] = { x: e.nativeEvent.layout.x, w: e.nativeEvent.layout.width };
                  if (c.category === active) centerChip(c.category);
                }}
                onPress={() => { setActive(c.category); centerChip(c.category); }}
                style={[styles.chip, on && styles.chipActive]}
              >
                <Text style={[styles.chipText, on && styles.chipTextActive]} numberOfLines={1}>{c.category}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
        {subcats.length > 0 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.subChipRow}>
            {[{ subcategory: "All", count: 0 }, ...subcats].map((s) => {
              const on = activeSub === s.subcategory;
              return (
                <TouchableOpacity key={s.subcategory} testID={`browse-subchip-${s.subcategory}`} onPress={() => setActiveSub(s.subcategory)} style={[styles.subChip, on && styles.subChipActive]}>
                  <Text style={[styles.subChipText, on && styles.subChipTextActive]} numberOfLines={1}>{s.subcategory}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        )}
        <FishSubcatNote category={active} />
        <Text style={styles.resultCount}>{total.toLocaleString()} items</Text>
      </View>
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <ShopHeader active="groceries" />

      <FlatList
          testID="browse-list"
          key={cols}
          data={loading ? [] : items}
          keyExtractor={(g) => g.item_id}
          renderItem={({ item }) => <Card g={item} />}
          numColumns={cols}
          columnWrapperStyle={{ justifyContent: "flex-start", alignSelf: "center", width: contentWidth, paddingHorizontal: spacing.lg - 6 }}
          ListHeaderComponent={Header}
          contentContainerStyle={{ paddingBottom: 48 + insets.bottom }}
          keyboardShouldPersistTaps="handled"
          onEndReachedThreshold={0.6}
          onEndReached={() => { if (!loadingMore && page < pages) fetchPage(page + 1, active, activeSub, query, false); }}
          ListEmptyComponent={loading
            ? <View style={{ paddingVertical: 80, alignItems: "center" }}><ActivityIndicator color={colors.primary} size="large" /></View>
            : <Text style={styles.empty}>No products found.</Text>}
          ListFooterComponent={
            <>
              {loadingMore && <ActivityIndicator color={colors.primary} style={{ marginVertical: 20 }} />}
              <ShopFooter />
            </>
          }
        />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  nav: { backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border, alignItems: "center", paddingBottom: 10, ...(Platform.OS === "web" ? { position: "sticky" as any, top: 0, zIndex: 20 } : {}) },
  navInner: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg },
  brandRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  logo: { width: 44, height: 44, borderRadius: 22, backgroundColor: "#fff", borderWidth: 2, borderColor: "#1E5AA8" },
  brandName: { fontSize: 20, fontWeight: "900", color: colors.text, letterSpacing: -0.5 },
  cartBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, height: 40, borderRadius: radius.pill, backgroundColor: "#D62828" },
  cartBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  cartDot: { position: "absolute", top: -4, right: -4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.secondary, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  cartDotText: { color: "#1a1a1a", fontSize: 10, fontWeight: "900" },

  crumb: { color: colors.primary, fontWeight: "700", fontSize: 13, marginTop: spacing.lg },
  h1: { fontSize: 26, fontWeight: "900", color: colors.text, letterSpacing: -0.5, marginTop: 4 },
  hero: { width: "100%", alignItems: "center", overflow: "hidden", minHeight: 210, justifyContent: "center" },
  heroInner: { paddingHorizontal: spacing.lg, paddingVertical: 32, gap: 10 },
  heroCrumb: { color: "rgba(255,255,255,0.9)", fontWeight: "700", fontSize: 13 },
  heroBadge: { alignSelf: "flex-start", backgroundColor: "rgba(255,255,255,0.2)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill },
  heroBadgeText: { color: "#fff", fontSize: 11, fontWeight: "900", letterSpacing: 1.5 },
  heroTitle: { color: "#fff", fontSize: 34, fontWeight: "900", letterSpacing: -0.6, maxWidth: 620 },
  heroSub: { color: "rgba(255,255,255,0.95)", fontSize: 15, maxWidth: 540 },
  searchBar: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: spacing.md, height: 46, marginTop: spacing.md, maxWidth: 520 },
  searchInput: { flex: 1, color: colors.text, fontSize: 15, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  chipRow: { gap: 10, paddingVertical: spacing.lg, alignItems: "center" },
  chip: { height: 46, flexShrink: 0, paddingHorizontal: 20, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 15, fontWeight: "800", color: colors.text },
  chipTextActive: { color: "#fff" },
  subChipRow: { gap: 10, paddingBottom: spacing.md, alignItems: "center" },
  subChip: { height: 42, flexShrink: 0, paddingHorizontal: 18, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surfaceAlt, alignItems: "center", justifyContent: "center" },
  subChipActive: { backgroundColor: colors.text, borderColor: colors.text },
  subChipText: { fontSize: 14.5, fontWeight: "800", color: colors.text },
  subChipTextActive: { color: "#fff" },
  resultCount: { color: colors.textMuted, fontWeight: "700", marginBottom: spacing.md },

  card: { padding: 6 },
  cardInner: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden", ...shadows.soft },
  imgWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceAlt },
  img: { width: "100%", height: "100%" },
  imgEmpty: { alignItems: "center", justifyContent: "center" },
  saleTag: { position: "absolute", top: 8, left: 8, backgroundColor: colors.secondary, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  saleTagText: { color: "#1a1a1a", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  cardBody: { padding: spacing.md, gap: 4 },
  cardName: { fontSize: 14, fontWeight: "700", color: colors.text, minHeight: 38 },
  priceRow: { flexDirection: "row", alignItems: "baseline", gap: 6, marginTop: 2 },
  price: { fontSize: 16, fontWeight: "800", color: colors.primary },
  compare: { fontSize: 12, color: colors.textMuted, textDecorationLine: "line-through" },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.primary, borderRadius: radius.pill, paddingVertical: 10, marginTop: 8 },
  addBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  comingBtn: { backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },
  comingBtnText: { color: colors.textMuted },
  empty: { color: colors.textMuted, textAlign: "center", padding: spacing.xl },
});
