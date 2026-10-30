import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ActivityIndicator, Switch, Platform,
} from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import AdminShell from "@/src/components/AdminShell";
import { adminApi } from "@/src/adminApi";
import { colors, spacing, radius, shadows } from "@/src/theme";

type Zone = {
  zone_id?: string;
  name: string;
  region?: string | null;
  postal_prefixes: string[];
  cities?: string[];
  fee_cents?: number | null;
  surcharge_cents: number;
  enabled: boolean;
};

const EMPTY: Zone = { name: "", region: "", postal_prefixes: [], cities: [], fee_cents: null, surcharge_cents: 0, enabled: true };

// Preferred display order for GTA regions; unknown regions sort after, alphabetically.
const REGION_ORDER = ["City of Toronto", "Peel Region", "York Region", "Halton Region", "Durham Region"];

export default function AdminPricing() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState<Zone | null>(null);
  const [prefixText, setPrefixText] = useState("");
  const [cityText, setCityText] = useState("");
  const [dollars, setDollars] = useState("");
  const [feeDollars, setFeeDollars] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    const r = await adminApi.get<{ zones: Zone[] }>("/admin/pricing-zones");
    setZones(r.ok ? r.data.zones || [] : []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setEdit({ ...EMPTY }); setPrefixText(""); setCityText(""); setDollars(""); setFeeDollars(""); };
  const openEdit = (z: Zone) => {
    setEdit({ ...z });
    setPrefixText((z.postal_prefixes || []).join(", "));
    setCityText((z.cities || []).join(", "));
    setDollars((z.surcharge_cents / 100).toFixed(2));
    setFeeDollars(z.fee_cents != null ? (z.fee_cents / 100).toFixed(2) : "");
  };

  const save = async () => {
    if (!edit) return;
    const prefixes = prefixText.split(/[\s,]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
    const cities = cityText.split(",").map(s => s.trim()).filter(Boolean);
    const cents = Math.round((parseFloat(dollars) || 0) * 100);
    const feeCents = feeDollars.trim() === "" ? null : Math.round((parseFloat(feeDollars) || 0) * 100);
    if (!edit.name.trim()) { if (Platform.OS === "web") window.alert("Zone name is required."); return; }
    setSaving(true);
    const r = await adminApi.post("/admin/pricing-zones", {
      zone_id: edit.zone_id, name: edit.name.trim(), region: (edit.region || "").trim(),
      postal_prefixes: prefixes, cities, fee_cents: feeCents, surcharge_cents: cents, enabled: edit.enabled,
    });
    setSaving(false);
    if (r.ok) { setEdit(null); await load(); }
    else if (Platform.OS === "web") window.alert("Could not save zone.");
  };

  const remove = async (z: Zone) => {
    if (Platform.OS === "web" && !window.confirm(`Delete zone "${z.name}"?`)) return;
    const r = await adminApi.del(`/admin/pricing-zones/${z.zone_id}`);
    if (r.ok) await load();
  };

  const sections = useMemo(() => {
    const map = new Map<string, Zone[]>();
    for (const z of zones) {
      const key = (z.region || "").trim() || "Other";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(z);
    }
    const order = (r: string) => {
      const i = REGION_ORDER.indexOf(r);
      return i === -1 ? REGION_ORDER.length + (r === "Other" ? 1 : 0) : i;
    };
    return Array.from(map.entries())
      .sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0]))
      .map(([region, list]) => ({
        region,
        zones: list.slice().sort((a, b) => a.name.localeCompare(b.name)),
      }));
  }, [zones]);

  return (
    <AdminShell title="Pricing Zones">
      <View style={styles.introRow}>
        <Text style={styles.intro}>Zones do two things: a fixed surcharge on grocery prices (by postal-code prefix), and a flat delivery fee for the zone&apos;s cities (orders from a listed city are charged that fee instead of the distance rate, and orders from cities in no zone are rejected). Base prices stay in the catalog; customers see the adjusted price automatically.</Text>
        <TouchableOpacity testID="new-zone-btn" style={styles.primaryBtn} onPress={openNew}>
          <Ionicons name="add" size={18} color="#fff" /><Text style={styles.primaryBtnText}>New zone</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} size="large" style={{ marginTop: 40 }} />
      ) : zones.length === 0 ? (
        <Text style={styles.empty}>No zones yet. Add one (e.g., &quot;Mississauga&quot; → L4, L5 → +$1.50).</Text>
      ) : (
        <View style={{ gap: spacing.lg, marginTop: spacing.md }}>
          {sections.map(sec => {
            const priced = sec.zones.filter(z => z.surcharge_cents > 0 || z.fee_cents != null).length;
            return (
              <View key={sec.region} style={{ gap: spacing.sm }} testID={`region-${sec.region}`}>
                <View style={styles.sectionHead}>
                  <Ionicons name="map-outline" size={16} color={colors.primary} />
                  <Text style={styles.sectionTitle}>{sec.region}</Text>
                  <Text style={styles.sectionCount}>{sec.zones.length} {sec.zones.length === 1 ? "zone" : "zones"}{priced ? ` · ${priced} priced` : ""}</Text>
                </View>
                {sec.zones.map(z => (
                  <View key={z.zone_id} style={styles.card} testID={`zone-${z.zone_id}`}>
                    <View style={{ flex: 1, gap: 4 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                        <Text style={styles.zoneName}>{z.name}</Text>
                        {!z.enabled && <Text style={styles.offTag}>OFF</Text>}
                      </View>
                      <Text style={styles.zoneMeta} numberOfLines={2}>
                        {(z.postal_prefixes || []).length} postal areas: {(z.postal_prefixes || []).join(", ") || "—"}
                      </Text>
                      <Text style={styles.zoneMeta} numberOfLines={3}>
                        {(z.cities || []).length} cities: {(z.cities || []).join(", ") || "—"}
                      </Text>
                      <Text style={[styles.zonePrice, z.fee_cents == null && { color: colors.textMuted }]}>
                        {z.fee_cents != null ? `Delivery fee: CA$${(z.fee_cents / 100).toFixed(2)}` : "No flat delivery fee"}
                      </Text>
                      <Text style={[styles.zonePrice, z.surcharge_cents === 0 && { color: colors.textMuted }]}>
                        {z.surcharge_cents > 0 ? `+CA$${(z.surcharge_cents / 100).toFixed(2)} per item` : "No surcharge — tap edit to set a price"}
                      </Text>
                    </View>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      <TouchableOpacity testID={`edit-zone-${z.zone_id}`} style={styles.iconBtn} onPress={() => openEdit(z)}><Ionicons name="pencil" size={16} color={colors.text} /></TouchableOpacity>
                      <TouchableOpacity testID={`del-zone-${z.zone_id}`} style={styles.iconBtn} onPress={() => remove(z)}><Ionicons name="trash-outline" size={16} color={colors.danger} /></TouchableOpacity>
                    </View>
                  </View>
                ))}
              </View>
            );
          })}
        </View>
      )}

      {edit && (
        <View style={styles.editor} testID="zone-editor">
          <Text style={styles.editorTitle}>{edit.zone_id ? "Edit zone" : "New zone"}</Text>
          <Text style={styles.label}>Zone name</Text>
          <TextInput testID="zone-name" style={styles.input} value={edit.name} onChangeText={t => setEdit({ ...edit, name: t })} placeholder="e.g., Mississauga" placeholderTextColor={colors.textMuted} />
          <Text style={styles.label}>Region (groups zones into a section)</Text>
          <TextInput testID="zone-region" style={styles.input} value={edit.region || ""} onChangeText={t => setEdit({ ...edit, region: t })} placeholder="e.g., Peel Region" placeholderTextColor={colors.textMuted} />
          <Text style={styles.label}>Postal-code prefixes (comma or space separated)</Text>
          <TextInput testID="zone-prefixes" style={styles.input} value={prefixText} onChangeText={setPrefixText} placeholder="e.g., L4, L5" placeholderTextColor={colors.textMuted} autoCapitalize="characters" />
          <Text style={styles.label}>Cities (comma separated — delivery area + flat fee applies to these)</Text>
          <TextInput testID="zone-cities" style={styles.input} value={cityText} onChangeText={setCityText} placeholder="e.g., Mississauga, Milton, Brampton" placeholderTextColor={colors.textMuted} />
          <Text style={styles.label}>Delivery fee for these cities (CA$ — blank = no flat fee, distance rate applies)</Text>
          <TextInput testID="zone-fee" style={styles.input} value={feeDollars} onChangeText={setFeeDollars} placeholder="5.00" placeholderTextColor={colors.textMuted} keyboardType="decimal-pad" />
          <Text style={styles.label}>Surcharge per item (CA$)</Text>
          <TextInput testID="zone-surcharge" style={styles.input} value={dollars} onChangeText={setDollars} placeholder="1.50" placeholderTextColor={colors.textMuted} keyboardType="decimal-pad" />
          <View style={styles.switchRow}>
            <Text style={styles.label}>Enabled</Text>
            <Switch value={edit.enabled} onValueChange={v => setEdit({ ...edit, enabled: v })} />
          </View>
          <View style={{ flexDirection: "row", gap: 10, marginTop: spacing.md }}>
            <TouchableOpacity testID="zone-save" style={[styles.primaryBtn, saving && { opacity: 0.6 }]} disabled={saving} onPress={save}>
              {saving ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="checkmark" size={18} color="#fff" />}
              <Text style={styles.primaryBtnText}>Save</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.ghostBtn} onPress={() => setEdit(null)}><Text style={styles.ghostBtnText}>Cancel</Text></TouchableOpacity>
          </View>
        </View>
      )}
    </AdminShell>
  );
}

const styles = StyleSheet.create({
  introRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md, flexWrap: "wrap" },
  intro: { flex: 1, minWidth: 240, color: colors.textMuted, fontSize: 13, lineHeight: 19 },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, paddingHorizontal: 16, height: 44, borderRadius: radius.pill },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  ghostBtn: { paddingHorizontal: 16, height: 44, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  ghostBtnText: { color: colors.text, fontWeight: "700" },
  empty: { color: colors.textMuted, marginTop: 30, textAlign: "center" },
  sectionHead: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: spacing.xs, paddingBottom: 4, borderBottomWidth: 1, borderBottomColor: colors.border },
  sectionTitle: { fontSize: 15, fontWeight: "800", color: colors.text },
  sectionCount: { fontSize: 12, fontWeight: "700", color: colors.textMuted, marginLeft: "auto" },
  card: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, ...shadows.soft },
  zoneName: { fontSize: 16, fontWeight: "800", color: colors.text },
  offTag: { fontSize: 10, fontWeight: "800", color: colors.danger, borderWidth: 1, borderColor: colors.danger, borderRadius: 4, paddingHorizontal: 5, paddingVertical: 1 },
  zoneMeta: { fontSize: 13, color: colors.textMuted },
  zonePrice: { fontSize: 14, fontWeight: "800", color: colors.primary },
  iconBtn: { width: 40, height: 40, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  editor: { marginTop: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, gap: 6, maxWidth: 520, ...shadows.card },
  editorTitle: { fontSize: 18, fontWeight: "800", color: colors.text, marginBottom: 4 },
  label: { fontSize: 12, fontWeight: "700", color: colors.textMuted, marginTop: 8 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 12, height: 44, color: colors.text, backgroundColor: colors.surfaceAlt },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
});
