import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Image,
  TextInput, ScrollView, Modal, Alert,
} from "react-native";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import AdminShell from "@/src/components/AdminShell";
import { adminApi, getAdminToken } from "@/src/adminApi";
import { colors, spacing, radius, shadows } from "@/src/theme";

type ProteinOption = { option_id: string; name: string; price_cents: number };
type ThaliPackage = {
  package_id: string; name: string; thali_type: "veg" | "non_veg"; description: string;
  per_person_price_cents: number; protein_options: ProteinOption[];
  includes: string[]; min_guests: number; image_url: string;
  is_active: boolean; sort_order: number;
};

const rndId = (p: string) => `${p}_${Math.random().toString(36).slice(2, 10)}`;

const makeBlank = (): ThaliPackage => ({
  package_id: rndId("th"), name: "", thali_type: "veg", description: "",
  per_person_price_cents: 999, protein_options: [], includes: [],
  min_guests: 25, image_url: "", is_active: true, sort_order: 0,
});

export default function AdminThali() {
  const router = useRouter();
  const [items, setItems] = useState<ThaliPackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState<ThaliPackage | null>(null);
  const [priceStr, setPriceStr] = useState("");
  const [includesText, setIncludesText] = useState("");
  const [confirmDel, setConfirmDel] = useState<ThaliPackage | null>(null);

  const load = useCallback(async () => {
    const r = await adminApi.get<ThaliPackage[]>("/admin/thali");
    if (r.status === 401) { router.replace("/admin"); return; }
    if (r.ok) setItems(r.data || []);
    setLoading(false);
  }, [router]);

  useEffect(() => {
    (async () => {
      const t = await getAdminToken();
      if (!t) return router.replace("/admin");
      await load();
    })();
  }, [router, load]);

  const openEdit = (p: ThaliPackage | null) => {
    const target: ThaliPackage = p ? JSON.parse(JSON.stringify(p)) : makeBlank();
    setEdit(target);
    setPriceStr((target.per_person_price_cents / 100).toFixed(2));
    setIncludesText(target.includes.join("\n"));
  };

  const save = async () => {
    if (!edit) return;
    if (!edit.name.trim()) { Alert.alert("Missing name", "Please enter a thali name."); return; }
    if (edit.thali_type === "non_veg" && edit.protein_options.length === 0) {
      Alert.alert("Add a protein", "Non-veg thali needs at least one protein option.");
      return;
    }
    const body: ThaliPackage = {
      ...edit,
      per_person_price_cents: Math.round((parseFloat(priceStr) || 0) * 100),
      includes: includesText.split("\n").map(s => s.trim()).filter(Boolean),
    };
    const r = await adminApi.post("/admin/thali", body);
    if (r.ok) { setEdit(null); await load(); }
    else Alert.alert("Save failed", r.error);
  };

  const doDelete = async () => {
    if (!confirmDel) return;
    const r = await adminApi.del(`/admin/thali/${confirmDel.package_id}`);
    setConfirmDel(null);
    if (r.ok) await load();
  };

  // protein helpers
  const addProtein = () => {
    if (!edit) return;
    setEdit({ ...edit, protein_options: [...edit.protein_options, { option_id: rndId("tp"), name: "", price_cents: 1199 }] });
  };
  const updProtein = (id: string, patch: Partial<ProteinOption>) => {
    if (!edit) return;
    setEdit({ ...edit, protein_options: edit.protein_options.map(o => o.option_id === id ? { ...o, ...patch } : o) });
  };
  const removeProtein = (id: string) => {
    if (!edit) return;
    setEdit({ ...edit, protein_options: edit.protein_options.filter(o => o.option_id !== id) });
  };

  const priceLabel = (p: ThaliPackage) => {
    if (p.thali_type === "non_veg" && p.protein_options.length) {
      const min = Math.min(...p.protein_options.map(o => o.price_cents));
      return `From CA$${(min / 100).toFixed(2)}`;
    }
    return `CA$${(p.per_person_price_cents / 100).toFixed(2)}`;
  };

  return (
    <AdminShell title="Thali Party Orders">
      {loading ? <ActivityIndicator color={colors.primary} size="large" /> : (
        <>
          <View style={styles.actionRow}>
            <Text style={styles.count}>{items.length} thali{items.length === 1 ? "" : "s"}</Text>
            <TouchableOpacity testID="new-thali-btn" style={styles.primaryBtn} onPress={() => openEdit(null)}>
              <Ionicons name="add" size={16} color="#fff" />
              <Text style={styles.primaryBtnText}>New thali</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.grid}>
            {items.map(p => (
              <View key={p.package_id} style={styles.card} testID={`thali-card-${p.package_id}`}>
                {p.image_url ? <Image source={{ uri: p.image_url }} style={styles.img} /> : (
                  <View style={[styles.img, { alignItems: "center", justifyContent: "center" }]}>
                    <Ionicons name="fast-food-outline" size={30} color={colors.textMuted} />
                  </View>
                )}
                <View style={{ flex: 1, padding: spacing.md, gap: 6 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.name}>{p.name || "Untitled"}</Text>
                    <View style={[styles.tag, { backgroundColor: p.thali_type === "veg" ? "#16803722" : "#B91C1C22" }]}>
                      <Text style={[styles.tagText, { color: p.thali_type === "veg" ? "#15803D" : "#B91C1C" }]}>
                        {p.thali_type === "veg" ? "VEG" : "NON-VEG"}
                      </Text>
                    </View>
                    {!p.is_active && <Text style={styles.inactive}>HIDDEN</Text>}
                  </View>
                  <Text style={styles.pricing}>
                    <Text style={styles.priceStrong}>{priceLabel(p)}</Text>
                    <Text>{" "}/ person · min {p.min_guests} guests</Text>
                  </Text>
                  {p.thali_type === "non_veg" && (
                    <Text style={styles.chip}>{p.protein_options.map(o => `${o.name} CA$${(o.price_cents / 100).toFixed(2)}`).join(" · ")}</Text>
                  )}
                  <Text style={styles.desc} numberOfLines={3}>{p.includes.join(", ")}</Text>
                  <View style={styles.foot}>
                    <TouchableOpacity testID={`edit-thali-${p.package_id}`} style={styles.iconBtn} onPress={() => openEdit(p)}>
                      <Ionicons name="pencil" size={14} color={colors.text} />
                    </TouchableOpacity>
                    <TouchableOpacity testID={`del-thali-${p.package_id}`} style={styles.iconBtn} onPress={() => setConfirmDel(p)}>
                      <Ionicons name="trash-outline" size={14} color={colors.danger} />
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            ))}
            {items.length === 0 && <Text style={styles.empty}>No thali packages yet.</Text>}
          </View>
        </>
      )}

      {/* Edit modal */}
      <Modal visible={!!edit} transparent animationType="slide" onRequestClose={() => setEdit(null)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard} testID="edit-thali-modal">
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>{edit?.name ? `Edit — ${edit.name}` : "New thali"}</Text>
              <TouchableOpacity onPress={() => setEdit(null)}><Ionicons name="close" size={22} color={colors.text} /></TouchableOpacity>
            </View>
            {edit && (
              <ScrollView contentContainerStyle={{ gap: spacing.md, paddingBottom: spacing.xl }}>
                <View style={styles.section}>
                  <Text style={styles.label}>Name</Text>
                  <TextInput value={edit.name} onChangeText={t => setEdit({ ...edit, name: t })} style={styles.input} testID="thali-name" />

                  <Text style={[styles.label, { marginTop: spacing.sm }]}>Type</Text>
                  <View style={{ flexDirection: "row", gap: spacing.sm }}>
                    {(["veg", "non_veg"] as const).map(tt => (
                      <TouchableOpacity key={tt} testID={`thali-type-${tt}`} onPress={() => setEdit({ ...edit, thali_type: tt })}
                        style={[styles.pill, edit.thali_type === tt && styles.pillActive]}>
                        <Text style={[styles.pillText, edit.thali_type === tt && { color: "#fff" }]}>{tt === "veg" ? "Veg" : "Non-Veg"}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  <Text style={[styles.label, { marginTop: spacing.sm }]}>Description</Text>
                  <TextInput value={edit.description} onChangeText={t => setEdit({ ...edit, description: t })} multiline style={[styles.input, { minHeight: 60 }]} />

                  <Text style={[styles.label, { marginTop: spacing.sm }]}>Image URL (optional)</Text>
                  <TextInput value={edit.image_url} onChangeText={t => setEdit({ ...edit, image_url: t })} style={styles.input} testID="thali-image" placeholder="Paste an image URL" placeholderTextColor={colors.textMuted} />

                  <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>{edit.thali_type === "veg" ? "Per-person price (CAD)" : "Fallback price (CAD)"}</Text>
                      <TextInput testID="thali-price" value={priceStr} onChangeText={setPriceStr} keyboardType="decimal-pad" style={styles.input} />
                      {edit.thali_type === "non_veg" && <Text style={styles.hint}>Used only if no protein is chosen.</Text>}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>Minimum guests</Text>
                      <TextInput testID="thali-min" value={String(edit.min_guests)} keyboardType="number-pad"
                        onChangeText={t => setEdit({ ...edit, min_guests: parseInt(t.replace(/[^0-9]/g, ""), 10) || 0 })} style={styles.input} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>Sort order</Text>
                      <TextInput value={String(edit.sort_order)} keyboardType="number-pad"
                        onChangeText={t => setEdit({ ...edit, sort_order: parseInt(t.replace(/[^0-9]/g, ""), 10) || 0 })} style={styles.input} />
                    </View>
                  </View>

                  <TouchableOpacity onPress={() => setEdit({ ...edit, is_active: !edit.is_active })} style={[styles.pill, edit.is_active && styles.pillActive, { marginTop: spacing.sm }]} testID="thali-active">
                    <Ionicons name={edit.is_active ? "checkmark-circle" : "ellipse-outline"} size={16} color={edit.is_active ? "#fff" : colors.text} />
                    <Text style={[styles.pillText, edit.is_active && { color: "#fff" }]}>Active (visible to customers)</Text>
                  </TouchableOpacity>
                </View>

                {edit.thali_type === "non_veg" && (
                  <View style={styles.section}>
                    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm }}>
                      <Text style={styles.sectionTitle}>Protein options (per-person price)</Text>
                      <TouchableOpacity style={styles.smallBtn} onPress={addProtein} testID="thali-add-protein">
                        <Ionicons name="add" size={14} color="#fff" /><Text style={styles.smallBtnText}>Add</Text>
                      </TouchableOpacity>
                    </View>
                    {edit.protein_options.length === 0 && <Text style={styles.hint}>Add Mutton / Chicken / Fish etc. with per-person price.</Text>}
                    {edit.protein_options.map(o => (
                      <View key={o.option_id} style={{ flexDirection: "row", gap: spacing.sm, alignItems: "flex-end", marginTop: 6 }}>
                        <View style={{ flex: 2 }}>
                          <Text style={styles.label}>Protein</Text>
                          <TextInput value={o.name} onChangeText={t => updProtein(o.option_id, { name: t })} style={styles.input} testID={`protein-${o.option_id}-name`} placeholder="e.g. Mutton" placeholderTextColor={colors.textMuted} />
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.label}>CAD / person</Text>
                          <TextInput value={(o.price_cents / 100).toFixed(2)} keyboardType="decimal-pad"
                            onChangeText={t => updProtein(o.option_id, { price_cents: Math.round((parseFloat(t) || 0) * 100) })} style={styles.input} testID={`protein-${o.option_id}-price`} />
                        </View>
                        <TouchableOpacity onPress={() => removeProtein(o.option_id)} style={[styles.iconBtn, { marginBottom: 2 }]}>
                          <Ionicons name="trash-outline" size={14} color={colors.danger} />
                        </TouchableOpacity>
                      </View>
                    ))}
                  </View>
                )}

                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>What&apos;s included</Text>
                  <Text style={styles.hint}>One item per line (e.g. 1 Rice, 1 Dal, Sweet…).</Text>
                  <TextInput testID="thali-includes" value={includesText} onChangeText={setIncludesText} multiline
                    style={[styles.input, { minHeight: 110, marginTop: 6 }]}
                    placeholder={"1 Rice\n1 Roti / 2 Luchi-Poori\n1 Dal\n2 Veg curries\nSweet"} placeholderTextColor={colors.textMuted} />
                </View>

                <TouchableOpacity testID="thali-save" style={styles.saveBtn} onPress={save}>
                  <Ionicons name="save" size={16} color="#fff" /><Text style={styles.primaryBtnText}>Save thali</Text>
                </TouchableOpacity>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

      {/* Delete confirm */}
      <Modal visible={!!confirmDel} transparent animationType="fade" onRequestClose={() => setConfirmDel(null)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { maxWidth: 380, alignItems: "center", gap: 8 }]} testID="thali-delete-confirm">
            <View style={styles.delIcon}><Ionicons name="trash" size={24} color={colors.danger} /></View>
            <Text style={styles.modalTitle}>Delete thali?</Text>
            <Text style={styles.hint}>&quot;{confirmDel?.name}&quot; will be removed.</Text>
            <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
              <TouchableOpacity style={[styles.ghostBtn, { flex: 1 }]} onPress={() => setConfirmDel(null)}><Text style={styles.ghostBtnText}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity testID="thali-delete-ok" style={[styles.primaryBtn, { flex: 1, justifyContent: "center", backgroundColor: colors.danger }]} onPress={doDelete}><Text style={styles.primaryBtnText}>Delete</Text></TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </AdminShell>
  );
}

const styles = StyleSheet.create({
  actionRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  count: { color: colors.textMuted, fontWeight: "600" },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.pill, ...shadows.soft },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  smallBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.primary, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill },
  smallBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  ghostBtn: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  ghostBtnText: { color: colors.text, fontWeight: "700" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.primary, paddingVertical: 14, borderRadius: radius.pill, marginTop: spacing.md },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.md },
  card: { flexGrow: 1, flexBasis: 320, minWidth: 300, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, overflow: "hidden", ...shadows.soft },
  img: { width: "100%", height: 130, backgroundColor: colors.surfaceAlt },
  name: { fontSize: 16, fontWeight: "800", color: colors.text, flexShrink: 1 },
  tag: { paddingHorizontal: 7, paddingVertical: 2, borderRadius: 4 },
  tagText: { fontSize: 10, fontWeight: "900", letterSpacing: 1 },
  inactive: { fontSize: 9, fontWeight: "900", color: colors.textMuted, letterSpacing: 1 },
  pricing: { color: colors.textMuted, fontSize: 12 },
  priceStrong: { color: colors.primary, fontWeight: "800" },
  chip: { fontSize: 11, color: colors.text, backgroundColor: colors.surfaceAlt, paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.pill, alignSelf: "flex-start" },
  desc: { color: colors.textMuted, fontSize: 12, lineHeight: 16 },
  foot: { flexDirection: "row", gap: 6, marginTop: 6 },
  iconBtn: { width: 30, height: 30, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  empty: { color: colors.textMuted, textAlign: "center", padding: spacing.xl, width: "100%" },

  modalOverlay: { flex: 1, backgroundColor: colors.overlay, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  modalCard: { width: "100%", maxWidth: 720, maxHeight: "92%", backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, gap: spacing.sm, ...shadows.card },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.text },
  delIcon: { width: 52, height: 52, borderRadius: 26, backgroundColor: "#FEE2E2", alignItems: "center", justifyContent: "center" },

  section: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceAlt },
  sectionTitle: { fontSize: 14, fontWeight: "800", color: colors.text },
  label: { color: colors.textMuted, letterSpacing: 2, fontSize: 10, fontWeight: "800", marginBottom: 4 },
  hint: { color: colors.textMuted, fontSize: 11, fontStyle: "italic" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10, color: colors.text, fontSize: 14 },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { fontSize: 13, color: colors.text, fontWeight: "700" },
});
