/**
 * Admin WhatsApp Broadcast — pick customers, enter a template name + body,
 * send ONLY to whatsapp_opt_in customers.
 *
 * IMPORTANT: the body MUST match a Meta-approved template EXACTLY
 * (variables substituted into the text) or Twilio/Meta rejects the send.
 * Template sync from the Twilio/Meta API is NOT built — template names
 * are entered manually. Customers without the opt-in flag are counted as
 * skipped and never sent, even if selected.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator,
} from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import AdminShell from "@/src/components/AdminShell";
import { adminApi } from "@/src/adminApi";
import { colors, spacing, radius, shadows } from "@/src/theme";

type Customer = {
  user_id: string; name: string; email: string; phone: string;
};

export default function WhatsappBroadcast() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [optIns, setOptIns] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [templateName, setTemplateName] = useState("");
  const [body, setBody] = useState("");
  const [armed, setArmed] = useState(false);
  const [sending, setSending] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const load = async () => {
    setLoading(true);
    const [c, o] = await Promise.all([
      adminApi.get<Customer[]>("/admin/customers"),
      adminApi.get<Record<string, boolean>>("/admin/whatsapp/opt-ins"),
    ]);
    if (c.ok) setCustomers(c.data);
    if (o.ok) setOptIns(o.data);
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return customers.filter((c) => {
      if (!c.phone) return false;
      if (!needle) return true;
      return (c.name || "").toLowerCase().includes(needle)
        || c.phone.includes(needle);
    });
  }, [customers, search]);

  const toggleSelect = (id: string) => {
    setArmed(false);
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleOptIn = async (id: string, next: boolean) => {
    setToggling(id);
    const r = await adminApi.post<any>("/admin/whatsapp/opt-in", { user_id: id, opt_in: next });
    setToggling(null);
    if (r.ok) {
      setOptIns((prev) => ({ ...prev, [id]: next }));
      setArmed(false);
    } else {
      setResult({ ok: false, msg: r.error });
    }
  };

  const recipients = useMemo(
    () => selected.filter((id) => optIns[id]),
    [selected, optIns],
  );
  const skipped = selected.length - recipients.length;

  const send = async () => {
    if (!armed) {
      if (!templateName.trim() || !body.trim()) {
        setResult({ ok: false, msg: "Template name and body are both required." });
        return;
      }
      if (recipients.length === 0) {
        setResult({ ok: false, msg: "No opted-in recipients selected — only customers flagged WhatsApp opt-in receive broadcasts." });
        return;
      }
      setArmed(true);
      return;
    }
    setSending(true);
    setResult(null);
    const r = await adminApi.post<any>("/admin/whatsapp/broadcast", {
      template_name: templateName.trim(),
      body: body.trim(),
      customer_ids: selected,
    });
    setSending(false);
    setArmed(false);
    if (r.ok) {
      setResult({
        ok: true,
        msg: `✓ Sent to ${r.data?.sent ?? 0} customer(s) via template "${r.data?.template_name}". `
          + `Skipped (not opted in): ${r.data?.skipped_not_opted_in ?? 0}. `
          + `Failed: ${(r.data?.failed || []).length}.`,
      });
      setSelected([]);
    } else {
      setResult({ ok: false, msg: r.error });
    }
  };

  return (
    <AdminShell title="WhatsApp Broadcast">
      <View testID="wa-bc-warning" style={[styles.banner, styles.bannerWarn]}>
        <Ionicons name="alert-circle" size={16} color="#B45309" />
        <Text style={styles.bannerText}>
          Broadcasts go ONLY to customers flagged WhatsApp opt-in, and the body must match a
          Meta-approved template EXACTLY (variables substituted into the text) — otherwise
          Twilio/Meta rejects the send. Template sync is not built yet: enter template names manually.
        </Text>
      </View>

      <Text style={styles.label}>Template name (Meta-approved)</Text>
      <TextInput testID="wa-bc-template" value={templateName}
        onChangeText={(t) => { setTemplateName(t); setArmed(false); }}
        placeholder="e.g. weekly_menu_update" autoCapitalize="none" style={styles.input} />

      <Text style={styles.label}>Message body (exact template text)</Text>
      <TextInput testID="wa-bc-body" value={body}
        onChangeText={(t) => { setBody(t); setArmed(false); }}
        placeholder="Type the message exactly as approved, with variables filled in…"
        multiline style={[styles.input, { minHeight: 100 }]} />

      <Text style={styles.label}>Customers (only phone numbers are listed)</Text>
      <TextInput testID="wa-bc-search" value={search} onChangeText={setSearch}
        placeholder="Search name or phone…" style={styles.input} />

      {loading ? (
        <ActivityIndicator color={colors.primary} />
      ) : (
        <View style={{ gap: spacing.sm }}>
          {visible.length === 0 && (
            <Text style={{ color: colors.textMuted }}>No customers with phone numbers found.</Text>
          )}
          {visible.map((c) => {
            const opted = !!optIns[c.user_id];
            const checked = selected.includes(c.user_id);
            return (
              <View key={c.user_id} testID="wa-bc-customer" style={styles.row}>
                <TouchableOpacity onPress={() => toggleSelect(c.user_id)}
                  style={[styles.check, checked && styles.checkOn]}>
                  {checked && <Ionicons name="checkmark" size={14} color="#fff" />}
                </TouchableOpacity>
                <View style={{ flex: 1, gap: 1 }}>
                  <Text style={styles.rowName}>{c.name || c.phone}</Text>
                  <Text style={styles.rowSub}>{c.phone}</Text>
                </View>
                <TouchableOpacity testID="wa-bc-optin-toggle"
                  onPress={() => toggleOptIn(c.user_id, !opted)}
                  disabled={toggling === c.user_id}
                  style={[styles.optBadge, opted ? styles.optOn : styles.optOff]}>
                  <Text style={[styles.optText, opted ? { color: colors.success } : { color: colors.textMuted }]}>
                    {toggling === c.user_id ? "…" : opted ? "Opted in ✓" : "Not opted in — tap to opt in"}
                  </Text>
                </TouchableOpacity>
              </View>
            );
          })}
        </View>
      )}

      <View testID="wa-bc-count" style={styles.countBox}>
        <Text style={styles.countText}>
          {recipients.length} customer(s) will receive this
          {skipped > 0 ? ` · ${skipped} selected but not opted in — will be skipped` : ""}
          {selected.length === 0 ? " · select customers above" : ""}
        </Text>
      </View>

      <TouchableOpacity testID={armed ? "wa-bc-confirm" : "wa-bc-send"} onPress={send}
        disabled={sending || recipients.length === 0}
        style={[styles.btnPrimary, (sending || recipients.length === 0) && { opacity: 0.5 }]}>
        {sending ? <ActivityIndicator color="#fff" size="small" /> :
          <><Ionicons name="megaphone-outline" size={16} color="#fff" />
          <Text style={styles.btnPrimaryText}>
            {armed ? `Tap again to confirm — send to ${recipients.length} customer(s)` : "Send broadcast"}
          </Text></>}
      </TouchableOpacity>

      {result && (
        <View testID="wa-bc-result" style={[styles.banner, result.ok ? styles.bannerOk : styles.bannerFail]}>
          <Ionicons name={result.ok ? "checkmark-circle" : "alert-circle"} size={16}
            color={result.ok ? colors.success : colors.danger} />
          <Text style={styles.bannerText}>{result.msg}</Text>
        </View>
      )}
    </AdminShell>
  );
}

const styles = StyleSheet.create({
  label: { color: colors.textMuted, letterSpacing: 1, fontSize: 11, fontWeight: "800", marginTop: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 10, color: colors.text, fontSize: 16 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.md, ...shadows.soft },
  check: { width: 24, height: 24, borderRadius: 6, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  checkOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  rowName: { color: colors.text, fontWeight: "800", fontSize: 15 },
  rowSub: { color: colors.textMuted, fontSize: 12 },
  optBadge: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1 },
  optOn: { backgroundColor: "#DCFCE7", borderColor: "#22c55e" },
  optOff: { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
  optText: { fontSize: 11, fontWeight: "800" },
  countBox: { backgroundColor: colors.surfaceAlt, borderRadius: radius.md, padding: spacing.md },
  countText: { color: colors.text, fontSize: 13, fontWeight: "700" },
  btnPrimary: { flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, paddingHorizontal: 16, paddingVertical: 13, borderRadius: radius.pill },
  btnPrimaryText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  banner: { flexDirection: "row", alignItems: "flex-start", gap: 6, padding: 10, borderRadius: radius.md, borderWidth: 1 },
  bannerWarn: { backgroundColor: "#FEF3C7", borderColor: "#F59E0B" },
  bannerOk: { backgroundColor: "#ecfdf5", borderColor: "#a7f3d0" },
  bannerFail: { backgroundColor: "#fef2f2", borderColor: "#fecaca" },
  bannerText: { color: colors.text, fontSize: 12, flex: 1, lineHeight: 17 },
});
