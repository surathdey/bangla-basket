import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  FlatList, TextInput, ScrollView,
} from "react-native";
import { Image } from "expo-image";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { useCart } from "@/src/cart";
import { api } from "@/src/api";
import { mediaUrl } from "@/src/utils/backendUrl";
import { colors, spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";
import { useComingSoon } from "@/src/hooks/use-coming-soon";
import { usePricingLocation } from "@/src/location";
import { PriceGate } from "@/src/components/PriceGate";
import { LocationBanner } from "@/src/components/LocationBanner";
import { FishSubcatNote } from "@/src/components/FishSubcatNote";

export type Grocery = {
  item_id: string; title: string; description: string; category: string;
  price_cents: number; compare_at_cents: number; unit: string;
  image_url: string; images: string[]; in_stock: boolean; is_featured: boolean;
  has_variants: boolean;
  variants: { variant_id: string; title: string; price_cents: number; compare_at_cents: number; available: boolean }[];
};
type Cat = { category: string; count: number };

export default function GroceriesTab() {
  const [cats, setCats] = useState<Cat[]>([]);
  const [active, setActive] = useState<string>("All");
  const [subcats, setSubcats] = useState<{ subcategory: string; count: number }[]>([]);
  const [activeSub, setActiveSub] = useState<string>("All");
  const [items, setItems] = useState<Grocery[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const { add, count } = useCart();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const comingSoon = useComingSoon();
  const { postal, gated, showHelp } = usePricingLocation();

  useEffect(() => {
    (async () => {
      const r = await api.get<{ total: number; categories: Cat[] }>("/grocery/categories");
      if (r.ok) setCats(r.data.categories || []);
    })();
  }, []);

  const fetchPage = useCallback(async (pg: number, cat: string, sub: string, q: string, replace: boolean) => {
    if (pg === 1) setLoading(true); else setLoadingMore(true);
    const params = new URLSearchParams({ page: String(pg), limit: "24" });
    if (cat && cat !== "All") params.set("category", cat);
    if (sub && sub !== "All") params.set("subcategory", sub);
    if (q) params.set("q", q);
    if (postal) params.set("postal", postal);
    const r = await api.get<{ items: Grocery[]; pages: number; total: number }>(`/grocery?${params.toString()}`);
    if (r.ok) {
      setItems(prev => replace ? r.data.items : [...prev, ...r.data.items]);
      setPages(r.data.pages); setTotal(r.data.total); setPage(pg);
    }
    setLoading(false); setLoadingMore(false);
  }, [postal]);

  // Load sub-filters whenever a category is chosen (e.g. Fish → Whole/Cut/By Weight).
  useEffect(() => {
    setActiveSub("All");
    if (!active || active === "All") { setSubcats([]); return; }
    (async () => {
      const r = await api.get<{ subcategories: { subcategory: string; count: number }[] }>(`/grocery/subcategories?category=${encodeURIComponent(active)}`);
      setSubcats(r.ok ? (r.data.subcategories || []) : []);
    })();
  }, [active]);

  useEffect(() => { fetchPage(1, active, activeSub, query, true); }, [active, activeSub, query, fetchPage]);

  const onSubmitSearch = () => setQuery(search.trim());
  const chips = useMemo(() => [{ category: "All", count: total } as Cat, ...cats], [cats, total]);

  const addToBag = (g: Grocery) => {
    if (g.has_variants) { router.push(`/grocery/${g.item_id}`); return; }
    add({
      kind: "grocery" as any, ref_id: g.item_id, name: g.title,
      price_cents: g.price_cents, image_url: g.image_url,
      category: g.category, subcategory: (g as any).subcategory,
    });
  };

  const renderItem = ({ item: g }: { item: Grocery }) => (
    <TouchableOpacity
      testID={`grocery-card-${g.item_id}`}
      style={styles.card}
      activeOpacity={0.85}
      onPress={() => router.push(`/grocery/${g.item_id}`)}
    >
      <View style={styles.imgWrap}>
        {g.image_url ? (
          <Image source={{ uri: mediaUrl(g.image_url) }} style={styles.img} contentFit="cover" transition={200} />
        ) : (
          <View style={[styles.img, styles.imgEmpty]}><Ionicons name="image-outline" size={28} color={colors.textMuted} /></View>
        )}
        {g.compare_at_cents > g.price_cents && (
          <View style={styles.saleTag}><Text style={styles.saleTagText}>SALE</Text></View>
        )}
      </View>
      <View style={styles.cardBody}>
        <Text style={styles.cardName} numberOfLines={2}>{g.title}</Text>
        {g.unit ? <Text style={styles.unit}>{g.unit}</Text> : null}
        <View style={styles.priceRow}>
          <PriceGate compact>
            <Text style={styles.price}>{g.has_variants ? "from " : ""}{centsToCAD(g.price_cents)}</Text>
            {g.compare_at_cents > g.price_cents && (
              <Text style={styles.compare}>{centsToCAD(g.compare_at_cents)}</Text>
            )}
          </PriceGate>
        </View>
        {gated ? (
          <TouchableOpacity testID={`grocery-enable-loc-${g.item_id}`} style={[styles.addBtn, styles.comingBtn]} onPress={showHelp}>
            <Ionicons name="location-outline" size={16} color={colors.primary} />
            <Text style={[styles.addBtnText, { color: colors.primary }]}>Enable location</Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity testID={`grocery-add-${g.item_id}`} disabled={comingSoon} style={[styles.addBtn, comingSoon && styles.comingBtn]} onPress={() => !comingSoon && addToBag(g)}>
            <Ionicons name={comingSoon ? "time-outline" : (g.has_variants ? "options-outline" : "add")} size={16} color={comingSoon ? colors.textMuted : "#fff"} />
            <Text style={[styles.addBtnText, comingSoon && styles.comingBtnText]}>{comingSoon ? "Coming soon" : (g.has_variants ? "Options" : "Add")}</Text>
          </TouchableOpacity>
        )}
      </View>
    </TouchableOpacity>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <LocationBanner topInset={insets.top} />
      <SafeAreaView edges={["top"]} style={styles.header}>
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.eyebrow}>GROCERIES</Text>
            <Text style={styles.title}>Shop Bengali & Indian</Text>
          </View>
          <TouchableOpacity testID="grocery-cart-button" style={styles.cartBtn} onPress={() => router.push("/(tabs)/orders")}>
            <Ionicons name="bag-handle-outline" size={22} color={colors.text} />
            {count > 0 && <View style={styles.cartDot}><Text style={styles.cartDotText}>{count}</Text></View>}
          </TouchableOpacity>
        </View>
        <View style={styles.searchBar}>
          <Ionicons name="search" size={18} color={colors.textMuted} />
          <TextInput
            testID="grocery-search-input"
            value={search}
            onChangeText={setSearch}
            onSubmitEditing={onSubmitSearch}
            returnKeyType="search"
            placeholder="Search groceries…"
            placeholderTextColor={colors.textMuted}
            style={styles.searchInput}
          />
          {search.length > 0 && (
            <TouchableOpacity onPress={() => { setSearch(""); setQuery(""); }}>
              <Ionicons name="close-circle" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          )}
        </View>
      </SafeAreaView>

      <View style={styles.chipRowWrap}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipRowContent}
        >
          {chips.map((c) => {
            const on = active === c.category;
            return (
              <TouchableOpacity
                key={c.category}
                testID={`grocery-chip-${c.category}`}
                onPress={() => setActive(c.category)}
                style={[styles.chip, on && styles.chipActive]}
              >
                <Text style={[styles.chipText, on && styles.chipTextActive]} numberOfLines={1}>{c.category}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      </View>

      {subcats.length > 0 && (
        <View style={styles.subChipWrap}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRowContent}>
            {[{ subcategory: "All", count: 0 }, ...subcats].map((s) => {
              const on = activeSub === s.subcategory;
              return (
                <TouchableOpacity key={s.subcategory} testID={`grocery-subchip-${s.subcategory}`} onPress={() => setActiveSub(s.subcategory)} style={[styles.subChip, on && styles.subChipActive]}>
                  <Text style={[styles.subChipText, on && styles.subChipTextActive]} numberOfLines={1}>{s.subcategory}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>
      )}
      {subcats.length > 0 && <FishSubcatNote category={active} />}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>
      ) : (
        <FlatList
          testID="grocery-list"
          data={items}
          keyExtractor={(g) => g.item_id}
          renderItem={renderItem}
          numColumns={2}
          columnWrapperStyle={{ gap: spacing.md, paddingHorizontal: spacing.lg }}
          contentContainerStyle={{ paddingTop: spacing.md, paddingBottom: 120 + insets.bottom, gap: spacing.md }}
          onEndReachedThreshold={0.5}
          onEndReached={() => { if (!loadingMore && page < pages) fetchPage(page + 1, active, activeSub, query, false); }}
          ListEmptyComponent={<Text style={styles.empty}>No items found.</Text>}
          ListFooterComponent={loadingMore ? <ActivityIndicator color={colors.primary} style={{ marginVertical: 16 }} /> : null}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border, paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
  headerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingTop: spacing.sm },
  eyebrow: { color: colors.primary, letterSpacing: 3, fontSize: 11, fontWeight: "800" },
  title: { fontSize: 24, fontWeight: "800", color: colors.text, marginTop: 2, letterSpacing: -0.3 },
  cartBtn: { width: 44, height: 44, borderRadius: radius.pill, backgroundColor: colors.surfaceAlt, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border },
  cartDot: { position: "absolute", top: 4, right: 4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  cartDotText: { color: "#fff", fontSize: 10, fontWeight: "800" },
  searchBar: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, paddingHorizontal: spacing.md, height: 44, marginTop: spacing.md },
  searchInput: { flex: 1, color: colors.text, fontSize: 14 },

  chipRowWrap: { height: 56, backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.border, justifyContent: "center" },
  chipRowContent: { paddingHorizontal: spacing.lg, gap: 8, alignItems: "center" },
  chip: { height: 36, flexShrink: 0, paddingHorizontal: 14, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 13, fontWeight: "700", color: colors.text },
  chipTextActive: { color: "#fff" },
  subChipWrap: { height: 58, backgroundColor: colors.surfaceAlt, borderBottomWidth: 1, borderBottomColor: colors.border, justifyContent: "center" },
  subChip: { height: 42, flexShrink: 0, paddingHorizontal: 18, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  subChipActive: { backgroundColor: colors.text, borderColor: colors.text },
  subChipText: { fontSize: 14.5, fontWeight: "800", color: colors.text },
  subChipTextActive: { color: "#fff" },

  card: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden", ...shadows.soft },
  imgWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceAlt },
  img: { width: "100%", height: "100%" },
  imgEmpty: { alignItems: "center", justifyContent: "center" },
  saleTag: { position: "absolute", top: 8, left: 8, backgroundColor: colors.secondary, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  saleTagText: { color: "#1a1a1a", fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  cardBody: { padding: spacing.md, gap: 4 },
  cardName: { fontSize: 13, fontWeight: "700", color: colors.text, minHeight: 34 },
  unit: { fontSize: 11, color: colors.textMuted },
  priceRow: { flexDirection: "row", alignItems: "baseline", gap: 6, marginTop: 2 },
  price: { fontSize: 16, fontWeight: "800", color: colors.primary },
  compare: { fontSize: 12, color: colors.textMuted, textDecorationLine: "line-through" },
  addBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, backgroundColor: colors.primary, borderRadius: radius.pill, paddingVertical: 9, marginTop: 6 },
  addBtnText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  comingBtn: { backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },
  comingBtnText: { color: colors.textMuted },
  empty: { color: colors.textMuted, textAlign: "center", padding: spacing.xl, width: "100%" },
});
