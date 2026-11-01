import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, ScrollView } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import AdminShell from "@/src/components/AdminShell";
import { adminApi, getAdminToken } from "@/src/adminApi";
import { colors, spacing, radius, shadows } from "@/src/theme";

type TopItem = { item_id: string; item_name: string; adds: number; qty: number };
type RecentEvent = {
  type: string; ts: string | null; path?: string | null;
  item_id?: string | null; item_name?: string | null; qty?: number | null;
  session?: string | null;
};
type DayRow = { date: string; sessions: number; page_views: number; cart_adds: number; orders: number };
type Summary = {
  days: number; window_start: string; window_end: string;
  sessions: number; page_views: number; cart_views: number;
  cart_adds: number; checkout_starts: number; orders: number;
  top_items: TopItem[]; recent: RecentEvent[]; daily: DayRow[];
};

const RANGES = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];

const fmtTs = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? String(iso).slice(0, 16).replace("T", " ") : d.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" });
};
const pct = (num: number, den: number) => (den > 0 ? `${Math.round((num / den) * 100)}%` : "—");

export default function AdminAnalytics() {
  const router = useRouter();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const tok = await getAdminToken();
      if (!tok) { router.replace("/admin"); return; }
      setLoading(true); setError(null);
      const r = await adminApi.get<Summary>(`/admin/analytics/summary?days=${days}`);
      if (r.ok) setData(r.data);
      else if (r.status === 401) { router.replace("/admin"); return; }
      else setError(r.error || "Could not load analytics");
      setLoading(false);
    })();
  }, [days, router]);

  return (
    <AdminShell title="Analytics">
      <View style={styles.switchRow}>
        {RANGES.map((r) => (
          <TouchableOpacity
            key={r.days}
            testID={`analytics-range-${r.days}`}
            onPress={() => setDays(r.days)}
            style={[styles.switchBtn, days === r.days && styles.switchBtnOn]}
          >
            <Text style={[styles.switchText, days === r.days && styles.switchTextOn]}>{r.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} size="large" />
      ) : error ? (
        <Text style={{ color: colors.danger }}>{error}</Text>
      ) : data ? (
        <>
          <View style={styles.grid}>
            <Stat testID="analytics-stat-sessions" icon="people-outline" label="SESSIONS" value={String(data.sessions)} color="#6d28d9" hint="Anonymous visitors" />
            <Stat testID="analytics-stat-page-views" icon="eye-outline" label="PAGE VIEWS" value={String(data.page_views)} color={colors.primary} hint="Shop pages viewed" />
            <Stat testID="analytics-stat-cart-views" icon="cart-outline" label="CART VIEWS" value={String(data.cart_views)} color={colors.secondary} hint="Reached cart / checkout" />
            <Stat testID="analytics-stat-cart-adds" icon="bag-add-outline" label="CART ADDS" value={String(data.cart_adds)} color={colors.accent} hint="Items added to carts" />
            <Stat testID="analytics-stat-checkout-starts" icon="card-outline" label="CHECKOUT STARTS" value={String(data.checkout_starts)} color="#0284c7" hint="Place-order attempts" />
            <Stat testID="analytics-stat-orders" icon="checkmark-done-outline" label="ORDERS" value={String(data.orders)} color={colors.success} hint="Excl. pending payment" />
          </View>

          <View style={styles.funnel} testID="analytics-funnel">
            <Ionicons name="filter-outline" size={18} color={colors.secondary} />
            <Text style={styles.funnelText}>
              Funnel: {data.sessions} sessions → {data.cart_views} viewed cart ({pct(data.cart_views, data.sessions)}) →{" "}
              {data.checkout_starts} started checkout ({pct(data.checkout_starts, data.cart_views)}) →{" "}
              {data.orders} orders ({pct(data.orders, data.checkout_starts)} of checkouts).
              Sessions are anonymous — no names, emails, or personal data is ever collected here.
            </Text>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Top added items</Text>
            <ScrollView horizontal>
              <View>
                <View style={[styles.row, styles.headerRow]}>
                  {["Item", "Adds", "Qty"].map((h) => (
                    <Text key={h} style={[styles.cell, styles.headerCell, h === "Item" ? styles.wideCell : null]}>{h}</Text>
                  ))}
                </View>
                {data.top_items.map((t) => (
                  <View key={t.item_id} testID={`analytics-top-row-${t.item_id}`} style={styles.row}>
                    <Text style={[styles.cell, styles.wideCell]} numberOfLines={1}>{t.item_name}</Text>
                    <Text style={styles.cell}>{t.adds}</Text>
                    <Text style={styles.cell}>{t.qty}</Text>
                  </View>
                ))}
                {data.top_items.length === 0 && <Text style={styles.emptyText}>Nothing added to carts yet in this range.</Text>}
              </View>
            </ScrollView>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Recent activity (newest first)</Text>
            <ScrollView horizontal>
              <View>
                <View style={[styles.row, styles.headerRow]}>
                  {["Time", "Event", "Detail", "Session"].map((h) => (
                    <Text key={h} style={[styles.cell, styles.headerCell, h === "Detail" ? styles.wideCell : null]}>{h}</Text>
                  ))}
                </View>
                {data.recent.map((e, i) => (
                  <View key={`${e.ts || ""}-${i}`} testID={`analytics-recent-row-${i}`} style={styles.row}>
                    <Text style={styles.cell}>{fmtTs(e.ts)}</Text>
                    <Text style={styles.cell}>{e.type}</Text>
                    <Text style={[styles.cell, styles.wideCell]} numberOfLines={1}>
                      {e.type === "cart_add" ? `${e.item_name || e.item_id || "item"} × ${e.qty || 1}` : e.path || "—"}
                    </Text>
                    <Text style={styles.cell}>{e.session || "—"}</Text>
                  </View>
                ))}
                {data.recent.length === 0 && <Text style={styles.emptyText}>No events yet in this range.</Text>}
              </View>
            </ScrollView>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Daily</Text>
            <ScrollView horizontal>
              <View>
                <View style={[styles.row, styles.headerRow]}>
                  {["Date", "Sessions", "Page views", "Cart adds", "Orders"].map((h) => (
                    <Text key={h} style={[styles.cell, styles.headerCell]}>{h}</Text>
                  ))}
                </View>
                {[...data.daily].reverse().map((d) => (
                  <View key={d.date} style={styles.row}>
                    <Text style={styles.cell}>{d.date}</Text>
                    <Text style={styles.cell}>{d.sessions}</Text>
                    <Text style={styles.cell}>{d.page_views}</Text>
                    <Text style={styles.cell}>{d.cart_adds}</Text>
                    <Text style={[styles.cell, styles.boldCell]}>{d.orders}</Text>
                  </View>
                ))}
              </View>
            </ScrollView>
          </View>
        </>
      ) : (
        <Text style={{ color: colors.textMuted }}>No data yet.</Text>
      )}
    </AdminShell>
  );
}

function Stat({ icon, label, value, color, testID, hint }: any) {
  return (
    <View testID={testID} style={[styles.statCard, { borderLeftColor: color }]}>
      <View style={styles.statHead}>
        <Text style={styles.statLabel}>{label}</Text>
        <Ionicons name={icon} size={20} color={color} />
      </View>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statHint}>{hint}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  switchRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  switchBtn: { paddingVertical: 8, paddingHorizontal: 16, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  switchBtnOn: { backgroundColor: colors.text, borderColor: colors.text },
  switchText: { fontWeight: "700", fontSize: 13, color: colors.text },
  switchTextOn: { color: "#fff" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  statCard: {
    flexGrow: 1, flexBasis: 200, minWidth: 180,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.lg, borderWidth: 1, borderColor: colors.border,
    borderLeftWidth: 4, ...shadows.soft, gap: spacing.sm,
  },
  statHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  statLabel: { color: colors.textMuted, letterSpacing: 2, fontSize: 10, fontWeight: "800" },
  statValue: { fontSize: 26, fontWeight: "800", letterSpacing: -0.5 },
  statHint: { color: colors.textMuted, fontSize: 12 },
  funnel: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: "#FFF7E6", borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: "#FCD9A5", marginTop: spacing.md },
  funnelText: { flex: 1, color: "#7C4A03", fontSize: 13, lineHeight: 19 },
  section: { marginTop: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, ...shadows.soft, gap: spacing.md },
  sectionTitle: { fontSize: 18, fontWeight: "800", color: colors.text },
  row: { flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: 8 },
  headerRow: { backgroundColor: "#F1F5F9", borderRadius: radius.sm },
  cell: { width: 110, paddingHorizontal: 6, fontSize: 12, color: colors.text },
  wideCell: { width: 220 },
  headerCell: { fontWeight: "800", color: colors.textMuted },
  boldCell: { fontWeight: "800" },
  emptyText: { color: colors.textMuted, paddingVertical: 16, fontSize: 13 },
});
