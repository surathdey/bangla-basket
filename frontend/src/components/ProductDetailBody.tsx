import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { api } from "@/src/api";
import { useCart } from "@/src/cart";
import { mediaUrl } from "@/src/utils/backendUrl";
import { colors, spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";
import { useComingSoon } from "@/src/hooks/use-coming-soon";
import { usePricingLocation } from "@/src/location";
import { PriceGate } from "@/src/components/PriceGate";
import type { Grocery } from "../../app/(tabs)/groceries";

type Variant = Grocery["variants"][number];

// Fish cut styles offered on Cut / By Weight items (Block items are
// pre-cut, so they get no selector). Sample photos per option arrive
// from the owners later; the selector ships text-only until then.
const CUT_OPTIONS = ["Gada-Peti", "Restaurant Cut", "Chinese Cut", "Gada-Peti 4 Slice"];

/**
 * Shared product-detail renderer used by BOTH the mobile app route
 * (`/grocery/[id]`) and the desktop web route (`/shop/product/[id]`).
 *
 * `web=true` drops the sticky mobile add-bar in favour of an inline
 * add button (the page supplies the shared site header/footer instead),
 * and routes related-item links to the matching URL space.
 */
export function ProductDetailBody({
  id,
  web = false,
  bottomInset = 0,
  onLoaded,
}: {
  id: string;
  web?: boolean;
  bottomInset?: number;
  onLoaded?: (g: Grocery) => void;
}) {
  const [item, setItem] = useState<Grocery | null>(null);
  const [related, setRelated] = useState<Grocery[]>([]);
  const [loading, setLoading] = useState(true);
  const [qty, setQty] = useState(1);
  const [added, setAdded] = useState(false);
  const [variantId, setVariantId] = useState<string | null>(null);
  const [cut, setCut] = useState<string | null>(null);
  const [cutOpen, setCutOpen] = useState(false);
  const { add } = useCart();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isWide = width >= 900;
  const comingSoon = useComingSoon();
  const { postal, gated, showHelp } = usePricingLocation();

  const linkBase = web ? "/shop/product" : "/grocery";

  useEffect(() => {
    (async () => {
      setLoading(true);
      const qs = postal ? `?postal=${encodeURIComponent(postal)}` : "";
      const r = await api.get<Grocery>(`/grocery/${id}${qs}`);
      if (r.ok) {
        setItem(r.data);
        setQty(1);
        setCut(null);
        setCutOpen(false);
        onLoaded?.(r.data);
        if (r.data.has_variants && r.data.variants?.length) {
          const first = r.data.variants.find(v => v.available) || r.data.variants[0];
          setVariantId(first.variant_id);
        }
      }
      setLoading(false);
      const rel = await api.get<{ items: Grocery[] }>(`/grocery/${id}/related${qs}`);
      setRelated(rel.ok ? (rel.data.items || []) : []);
    })();
  }, [id, postal]);

  const selected: Variant | null = useMemo(() => {
    if (!item?.has_variants) return null;
    return item.variants.find(v => v.variant_id === variantId) || null;
  }, [item, variantId]);

  if (loading) return <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>;
  if (!item) return <View style={styles.center}><Text style={{ color: colors.textMuted }}>Item not found.</Text></View>;

  const unitPrice = selected ? selected.price_cents : item.price_cents;
  const comparePrice = selected ? selected.compare_at_cents : item.compare_at_cents;
  const available = selected ? selected.available : item.in_stock;
  const showCut = item.subcategory === "Cut" || item.subcategory === "By Weight";

  const onAdd = () => {
    if (item.has_variants && !selected) return;
    add({
      kind: "grocery" as any,
      ref_id: item.item_id,
      name: item.title + (selected && selected.title !== "Standard" ? ` — ${selected.title}` : ""),
      price_cents: unitPrice,
      image_url: item.image_url,
      variant_id: selected?.variant_id,
      variant_title: selected?.title,
      cut_preference: showCut ? (cut || undefined) : undefined,
      category: item.category,
      subcategory: item.subcategory,
    }, qty);
    setAdded(true);
    setTimeout(() => setAdded(false), 1600);
  };

  const imageNode = (selected?.image_url || item.image_url) ? (
    <Image source={{ uri: mediaUrl(selected?.image_url || item.image_url) }} style={styles.heroImg} contentFit="cover" transition={200} />
  ) : (
    <View style={[styles.heroImg, { alignItems: "center", justifyContent: "center" }]}>
      <Ionicons name="image-outline" size={48} color={colors.textMuted} />
    </View>
  );

  const infoNode = (
    <>
      <Text style={styles.cat}>{item.category?.toUpperCase()}</Text>
      <Text style={styles.name}>{item.title}</Text>
      <View style={styles.priceRow}>
        <PriceGate>
          <Text style={styles.price}>{centsToCAD(unitPrice)}</Text>
          {comparePrice > unitPrice && <Text style={styles.compare}>{centsToCAD(comparePrice)}</Text>}
        </PriceGate>
        {!available && <Text style={styles.oos}>Out of stock</Text>}
      </View>

      {item.has_variants && (
        <View style={styles.variantBox} testID="variant-selector">
          <Text style={styles.variantLabel}>Choose an option</Text>
          <View style={styles.variantList}>
            {item.variants.map((v) => {
              const on = v.variant_id === variantId;
              return (
                <TouchableOpacity
                  key={v.variant_id}
                  testID={`variant-${v.variant_id}`}
                  disabled={!v.available}
                  onPress={() => setVariantId(v.variant_id)}
                  style={[styles.variantChip, on && styles.variantChipOn, !v.available && styles.variantChipOff]}
                >
                  {v.image_url ? (
                    <Image source={{ uri: mediaUrl(v.image_url) }} style={{ width: 40, height: 40, borderRadius: 8, marginRight: 8 }} contentFit="cover" />
                  ) : null}
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.variantTitle, on && { color: colors.primary }]} numberOfLines={2}>{v.title}</Text>
                    {!v.available && <Text style={styles.variantOos}>Sold out</Text>}
                  </View>
                  {!gated && <Text style={[styles.variantPrice, on && { color: colors.primary }]}>{centsToCAD(v.price_cents)}</Text>}
                  {on && <Ionicons name="checkmark-circle" size={18} color={colors.primary} style={{ marginLeft: 6 }} />}
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      )}

      {showCut && (
        <View style={styles.cutBox} testID="cut-preference-dropdown">
          <Text style={styles.variantLabel}>Cut Preference</Text>
          <TouchableOpacity
            testID="cut-preference-field"
            onPress={() => setCutOpen(o => !o)}
            style={[styles.cutField, cutOpen && styles.cutFieldOpen]}
          >
            <Text style={[styles.cutFieldText, !cut && { color: colors.textMuted }]}>
              {cut || "Choose how you want it cut"}
            </Text>
            <Ionicons name={cutOpen ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
          </TouchableOpacity>
          {cutOpen && (
            <View style={styles.cutList}>
              {CUT_OPTIONS.map((opt) => {
                const on = cut === opt;
                return (
                  <TouchableOpacity
                    key={opt}
                    testID={`cut-option-${opt.replace(/[^A-Za-z0-9]+/g, "-").toLowerCase()}`}
                    onPress={() => { setCut(opt); setCutOpen(false); }}
                    style={[styles.cutOption, on && styles.cutOptionOn]}
                  >
                    <Text style={[styles.cutOptionText, on && { color: colors.primary }]}>{opt}</Text>
                    {on && <Ionicons name="checkmark-circle" size={18} color={colors.primary} />}
                  </TouchableOpacity>
                );
              })}
            </View>
          )}
        </View>
      )}

      {item.description ? <Text style={styles.desc}>{item.description}</Text> : null}
    </>
  );

  const addControls = (
    <View style={styles.addRow}>
      <View style={[styles.qtyBox, (comingSoon || gated) && { opacity: 0.5 }]}>
        <TouchableOpacity testID="grocery-qty-minus" disabled={comingSoon || gated} onPress={() => setQty(q => Math.max(1, q - 1))} style={styles.qtyBtn}><Ionicons name="remove" size={18} color={colors.text} /></TouchableOpacity>
        <Text style={styles.qtyText}>{qty}</Text>
        <TouchableOpacity testID="grocery-qty-plus" disabled={comingSoon || gated} onPress={() => setQty(q => q + 1)} style={styles.qtyBtn}><Ionicons name="add" size={18} color={colors.text} /></TouchableOpacity>
      </View>
      {gated ? (
        <TouchableOpacity testID="grocery-enable-loc" style={[styles.addBtn, styles.comingBtn]} onPress={showHelp}>
          <Ionicons name="location-outline" size={18} color={colors.primary} />
          <Text style={[styles.addBtnText, { color: colors.primary }]}>Enable location to see price</Text>
        </TouchableOpacity>
      ) : comingSoon ? (
        <View testID="grocery-coming-soon" style={[styles.addBtn, styles.comingBtn]}>
          <Ionicons name="time-outline" size={18} color={colors.textMuted} />
          <Text style={[styles.addBtnText, { color: colors.textMuted }]}>Coming soon</Text>
        </View>
      ) : (
        <TouchableOpacity testID="grocery-add-to-bag" style={[styles.addBtn, !available && { opacity: 0.5 }]} disabled={!available} onPress={onAdd}>
          <Ionicons name={added ? "checkmark" : "bag-add"} size={18} color="#fff" />
          <Text style={styles.addBtnText}>{added ? "Added" : `Add · ${centsToCAD(unitPrice * qty)}`}</Text>
        </TouchableOpacity>
      )}
    </View>
  );

  const relatedNode = related.length > 0 ? (
    <View style={styles.relatedSection}>
      <Text style={styles.relatedTitle}>You may also like</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.relatedRow}>
        {related.map((g) => {
          const onSale = g.compare_at_cents > g.price_cents;
          return (
            <TouchableOpacity
              key={g.item_id}
              testID={`related-${g.item_id}`}
              activeOpacity={0.85}
              style={styles.relCard}
              onPress={() => router.push(`${linkBase}/${g.item_id}`)}
            >
              <View style={styles.relImgWrap}>
                {g.image_url ? (
                  <Image source={{ uri: mediaUrl(g.image_url) }} style={styles.relImg} contentFit="cover" transition={150} />
                ) : (
                  <View style={[styles.relImg, { alignItems: "center", justifyContent: "center" }]}>
                    <Ionicons name="image-outline" size={28} color={colors.textMuted} />
                  </View>
                )}
              </View>
              <Text style={styles.relName} numberOfLines={2}>{g.title}</Text>
              <View style={styles.relPriceRow}>
                <PriceGate compact>
                  <Text style={styles.relPrice}>{g.has_variants ? `from ${centsToCAD(g.price_cents)}` : centsToCAD(g.price_cents)}</Text>
                  {onSale && <Text style={styles.relCompare}>{centsToCAD(g.compare_at_cents)}</Text>}
                </PriceGate>
              </View>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  ) : null;

  // ─── Wide / website layout: image left, options right ───
  if (isWide) {
    return (
      <ScrollView contentContainerStyle={{ alignItems: "center", paddingBottom: 60 + bottomInset }}>
        <View style={styles.wideRow}>
          <View style={styles.wideImageCol}>
            <View style={styles.wideImageWrap}>{imageNode}</View>
          </View>
          <View style={styles.wideInfoCol}>
            {infoNode}
            <View style={styles.addControlsInline}>{addControls}</View>
          </View>
        </View>
        <View style={styles.relatedWideWrap}>{relatedNode}</View>
      </ScrollView>
    );
  }

  // ─── Narrow / mobile layout ───
  // web=true: inline add button (site header is sticky, no floating bars).
  // web=false: sticky bottom add bar (native app pattern) handled by caller.
  if (web) {
    return (
      <ScrollView contentContainerStyle={{ paddingBottom: 40 + bottomInset }}>
        <View style={styles.hero}>{imageNode}</View>
        <View style={styles.body}>
          {infoNode}
          <View style={styles.addControlsInline}>{addControls}</View>
        </View>
        {relatedNode}
      </ScrollView>
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 140 + bottomInset }}>
        <View style={styles.hero}>{imageNode}</View>
        <View style={styles.body}>{infoNode}</View>
        {relatedNode}
      </ScrollView>
      <View style={[styles.footer, { paddingBottom: bottomInset + 12 }]}>{addControls}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background, paddingVertical: 80 },
  hero: { width: "100%", aspectRatio: 1, maxHeight: 420, backgroundColor: colors.surfaceAlt },
  heroImg: { width: "100%", height: "100%" },
  body: { padding: spacing.lg, gap: 6, maxWidth: 720, width: "100%", alignSelf: "center" },
  cat: { color: colors.primary, letterSpacing: 2, fontSize: 11, fontWeight: "800" },
  name: { fontSize: 22, fontWeight: "800", color: colors.text, letterSpacing: -0.3 },
  priceRow: { flexDirection: "row", alignItems: "baseline", gap: 10, marginTop: 6 },
  price: { fontSize: 24, fontWeight: "800", color: colors.primary },
  compare: { fontSize: 15, color: colors.textMuted, textDecorationLine: "line-through" },
  oos: { fontSize: 12, color: colors.danger, fontWeight: "700" },

  wideRow: { flexDirection: "row", gap: spacing.xxl, width: "100%", maxWidth: 1120, padding: spacing.xl, alignItems: "flex-start" },
  wideImageCol: { flex: 1, maxWidth: 560 },
  wideImageWrap: { width: "100%", aspectRatio: 1, maxHeight: 560, borderRadius: radius.xl, overflow: "hidden", backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },
  wideInfoCol: { flex: 1, gap: 6, paddingTop: spacing.sm },
  addControlsInline: { marginTop: spacing.lg },

  variantBox: { marginTop: spacing.lg, gap: spacing.sm },
  variantLabel: { color: colors.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800" },
  variantList: { gap: 8 },
  variantChip: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 12, backgroundColor: colors.surface },
  variantChipOn: { borderColor: colors.primary, backgroundColor: colors.surfaceAlt },
  variantChipOff: { opacity: 0.45 },
  variantTitle: { fontSize: 14, fontWeight: "700", color: colors.text },
  variantOos: { fontSize: 11, color: colors.danger, fontWeight: "700", marginTop: 2 },
  variantPrice: { fontSize: 15, fontWeight: "800", color: colors.text },

  cutBox: { marginTop: spacing.lg, gap: spacing.sm },
  cutField: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 13, backgroundColor: colors.surface },
  cutFieldOpen: { borderColor: colors.primary },
  cutFieldText: { fontSize: 14, fontWeight: "700", color: colors.text },
  cutList: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surface },
  cutOption: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.md, paddingVertical: 12, borderTopWidth: 1, borderTopColor: colors.border },
  cutOptionOn: { backgroundColor: colors.surfaceAlt },
  cutOptionText: { fontSize: 14, fontWeight: "700", color: colors.text },

  desc: { color: colors.textMuted, fontSize: 14, lineHeight: 21, marginTop: 14 },
  footer: { backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, padding: spacing.lg, paddingTop: spacing.md },
  addRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  qtyBox: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, backgroundColor: colors.surfaceAlt },
  qtyBtn: { width: 40, height: 44, alignItems: "center", justifyContent: "center" },
  qtyText: { minWidth: 24, textAlign: "center", fontWeight: "800", color: colors.text, fontSize: 15 },
  addBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, borderRadius: radius.pill, height: 52, ...shadows.soft },
  addBtnText: { color: "#fff", fontSize: 15, fontWeight: "800" },
  comingBtn: { backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },

  relatedWideWrap: { width: "100%", maxWidth: 1120, paddingHorizontal: spacing.xl },
  relatedSection: { paddingHorizontal: spacing.lg, paddingTop: spacing.xl, paddingBottom: spacing.md, gap: spacing.md },
  relatedTitle: { fontSize: 18, fontWeight: "800", color: colors.text, letterSpacing: -0.2 },
  relatedRow: { gap: spacing.md, paddingRight: spacing.lg },
  relCard: { width: 150 },
  relImgWrap: { width: 150, aspectRatio: 1, borderRadius: radius.lg, overflow: "hidden", backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  relImg: { width: "100%", height: "100%" },
  relName: { fontSize: 13, fontWeight: "700", color: colors.text, lineHeight: 17, minHeight: 34 },
  relPriceRow: { flexDirection: "row", alignItems: "baseline", gap: 6, marginTop: 4 },
  relPrice: { fontSize: 14, fontWeight: "800", color: colors.primary },
  relCompare: { fontSize: 11, color: colors.textMuted, textDecorationLine: "line-through" },
});
