import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, TextInput, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import { api } from "@/src/api";
import { useCart } from "@/src/cart";
import { mediaUrl } from "@/src/utils/backendUrl";
import { centsToCAD } from "@/src/utils/format";
import { colors, spacing, radius, shadows } from "@/src/theme";

type ProteinOption = { option_id: string; name: string; price_cents: number };
type ThaliPackage = {
  package_id: string; name: string; thali_type: "veg" | "non_veg"; description: string;
  per_person_price_cents: number; protein_options: ProteinOption[];
  includes: string[]; min_guests: number; image_url: string;
};

const isoToday = () => new Date().toISOString().slice(0, 10);

/** Shared Thali Party Order flow used by the app (/thali) and web (/shop/thali). */
export function ThaliOrderBody({ web = false, bottomInset = 0 }: { web?: boolean; bottomInset?: number }) {
  const router = useRouter();
  const { add } = useCart();
  const { width } = useWindowDimensions();
  const isWide = width >= 900;

  const [packages, setPackages] = useState<ThaliPackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState<ThaliPackage | null>(null);
  const [proteinId, setProteinId] = useState<string | null>(null);
  const [guestsStr, setGuestsStr] = useState("25");
  const [date, setDate] = useState("");
  const [added, setAdded] = useState(false);

  useEffect(() => {
    (async () => {
      const r = await api.get<ThaliPackage[]>("/thali");
      const list = r.ok ? r.data : [];
      setPackages(list);
      if (list.length) selectPackage(list[0]);
      setLoading(false);
    })();
    // eslint-disable-next-line
  }, []);

  const selectPackage = (p: ThaliPackage) => {
    setSel(p);
    setGuestsStr(String(p.min_guests));
    setProteinId(p.thali_type === "non_veg" && p.protein_options.length ? p.protein_options[0].option_id : null);
    setAdded(false);
  };

  const protein = useMemo(
    () => sel?.protein_options.find(o => o.option_id === proteinId) || null,
    [sel, proteinId]
  );
  const perPerson = sel ? (sel.thali_type === "non_veg" && protein ? protein.price_cents : sel.per_person_price_cents) : 0;
  const guests = parseInt(guestsStr.replace(/[^0-9]/g, ""), 10) || 0;
  const belowMin = !!sel && guests < sel.min_guests;
  const total = perPerson * guests;
  const dateValid = !!date && /^\d{4}-\d{2}-\d{2}$/.test(date) && date >= isoToday();
  const canAdd = !!sel && !belowMin && dateValid && !(sel.thali_type === "non_veg" && !protein);

  const onAdd = () => {
    if (!sel || !canAdd) return;
    add({
      kind: "thali",
      ref_id: sel.package_id,
      name: sel.name + (protein ? ` — ${protein.name}` : ""),
      price_cents: perPerson,
      image_url: sel.image_url,
      thali_type: sel.thali_type,
      thali_guest_count: guests,
      thali_protein_option_id: protein?.option_id,
      thali_protein_title: protein?.name,
      thali_delivery_date: date,
    }, 1);
    setAdded(true);
    setTimeout(() => router.push(web ? "/shop/cart" : "/cart"), 500);
  };

  if (loading) return <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>;
  if (packages.length === 0) return <View style={styles.center}><Text style={{ color: colors.textMuted }}>Thali ordering is coming soon.</Text></View>;

  const builder = sel && (
    <View style={styles.builder}>
      {/* Protein */}
      {sel.thali_type === "non_veg" && sel.protein_options.length > 0 && (
        <View style={styles.block}>
          <Text style={styles.blockLabel}>CHOOSE YOUR PROTEIN</Text>
          <View style={styles.proteinRow}>
            {sel.protein_options.map(o => {
              const on = o.option_id === proteinId;
              return (
                <TouchableOpacity key={o.option_id} testID={`thali-protein-${o.option_id}`} onPress={() => setProteinId(o.option_id)}
                  style={[styles.proteinChip, on && styles.proteinChipOn]}>
                  <Text style={[styles.proteinName, on && { color: "#fff" }]}>{o.name}</Text>
                  <Text style={[styles.proteinPrice, on && { color: "#fff" }]}>{centsToCAD(o.price_cents)}/person</Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      )}

      {/* Guests */}
      <View style={styles.block}>
        <Text style={styles.blockLabel}>NUMBER OF GUESTS</Text>
        <View style={styles.guestRow}>
          <TouchableOpacity testID="thali-guests-minus" style={styles.stepBtn} onPress={() => setGuestsStr(String(Math.max(0, guests - 5)))}>
            <Ionicons name="remove" size={18} color={colors.text} />
          </TouchableOpacity>
          <TextInput testID="thali-guests-input" value={guestsStr} onChangeText={setGuestsStr} keyboardType="number-pad" style={styles.guestInput} />
          <TouchableOpacity testID="thali-guests-plus" style={styles.stepBtn} onPress={() => setGuestsStr(String(guests + 5))}>
            <Ionicons name="add" size={18} color={colors.text} />
          </TouchableOpacity>
        </View>
        {belowMin ? (
          <Text style={styles.errText} testID="thali-min-error">⚠ Minimum order is {sel.min_guests} guests for {sel.name}.</Text>
        ) : (
          <Text style={styles.hintText}>Minimum {sel.min_guests} guests.</Text>
        )}
      </View>

      {/* Delivery date */}
      <View style={styles.block}>
        <Text style={styles.blockLabel}>DELIVERY DATE</Text>
        <TextInput testID="thali-date-input" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" placeholderTextColor={colors.textMuted} style={styles.dateInput} />
        {!!date && !dateValid && <Text style={styles.errText}>Enter a valid future date (YYYY-MM-DD).</Text>}
      </View>

      {/* Includes */}
      {sel.includes.length > 0 && (
        <View style={styles.block}>
          <Text style={styles.blockLabel}>WHAT&apos;S INCLUDED</Text>
          {sel.includes.map((x, i) => (
            <View key={i} style={styles.incRow}>
              <Ionicons name="checkmark-circle" size={15} color={colors.primary} />
              <Text style={styles.incText}>{x}</Text>
            </View>
          ))}
        </View>
      )}

      {/* Total + add */}
      <View style={styles.totalBar}>
        <View>
          <Text style={styles.totalLabel}>Estimated total</Text>
          <Text style={styles.totalValue}>{centsToCAD(total)}</Text>
          <Text style={styles.totalMeta}>{centsToCAD(perPerson)}/person × {guests} guests</Text>
        </View>
        <TouchableOpacity testID="thali-add-to-bag" style={[styles.addBtn, !canAdd && { opacity: 0.5 }]} disabled={!canAdd} onPress={onAdd}>
          <Ionicons name={added ? "checkmark" : "bag-add"} size={18} color="#fff" />
          <Text style={styles.addBtnText}>{added ? "Added" : "Add to bag"}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  return (
    <ScrollView contentContainerStyle={{ alignItems: "center", paddingBottom: 60 + bottomInset }}>
      <View style={[styles.inner, { maxWidth: 1100 }]}>
        <View style={styles.intro}>
          <Text style={styles.kicker}>PARTY & EVENTS</Text>
          <Text style={styles.title}>Thali Party Order</Text>
          <Text style={styles.sub}>Bulk thalis for parties & events — pick a thali, choose your protein, set your guest count and date.</Text>
        </View>

        <View style={[styles.layout, isWide && { flexDirection: "row" }]}>
          {/* Package chooser */}
          <View style={[styles.pkgCol, isWide && { maxWidth: 420 }]}>
            {packages.map(p => {
              const on = sel?.package_id === p.package_id;
              const from = p.thali_type === "non_veg" && p.protein_options.length
                ? Math.min(...p.protein_options.map(o => o.price_cents)) : p.per_person_price_cents;
              return (
                <TouchableOpacity key={p.package_id} testID={`thali-pkg-${p.package_id}`} activeOpacity={0.9}
                  onPress={() => selectPackage(p)} style={[styles.pkgCard, on && styles.pkgCardOn]}>
                  <View style={styles.pkgImgWrap}>
                    {p.image_url ? <Image source={{ uri: mediaUrl(p.image_url) }} style={styles.pkgImg} contentFit="cover" /> :
                      <View style={[styles.pkgImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="fast-food" size={30} color={colors.textMuted} /></View>}
                  </View>
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Text style={styles.pkgName}>{p.name}</Text>
                      <View style={[styles.vegTag, { backgroundColor: p.thali_type === "veg" ? "#16803722" : "#B91C1C22" }]}>
                        <Text style={[styles.vegTagText, { color: p.thali_type === "veg" ? "#15803D" : "#B91C1C" }]}>{p.thali_type === "veg" ? "VEG" : "NON-VEG"}</Text>
                      </View>
                    </View>
                    <Text style={styles.pkgPrice}>{p.thali_type === "non_veg" ? "From " : ""}{centsToCAD(from)}/person · min {p.min_guests}</Text>
                    <Text style={styles.pkgDesc} numberOfLines={2}>{p.description}</Text>
                  </View>
                  <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={20} color={on ? colors.primary : colors.textMuted} />
                </TouchableOpacity>
              );
            })}
          </View>

          {/* Builder */}
          <View style={{ flex: 1 }}>{builder}</View>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 80, backgroundColor: colors.background },
  inner: { width: "100%", paddingHorizontal: spacing.lg, paddingTop: spacing.lg, gap: spacing.lg },
  intro: { gap: 4 },
  kicker: { color: colors.primary, letterSpacing: 2, fontSize: 11, fontWeight: "900" },
  title: { fontSize: 28, fontWeight: "900", color: colors.text, letterSpacing: -0.6 },
  sub: { fontSize: 14, color: colors.textMuted, lineHeight: 20, maxWidth: 560 },

  layout: { flexDirection: "column", gap: spacing.lg },
  pkgCol: { gap: spacing.md },
  pkgCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.md, borderRadius: radius.lg, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface },
  pkgCardOn: { borderColor: colors.primary, backgroundColor: colors.surfaceAlt },
  pkgImgWrap: { width: 64, height: 64, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surfaceAlt },
  pkgImg: { width: "100%", height: "100%" },
  pkgName: { fontSize: 16, fontWeight: "800", color: colors.text },
  vegTag: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  vegTagText: { fontSize: 9, fontWeight: "900", letterSpacing: 1 },
  pkgPrice: { fontSize: 13, color: colors.primary, fontWeight: "700", marginTop: 2 },
  pkgDesc: { fontSize: 12, color: colors.textMuted, marginTop: 2 },

  builder: { gap: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.xl, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, ...shadows.soft },
  block: { gap: 8 },
  blockLabel: { color: colors.textMuted, letterSpacing: 2, fontSize: 11, fontWeight: "800" },
  proteinRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  proteinChip: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surfaceAlt, alignItems: "center" },
  proteinChipOn: { borderColor: colors.primary, backgroundColor: colors.primary },
  proteinName: { fontSize: 14, fontWeight: "800", color: colors.text },
  proteinPrice: { fontSize: 11, color: colors.textMuted, marginTop: 2 },

  guestRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  stepBtn: { width: 46, height: 46, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceAlt, alignItems: "center", justifyContent: "center" },
  guestInput: { minWidth: 90, textAlign: "center", fontSize: 20, fontWeight: "800", color: colors.text, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingVertical: 8, paddingHorizontal: 12, backgroundColor: colors.surface },
  dateInput: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 12, color: colors.text, fontSize: 15, backgroundColor: colors.surface, maxWidth: 220 },
  errText: { color: colors.danger, fontSize: 12.5, fontWeight: "700" },
  hintText: { color: colors.textMuted, fontSize: 12 },

  incRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  incText: { fontSize: 14, color: colors.text },

  totalBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.md, gap: spacing.md, flexWrap: "wrap" },
  totalLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "700" },
  totalValue: { fontSize: 26, fontWeight: "900", color: colors.primary },
  totalMeta: { fontSize: 12, color: colors.textMuted },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.primary, borderRadius: radius.pill, paddingHorizontal: 28, height: 54, ...shadows.soft },
  addBtnText: { color: "#fff", fontSize: 15, fontWeight: "800" },
});
