import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, ActivityIndicator,
} from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useLocalSearchParams, useRouter, Stack } from "expo-router";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { api } from "@/src/api";
import { mediaUrl } from "@/src/utils/backendUrl";
import { useCart } from "@/src/cart";
import { colors, spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";

type Item = { item_id: string; name: string; description: string; price_cents: number; image_url: string; category: string; tags: string[]; is_featured: boolean; veg_type?: string; };
type WeeklyPackage = {
  package_id: string; name: string; description?: string; price_cents: number;
  pick_count: number; eligible_master_ids: string[]; image_url?: string;
  item_surcharges_cents?: Record<string, number>;
  pricing_mode?: string;
  veg_price_cents?: number; mixed_price_cents?: number; nonveg_price_cents?: number;
  complimentary_master_ids?: string[];
  max_per_dish?: number;
  veg_pick_count?: number; nonveg_pick_count?: number;
  mixed_veg_count?: number; mixed_nonveg_count?: number;
};
type Compl = { item_id: string; name: string; description: string; image_url: string; category: string; };
type WeeklyMenu = {
  menu_id: string; week_start: string; title: string; items: Item[];
  package_enabled?: boolean; package?: WeeklyPackage | null;
  complimentary_items?: Compl[];
};

export default function PackageCustomize() {
  const { id, from } = useLocalSearchParams<{ id: string; from?: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { add } = useCart();

  const [wm, setWm] = useState<WeeklyMenu | null>(null);
  const [loading, setLoading] = useState(true);
  // NEW: map of master_item_id → quantity picked. Sum(values) === pickCount when valid.
  const [qty, setQty] = useState<Record<string, number>>({});

  useEffect(() => {
    (async () => {
      // Since we currently only allow a package on the CURRENT week, use /menu/current.
      const r = await api.get<WeeklyMenu>("/menu/current");
      if (r.ok && r.data) {
        // Sanity: menu_id must match id from param (or accept any current)
        setWm(r.data);
      }
      setLoading(false);
    })();
  }, [id]);

  const pkg = wm?.package;
  const pickCount = pkg?.pick_count || 0;

  const eligibleItems: Item[] = useMemo(() => {
    if (!wm || !pkg) return [];
    const eligible = pkg.eligible_master_ids && pkg.eligible_master_ids.length > 0
      ? new Set(pkg.eligible_master_ids)
      : null;
    return wm.items.filter(i => !eligible || eligible.has(i.item_id));
  }, [wm, pkg]);

  const totalPicked = useMemo(() => Object.values(qty).reduce((a, b) => a + b, 0), [qty]);

  const isComposition = pkg?.pricing_mode === "composition";

  // Fixed bundle: flat price, pick_count == every eligible dish, max 1 each —
  // the bundle IS all dishes, so there is nothing to pick. All dishes are
  // pre-included, steppers stay disabled, and one tap orders the plan.
  // Any other shape falls back to normal picking.
  const maxPerEarly = pkg?.max_per_dish || 0;
  const isFixedBundle = !isComposition && (pkg?.pick_count || 0) > 0
    && eligibleItems.length === (pkg?.pick_count || 0) && maxPerEarly === 1;
  useEffect(() => {
    if (isFixedBundle && eligibleItems.length > 0) {
      const all: Record<string, number> = {};
      eligibleItems.forEach(it => { all[it.item_id] = 1; });
      setQty(all);
    }
  }, [isFixedBundle, eligibleItems]);

  // Count non-veg portions among picks (egg counts as non-veg).
  const vegTypeOf = (mid: string) => wm?.items.find(x => x.item_id === mid)?.veg_type || "vegetarian";
  const nonVegPicked = useMemo(() => {
    let s = 0;
    for (const [mid, q] of Object.entries(qty)) if (vegTypeOf(mid) !== "vegetarian") s += q;
    return s;
  }, [qty, wm]);
  const vegPicked = totalPicked - nonVegPicked;
  const remaining = Math.max(0, pickCount - totalPicked);

  // ---- Fixed-composition plan config ----
  const maxPer = pkg?.max_per_dish || 0;                       // 0 = unlimited
  const vegN = pkg?.veg_pick_count || pkg?.pick_count || 0;     // all-veg plan size
  const nonvegN = pkg?.nonveg_pick_count || pkg?.pick_count || 0; // all-non-veg plan size
  const mixedV = pkg?.mixed_veg_count || 0;                    // mixed: veg dishes
  const mixedNV = pkg?.mixed_nonveg_count || 0;                // mixed: non-veg dishes
  const hasMixedPlan = mixedV > 0 && mixedNV > 0;
  // Largest plan size — used to cap total picks in free-build.
  const maxPlanTotal = isComposition ? Math.max(vegN, nonvegN, mixedV + mixedNV, pickCount) : pickCount;

  // Which fixed plan does the CURRENT selection satisfy (null when none yet).
  const matchedPlan: "all-veg" | "mixed" | "all-non-veg" | null = useMemo(() => {
    if (!isComposition) return null;
    if (nonVegPicked === 0 && vegN > 0 && vegPicked === vegN) return "all-veg";
    if (vegPicked === 0 && nonvegN > 0 && nonVegPicked === nonvegN) return "all-non-veg";
    if (hasMixedPlan && vegPicked === mixedV && nonVegPicked === mixedNV) return "mixed";
    return null;
  }, [isComposition, vegPicked, nonVegPicked, vegN, nonvegN, mixedV, mixedNV, hasMixedPlan]);

  // ---- Which plans are still reachable, and per-category add gating ----
  // Each plan is a (veg,nonveg) target. A hypothetical selection is reachable
  // if some plan can still be completed from it (v<=target.v and n<=target.n).
  const plans = useMemo(() => {
    const ps: { v: number; n: number }[] = [];
    if (vegN > 0) ps.push({ v: vegN, n: 0 });
    if (hasMixedPlan) ps.push({ v: mixedV, n: mixedNV });
    if (nonvegN > 0) ps.push({ v: 0, n: nonvegN });
    return ps;
  }, [vegN, nonvegN, mixedV, mixedNV, hasMixedPlan]);
  const canReach = (v: number, n: number) => plans.some(p => v <= p.v && n <= p.n);
  const canAddVeg = !isComposition || canReach(vegPicked + 1, nonVegPicked);
  const canAddNonVeg = !isComposition || canReach(vegPicked, nonVegPicked + 1);

  // Total per-portion surcharges from the customer's picks.
  const surchargeMap = pkg?.item_surcharges_cents || {};
  const surchargeTotal = useMemo(() => {
    let s = 0;
    for (const [mid, q] of Object.entries(qty)) s += (surchargeMap[mid] || 0) * q;
    return s;
  }, [qty, surchargeMap]);

  const planBasePrice =
    matchedPlan === "all-veg" ? (pkg?.veg_price_cents || 0)
    : matchedPlan === "all-non-veg" ? (pkg?.nonveg_price_cents || 0)
    : matchedPlan === "mixed" ? (pkg?.mixed_price_cents || 0)
    : 0;

  const effectiveTotal = isComposition
    ? (matchedPlan ? planBasePrice + surchargeTotal : 0)
    : (pkg?.price_cents || 0) + surchargeTotal;

  const inc = (mid: string) => {
    if (totalPicked >= maxPlanTotal) return;
    if (maxPer > 0 && (qty[mid] || 0) >= maxPer) return;
    setQty(prev => ({ ...prev, [mid]: (prev[mid] || 0) + 1 }));
  };
  const dec = (mid: string) => {
    setQty(prev => {
      const cur = prev[mid] || 0;
      if (cur <= 0) return prev;
      const next = { ...prev, [mid]: cur - 1 };
      if (next[mid] === 0) delete next[mid];
      return next;
    });
  };

  const alacarteTotal = useMemo(() => {
    let s = 0;
    for (const [mid, q] of Object.entries(qty)) {
      const it = wm?.items.find(x => x.item_id === mid);
      s += (it?.price_cents || 0) * q;
    }
    return s;
  }, [qty, wm]);
  const savings = Math.max(0, alacarteTotal - effectiveTotal);

  const isValid = isComposition ? matchedPlan !== null : (totalPicked === pickCount && pickCount > 0);

  const planLabel = (kind: "all-veg" | "mixed" | "all-non-veg") =>
    kind === "all-veg" ? `${vegN} Veg plan`
    : kind === "all-non-veg" ? `${nonvegN} Non-Veg plan`
    : `${mixedV} Veg + ${mixedNV} Non-Veg plan`;

  // Short guidance while the customer is still building a valid plan.
  const guidance = useMemo(() => {
    if (!isComposition) return "";
    const opts: string[] = [];
    if (vegN > 0) opts.push(`${vegN} veg`);
    if (hasMixedPlan) opts.push(`${mixedV} veg + ${mixedNV} non-veg`);
    if (nonvegN > 0) opts.push(`${nonvegN} non-veg`);
    return `Pick ${opts.join(", or ")}`;
  }, [isComposition, vegN, nonvegN, mixedV, mixedNV, hasMixedPlan]);

  const onAdd = () => {
    if (!wm || !pkg || !isValid) return;

    // Expanded id list preserves quantities for the backend / kitchen ticket.
    const expandedIds: string[] = [];
    // Human-readable, aggregated for display: "Biryani × 3", "Rasgulla × 2"
    const displayLines: string[] = [];
    for (const [mid, q] of Object.entries(qty)) {
      const it = wm.items.find(x => x.item_id === mid);
      const name = it?.name || mid;
      for (let i = 0; i < q; i++) expandedIds.push(mid);
      displayLines.push(q > 1 ? `${name} × ${q}` : name);
    }

    add({
      kind: "weekly_package",
      ref_id: wm.menu_id,
      name: pkg.name,
      price_cents: effectiveTotal,     // base + selected surcharges (server re-computes for safety)
      image_url: pkg.image_url || wm.items[0]?.image_url || "",
      package_selections: expandedIds,
      package_selection_names: displayLines,
      package_pick_count: totalPicked,
      weekly_menu_id: wm.menu_id,
      selection_labels: [{ title: isComposition && matchedPlan ? planLabel(matchedPlan) : `Pick ${pickCount}`, items: displayLines }],
    });
    router.replace(from === "shop" ? "/shop/cart" : "/cart");
  };

  const vegItems = eligibleItems.filter(i => (i.veg_type || "vegetarian") === "vegetarian");
  const nonVegItems = eligibleItems.filter(i => (i.veg_type || "vegetarian") !== "vegetarian");

  const renderRow = (it: Item) => {
    const n = qty[it.item_id] || 0;
    const on = n > 0;
    const isVeg = (it.veg_type || "vegetarian") === "vegetarian";
    const atMax = maxPer > 0 && n >= maxPer;
    const catCanAdd = isComposition ? (isVeg ? canAddVeg : canAddNonVeg) : totalPicked < maxPlanTotal;
    const canInc = !atMax && catCanAdd && totalPicked < maxPlanTotal;
    const dimmed = isComposition && n === 0 && !catCanAdd;
    const surcharge = surchargeMap[it.item_id] || 0;
    return (
      <View
        key={it.item_id}
        testID={`pkg-option-${it.item_id}`}
        style={[styles.optRow, on && styles.optRowActive, dimmed && styles.optRowDim]}
      >
        <Image source={{ uri: mediaUrl(it.image_url) }} style={styles.optImg} />
        <View style={{ flex: 1, gap: 2 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <View
              testID={`pkg-vegmark-${isVeg ? "veg" : "nonveg"}-${it.item_id}`}
              style={[styles.vegMark, isVeg ? styles.vegMarkVeg : styles.vegMarkNon]}
            >
              <View style={[styles.vegDot, isVeg ? styles.vegDotVeg : styles.vegDotNon]} />
            </View>
            <Text style={styles.optName} numberOfLines={1}>{it.name}</Text>
            {it.is_featured && <View style={styles.tagFeat}><Text style={styles.tagFeatText}>★</Text></View>}
            {surcharge > 0 && (
              <View style={styles.surTag} testID={`pkg-surcharge-tag-${it.item_id}`}>
                <Ionicons name="add" size={10} color="#fff" />
                <Text style={styles.surTagText}>{centsToCAD(surcharge)}</Text>
              </View>
            )}
          </View>
          <Text style={styles.optDesc} numberOfLines={2}>{it.description}</Text>
          {it.price_cents > 0 && (
            <Text style={styles.optPrice}>
              À la carte {centsToCAD(it.price_cents)}
              {surcharge > 0 ? ` · +${centsToCAD(surcharge)} per portion in combo` : ""}
              {atMax ? ` · max ${maxPer} reached` : ""}
            </Text>
          )}
          {dimmed && (
            <Text style={styles.optBlocked} testID={`pkg-blocked-${it.item_id}`}>
              {isVeg ? "Adding veg no longer fits any plan" : "Adding non-veg no longer fits any plan"}
            </Text>
          )}
        </View>

        {/* Qty stepper */}
        <View style={styles.qtyBox}>
          <TouchableOpacity
            testID={`pkg-dec-${it.item_id}`}
            disabled={isFixedBundle || !on}
            onPress={() => dec(it.item_id)}
            style={[styles.qtyBtn, !on && styles.qtyBtnDisabled]}
          >
            <Ionicons name="remove" size={18} color={on ? colors.text : colors.textMuted} />
          </TouchableOpacity>
          <Text style={[styles.qtyText, on && styles.qtyTextActive]}>{n}</Text>
          <TouchableOpacity
            testID={`pkg-inc-${it.item_id}`}
            disabled={isFixedBundle || !canInc}
            onPress={() => inc(it.item_id)}
            style={[styles.qtyBtn, canInc ? styles.qtyBtnAdd : styles.qtyBtnDisabled]}
          >
            <Ionicons name="add" size={18} color={canInc ? "#fff" : colors.textMuted} />
          </TouchableOpacity>
        </View>
      </View>
    );
  };

  if (loading) return <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>;
  if (!wm || !pkg) {
    return (
      <View style={styles.center}>
        <Text style={styles.err}>No weekly package is available.</Text>
        <TouchableOpacity onPress={() => router.back()} style={styles.backCta}><Text style={styles.backCtaText}>Go back</Text></TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Stack.Screen options={{ headerShown: false }} />
      <SafeAreaView edges={["top"]} style={styles.hdr}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="pkg-back">
          <Ionicons name="chevron-back" size={22} color={colors.text} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.hdrTitle} numberOfLines={1}>Weekly Combo</Text>
          <Text style={styles.hdrSub} numberOfLines={1}>{pkg.name}</Text>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={{ paddingBottom: 220 + insets.bottom }} showsVerticalScrollIndicator={false}>
        <Image source={{ uri: mediaUrl(pkg.image_url || eligibleItems[0]?.image_url) }} style={styles.hero} />
        <View style={styles.headBlock}>
          <Text style={styles.packName}>{pkg.name}</Text>
          {pkg.description ? <Text style={styles.packTagline}>{pkg.description}</Text> : null}
          {isComposition ? (
            <View style={{ gap: 6, marginTop: 4 }}>
              <Text style={styles.packMeta}>Build one plan · {guidance.toLowerCase()}{maxPer > 0 ? ` · max ${maxPer} of a dish` : ""}</Text>
              <View style={styles.tierRow} testID="pkg-pricing-tiers">
                <View style={[styles.tierChip, matchedPlan === "all-veg" && styles.tierChipOn]}><Text style={styles.tierChipLabel}>{vegN} Veg</Text><Text style={styles.tierChipPrice}>{centsToCAD(pkg.veg_price_cents || 0)}</Text></View>
                {hasMixedPlan && <View style={[styles.tierChip, matchedPlan === "mixed" && styles.tierChipOn]}><Text style={styles.tierChipLabel}>{mixedV} Veg + {mixedNV} NV</Text><Text style={styles.tierChipPrice}>{centsToCAD(pkg.mixed_price_cents || 0)}</Text></View>}
                <View style={[styles.tierChip, matchedPlan === "all-non-veg" && styles.tierChipOn]}><Text style={styles.tierChipLabel}>{nonvegN} Non-Veg</Text><Text style={styles.tierChipPrice}>{centsToCAD(pkg.nonveg_price_cents || 0)}</Text></View>
              </View>
            </View>
          ) : (
            <View style={styles.summaryRow}>
              <Text style={styles.packPrice}>{centsToCAD(pkg.price_cents)}</Text>
              <Text style={styles.packMeta}>{isFixedBundle ? `total · all ${pickCount} dishes included` : `total · pick ${pickCount} portions · repeats allowed`}</Text>
            </View>
          )}
        </View>

        <View style={styles.stickyProgress}>
          <View style={{ flex: 1 }}>
            <Text style={styles.progressTitle}>
              {isFixedBundle ? "This week's plan" : isValid ? "All set!" : isComposition ? "Build your plan" : remaining === 1 ? "Pick 1 more" : `Pick ${remaining} more`}
            </Text>
            <Text style={styles.progressSub}>
              {isFixedBundle
                ? "All dishes included · no picking needed"
                : isComposition
                ? `${vegPicked} veg · ${nonVegPicked} non-veg`
                : `${totalPicked} / ${pickCount} selected`}
            </Text>
            {isComposition && (
              <Text style={styles.progressPrice} testID="pkg-live-price">
                {isValid ? `Total ${centsToCAD(effectiveTotal)}` : guidance}
              </Text>
            )}
          </View>
          {savings > 0 && (
            <View style={styles.savingsBadge}>
              <Ionicons name="pricetag" size={12} color="#fff" />
              <Text style={styles.savingsText}>Save {centsToCAD(savings)}</Text>
            </View>
          )}
        </View>

        <View style={{ padding: spacing.lg, gap: spacing.sm }}>
          {isComposition ? (
            <>
              {vegItems.length > 0 && (
                <View style={styles.groupHead} testID="pkg-group-veg">
                  <View style={[styles.vegMark, styles.vegMarkVeg]}><View style={[styles.vegDot, styles.vegDotVeg]} /></View>
                  <Text style={styles.groupHeadText}>Vegetarian</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={styles.groupHeadCount}>{vegPicked > 0 ? `${vegPicked} selected` : `${vegItems.length} dishes`}</Text>
                </View>
              )}
              {vegItems.map(renderRow)}
              {nonVegItems.length > 0 && (
                <View style={[styles.groupHead, { marginTop: spacing.md }]} testID="pkg-group-nonveg">
                  <View style={[styles.vegMark, styles.vegMarkNon]}><View style={[styles.vegDot, styles.vegDotNon]} /></View>
                  <Text style={styles.groupHeadText}>Non-Vegetarian</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={styles.groupHeadCount}>{nonVegPicked > 0 ? `${nonVegPicked} selected` : `${nonVegItems.length} dishes`}</Text>
                </View>
              )}
              {nonVegItems.map(renderRow)}
            </>
          ) : (
            eligibleItems.map(renderRow)
          )}
          {eligibleItems.length === 0 && (
            <Text style={styles.err}>No eligible items available in this week&apos;s menu.</Text>
          )}
        </View>

        {wm.complimentary_items && wm.complimentary_items.length > 0 && (
          <View style={styles.compWrap} testID="pkg-complimentary">
            <View style={styles.compHead}>
              <Ionicons name="gift-outline" size={16} color={colors.secondary} />
              <Text style={styles.compTitle}>Complimentary this week</Text>
              <View style={styles.compFreeTag}><Text style={styles.compFreeText}>FREE</Text></View>
            </View>
            <Text style={styles.compSub}>Included with every weekly plan — no selection needed.</Text>
            {wm.complimentary_items.map(c => (
              <View key={c.item_id} style={styles.compRow} testID={`pkg-comp-${c.item_id}`}>
                <Image source={{ uri: mediaUrl(c.image_url) }} style={styles.compImg} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.compName} numberOfLines={1}>{c.name}</Text>
                  {!!c.description && <Text style={styles.compDesc} numberOfLines={2}>{c.description}</Text>}
                </View>
                <Ionicons name="checkmark-circle" size={20} color={colors.success} />
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      {/* Sticky footer */}
      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        <View style={{ flex: 1 }}>
          <Text style={styles.footerLabel}>Package total</Text>
          <Text style={styles.footerTotal} testID="pkg-total">{centsToCAD(effectiveTotal)}</Text>
          {isComposition && isValid && matchedPlan && (
            <Text style={styles.footerBreakdown} testID="pkg-composition-line">
              {planLabel(matchedPlan)}{surchargeTotal > 0 ? ` + ${centsToCAD(surchargeTotal)} premium picks` : ""}
            </Text>
          )}
          {!isComposition && surchargeTotal > 0 && (
            <Text style={styles.footerBreakdown} testID="pkg-surcharge-line">
              {centsToCAD(pkg.price_cents)} combo + {centsToCAD(surchargeTotal)} premium picks
            </Text>
          )}
          {savings > 0 && (
            <Text style={styles.footerSavings}>You save {centsToCAD(savings)} vs à la carte</Text>
          )}
        </View>
        <TouchableOpacity
          testID="pkg-add-to-bag"
          style={[styles.addBtn, !isValid && { opacity: 0.5 }]}
          disabled={!isValid}
          onPress={onAdd}
        >
          <Ionicons name="bag-add" size={18} color="#fff" />
          <Text style={styles.addBtnText}>{isFixedBundle ? "Order this week's plan" : "Add to Bag"}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background, padding: spacing.lg, gap: spacing.md },
  err: { color: colors.textMuted, textAlign: "center" },
  backCta: { backgroundColor: colors.primary, paddingHorizontal: 18, paddingVertical: 10, borderRadius: radius.pill },
  backCtaText: { color: "#fff", fontWeight: "800" },

  hdr: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  backBtn: { width: 40, height: 40, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceAlt },
  hdrTitle: { fontSize: 12, letterSpacing: 3, fontWeight: "800", color: colors.primary },
  hdrSub: { fontSize: 15, fontWeight: "800", color: colors.text, marginTop: 2 },

  hero: { width: "100%", height: 200, backgroundColor: colors.surfaceAlt },
  headBlock: { padding: spacing.lg, gap: 6 },
  packName: { fontSize: 22, fontWeight: "800", color: colors.text, letterSpacing: -0.3 },
  packTagline: { fontSize: 13, color: colors.textMuted, lineHeight: 19 },
  summaryRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.sm, marginTop: 4, flexWrap: "wrap" },
  packPrice: { fontSize: 22, fontWeight: "800", color: colors.primary },
  packMeta: { fontSize: 12, color: colors.textMuted },

  stickyProgress: { flexDirection: "row", alignItems: "center", padding: spacing.md, marginHorizontal: spacing.lg, borderRadius: radius.md, backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },
  progressTitle: { fontSize: 14, fontWeight: "800", color: colors.text },
  progressSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  progressPrice: { fontSize: 13, color: colors.primary, fontWeight: "800", marginTop: 2 },
  tierRow: { flexDirection: "row", gap: spacing.sm },
  tierChip: { flex: 1, backgroundColor: colors.surfaceAlt, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, paddingVertical: 8, alignItems: "center" },
  tierChipOn: { borderColor: colors.primary, borderWidth: 2, backgroundColor: "#F0F4FF" },
  vegMark: { width: 16, height: 16, borderRadius: 3, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  vegMarkVeg: { borderColor: "#1A8917" },
  vegMarkNon: { borderColor: "#B3402F" },
  vegDot: { width: 7, height: 7, borderRadius: 4 },
  vegDotVeg: { backgroundColor: "#1A8917" },
  vegDotNon: { backgroundColor: "#B3402F" },
  optRowDim: { opacity: 0.45 },
  optBlocked: { fontSize: 11, color: colors.textMuted, fontStyle: "italic" },
  groupHead: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6, paddingHorizontal: 2, borderBottomWidth: 1, borderBottomColor: colors.border, marginBottom: 2 },
  groupHeadText: { fontSize: 15, fontWeight: "800", color: colors.text, letterSpacing: 0.3 },
  groupHeadCount: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  tierChipLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  tierChipPrice: { fontSize: 15, color: colors.text, fontWeight: "800", marginTop: 2 },
  compWrap: { marginHorizontal: spacing.lg, marginTop: spacing.sm, padding: spacing.md, backgroundColor: "#FFFBF2", borderRadius: radius.md, borderWidth: 1, borderColor: colors.secondary, gap: spacing.sm },
  compHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  compTitle: { fontSize: 14, fontWeight: "800", color: colors.text, flex: 1 },
  compFreeTag: { backgroundColor: colors.success, paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill },
  compFreeText: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  compSub: { fontSize: 12, color: colors.textMuted, marginTop: -2 },
  compRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.sm, borderWidth: 1, borderColor: colors.border },
  compImg: { width: 48, height: 48, borderRadius: radius.sm, backgroundColor: colors.surfaceAlt },
  compName: { fontSize: 14, fontWeight: "700", color: colors.text },
  compDesc: { fontSize: 12, color: colors.textMuted, lineHeight: 16 },
  savingsBadge: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.success, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  savingsText: { color: "#fff", fontSize: 12, fontWeight: "800" },

  optRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  optRowActive: { borderColor: colors.primary, backgroundColor: "#FFF7F3" },
  optImg: { width: 64, height: 64, borderRadius: radius.sm, backgroundColor: colors.surfaceAlt },
  optName: { fontSize: 14, fontWeight: "800", color: colors.text, flex: 1 },
  optDesc: { fontSize: 12, color: colors.textMuted, lineHeight: 16 },
  optPrice: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  tagFeat: { backgroundColor: colors.secondary, paddingHorizontal: 4, borderRadius: 4 },
  tagFeatText: { color: "#1a1a1a", fontSize: 10, fontWeight: "900" },
  surTag: { flexDirection: "row", alignItems: "center", backgroundColor: colors.primary, paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4 },
  surTagText: { color: "#fff", fontSize: 10, fontWeight: "800" },

  qtyBox: { flexDirection: "row", alignItems: "center", gap: 6 },
  qtyBtn: { width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceAlt },
  qtyBtnAdd: { backgroundColor: colors.primary, borderColor: colors.primary },
  qtyBtnDisabled: { opacity: 0.4 },
  qtyText: { minWidth: 20, textAlign: "center", color: colors.textMuted, fontWeight: "800", fontSize: 14 },
  qtyTextActive: { color: colors.text },

  footer: { position: "absolute", bottom: 0, left: 0, right: 0, flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, ...shadows.card },
  footerLabel: { fontSize: 11, color: colors.textMuted, letterSpacing: 1, fontWeight: "700" },
  footerTotal: { fontSize: 22, fontWeight: "800", color: colors.primary, marginTop: 2 },
  footerSavings: { fontSize: 11, color: colors.success, fontWeight: "700" },
  footerBreakdown: { fontSize: 11, color: colors.textMuted, fontWeight: "600", marginTop: 1 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, paddingHorizontal: 22, paddingVertical: 14, borderRadius: radius.pill, ...shadows.soft },
  addBtnText: { color: "#fff", fontSize: 14, fontWeight: "800" },
});
