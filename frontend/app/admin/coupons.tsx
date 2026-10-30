import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, Switch, Platform } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import AdminShell from "@/src/components/AdminShell";
import { adminApi } from "@/src/adminApi";
import { colors, spacing, radius, shadows } from "@/src/theme";

type Coupon = {
  code: string; discount_type: string; value: number; active: boolean;
  min_order_cents: number; description: string; expiry?: string | null;
  usage_limit: number; per_customer_limit: number; first_time_only: boolean;
  used_count?: number; owner_user_id?: string | null;
};

const EMPTY: Coupon = { code: "", discount_type: "percent", value: 10, active: true, min_order_cents: 0, description: "", expiry: null, usage_limit: 0, per_customer_limit: 0, first_time_only: false };

export default function AdminCoupons() {
  const [list, setList] = useState<Coupon[]>([]);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState<Coupon | null>(null);
  const [minDollars, setMinDollars] = useState("0");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    const r = await adminApi.get<{ coupons: Coupon[] }>("/admin/coupons");
    if (r.ok) setList(r.data.coupons || []);
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const openNew = () => { setEdit({ ...EMPTY }); setMinDollars("0"); };
  const openEdit = (c: Coupon) => { setEdit({ ...c }); setMinDollars(((c.min_order_cents || 0) / 100).toString()); };

  const save = async () => {
    if (!edit) return;
    if (!edit.code.trim()) { if (Platform.OS === "web") window.alert("Code is required."); return; }
    if (edit.discount_type === "percent" && !(edit.value > 0 && edit.value <= 100)) {
      if (Platform.OS === "web") window.alert("Percentage must be 1–100."); return;
    }
    setSaving(true);
    const r = await adminApi.post("/admin/coupons", {
      code: edit.code.trim().toUpperCase(), discount_type: edit.discount_type, value: edit.value,
      active: edit.active, min_order_cents: Math.round((parseFloat(minDollars) || 0) * 100),
      description: edit.description, expiry: edit.expiry || null,
      usage_limit: edit.usage_limit || 0, per_customer_limit: edit.per_customer_limit || 0,
      first_time_only: edit.first_time_only,
    });
    setSaving(false);
    if (r.ok) { setEdit(null); await load(); }
    else if (Platform.OS === "web") window.alert("Could not save coupon.");
  };

  const remove = async (c: Coupon) => {
    if (Platform.OS === "web" && !window.confirm(`Delete coupon ${c.code}?`)) return;
    const r = await adminApi.del(`/admin/coupons/${c.code}`);
    if (r.ok) await load();
  };

  const numField = (label: string, val: number, on: (n: number) => void, hint?: string) => (
    <View style={{ gap: 4 }}>
      <Text style={styles.label}>{label}</Text>
      {!!hint && <Text style={styles.hint}>{hint}</Text>}
      <TextInput style={styles.input} keyboardType="number-pad" value={String(val)} onChangeText={t => on(parseInt(t) || 0)} placeholderTextColor={colors.textMuted} />
    </View>
  );

  return (
    <AdminShell>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Coupons</Text>
          <Text style={styles.sub}>Percentage & fixed discount codes. Auto-issued first-time coupons appear here too.</Text>
        </View>
        <TouchableOpacity testID="new-coupon" style={styles.newBtn} onPress={openNew}>
          <Ionicons name="add" size={18} color="#fff" /><Text style={styles.newBtnText}>New coupon</Text>
        </TouchableOpacity>
      </View>

      {edit && (
        <View style={styles.editCard}>
          <Text style={styles.editTitle}>{edit.code ? `Edit ${edit.code}` : "New coupon"}</Text>
          <Text style={styles.label}>Code</Text>
          <TextInput testID="coupon-code" style={styles.input} autoCapitalize="characters" value={edit.code} onChangeText={t => setEdit({ ...edit, code: t.toUpperCase() })} placeholder="SUMMER20" placeholderTextColor={colors.textMuted} />

          <View style={styles.row}>
            <TouchableOpacity style={[styles.typePill, edit.discount_type === "percent" && styles.typePillOn]} onPress={() => setEdit({ ...edit, discount_type: "percent" })}>
              <Text style={[styles.typeText, edit.discount_type === "percent" && styles.typeTextOn]}>Percentage %</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.typePill, edit.discount_type === "fixed" && styles.typePillOn]} onPress={() => setEdit({ ...edit, discount_type: "fixed" })}>
              <Text style={[styles.typeText, edit.discount_type === "fixed" && styles.typeTextOn]}>Fixed $ (cents)</Text>
            </TouchableOpacity>
          </View>
          {numField(edit.discount_type === "percent" ? "Percent off (1–100)" : "Amount off (cents)", edit.value, n => setEdit({ ...edit, value: n }))}

          <Text style={styles.label}>Minimum order ($)</Text>
          <TextInput testID="coupon-min" style={styles.input} keyboardType="decimal-pad" value={minDollars} onChangeText={setMinDollars} placeholder="0" placeholderTextColor={colors.textMuted} />

          <Text style={styles.label}>Expiry date (YYYY-MM-DD, optional)</Text>
          <TextInput testID="coupon-expiry" style={styles.input} value={edit.expiry || ""} onChangeText={t => setEdit({ ...edit, expiry: t })} placeholder="2026-12-31" placeholderTextColor={colors.textMuted} />

          {numField("Total usage limit (0 = unlimited)", edit.usage_limit, n => setEdit({ ...edit, usage_limit: n }))}
          {numField("Per-customer limit (0 = unlimited)", edit.per_customer_limit, n => setEdit({ ...edit, per_customer_limit: n }))}

          <Text style={styles.label}>Description</Text>
          <TextInput style={styles.input} value={edit.description} onChangeText={t => setEdit({ ...edit, description: t })} placeholder="20% off orders over $50" placeholderTextColor={colors.textMuted} />

          <View style={styles.switchRow}>
            <Text style={styles.label}>First-time customers only</Text>
            <Switch value={edit.first_time_only} onValueChange={v => setEdit({ ...edit, first_time_only: v })} />
          </View>
          <View style={styles.switchRow}>
            <Text style={styles.label}>Active</Text>
            <Switch value={edit.active} onValueChange={v => setEdit({ ...edit, active: v })} />
          </View>

          <View style={styles.editActions}>
            <TouchableOpacity style={styles.cancelBtn} onPress={() => setEdit(null)}><Text style={styles.cancelText}>Cancel</Text></TouchableOpacity>
            <TouchableOpacity testID="save-coupon" style={styles.saveBtn} onPress={save} disabled={saving}>
              {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.saveText}>Save coupon</Text>}
            </TouchableOpacity>
          </View>
        </View>
      )}

      {loading ? <ActivityIndicator color={colors.primary} size="large" style={{ marginTop: 40 }} /> :
        list.length === 0 ? <Text style={styles.empty}>No coupons yet. Create one above.</Text> :
        <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
          {list.map(c => (
            <View key={c.code} style={styles.card} testID={`coupon-row-${c.code}`}>
              <View style={styles.badge}><Text style={styles.badgeText}>{c.discount_type === "percent" ? `${c.value}%` : `$${(c.value / 100).toFixed(0)}`}</Text></View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <Text style={styles.code}>{c.code}</Text>
                  {!c.active && <Text style={styles.tagOff}>INACTIVE</Text>}
                  {c.first_time_only && <Text style={styles.tag}>First-time</Text>}
                  {c.owner_user_id && <Text style={styles.tag}>Personal</Text>}
                </View>
                <Text style={styles.meta} numberOfLines={1}>{c.description || "—"}</Text>
                <Text style={styles.meta}>
                  min ${(c.min_order_cents / 100).toFixed(0)} · used {c.used_count || 0}{c.usage_limit ? `/${c.usage_limit}` : ""}{c.expiry ? ` · exp ${c.expiry}` : ""}
                </Text>
              </View>
              <TouchableOpacity testID={`edit-coupon-${c.code}`} style={styles.iconBtn} onPress={() => openEdit(c)}><Ionicons name="pencil" size={16} color={colors.text} /></TouchableOpacity>
              <TouchableOpacity testID={`del-coupon-${c.code}`} style={styles.iconBtn} onPress={() => remove(c)}><Ionicons name="trash-outline" size={16} color={colors.danger} /></TouchableOpacity>
            </View>
          ))}
        </View>}
    </AdminShell>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: spacing.md, flexWrap: "wrap" },
  title: { fontSize: 22, fontWeight: "900", color: colors.text },
  sub: { fontSize: 13, color: colors.textMuted, marginTop: 2, maxWidth: 520 },
  newBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, borderRadius: radius.pill, paddingHorizontal: 16, paddingVertical: 10 },
  newBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  editCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, marginTop: spacing.md, gap: 8, borderWidth: 1, borderColor: colors.border, ...shadows.soft },
  editTitle: { fontSize: 16, fontWeight: "800", color: colors.text, marginBottom: 4 },
  label: { fontSize: 12, fontWeight: "800", color: colors.textMuted, marginTop: 6 },
  hint: { fontSize: 11, color: colors.textMuted, fontStyle: "italic" },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: colors.text, backgroundColor: colors.background },
  row: { flexDirection: "row", gap: 8, marginTop: 8 },
  typePill: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingVertical: 10, alignItems: "center" },
  typePillOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  typeText: { fontWeight: "800", color: colors.text, fontSize: 13 },
  typeTextOn: { color: "#fff" },
  switchRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10 },
  editActions: { flexDirection: "row", gap: 10, marginTop: spacing.md },
  cancelBtn: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, height: 46, alignItems: "center", justifyContent: "center" },
  cancelText: { fontWeight: "800", color: colors.text },
  saveBtn: { flex: 2, backgroundColor: colors.primary, borderRadius: radius.pill, height: 46, alignItems: "center", justifyContent: "center" },
  saveText: { color: "#fff", fontWeight: "800" },
  empty: { color: colors.textMuted, textAlign: "center", marginTop: 40 },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  badge: { backgroundColor: colors.surfaceAlt, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, minWidth: 56, alignItems: "center" },
  badgeText: { fontSize: 16, fontWeight: "900", color: colors.primary },
  code: { fontSize: 15, fontWeight: "800", color: colors.text },
  meta: { fontSize: 12, color: colors.textMuted },
  tag: { fontSize: 10, fontWeight: "800", color: colors.primary, backgroundColor: colors.surfaceAlt, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  tagOff: { fontSize: 10, fontWeight: "800", color: colors.danger, backgroundColor: colors.surfaceAlt, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  iconBtn: { width: 38, height: 38, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
});
