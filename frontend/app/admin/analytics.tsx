import React, { useCallback, useEffect, useState } from "react";
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
type HourRow = { hour: string; sessions: number; page_views: number; cart_adds: number; orders: number };
type Health = {
  cpu_percent: number | null; cpu_count: number | null;
  mem_total_mb: number | null; mem_used_mb: number | null; mem_percent: number | null;
  disk_total_gb: number | null; disk_used_gb: number | null; disk_percent: number | null;
  load_1: number | null; load_5: number | null; load_15: number | null;
  uptime_seconds: number | null; error: string | null;
};
type Summary = {
  days: number; window_start: string; window_end: string;
  sessions: number; page_views: number; cart_views: number;
  cart_adds: number; checkout_starts: number; orders: number;
  top_items: TopItem[]; recent: RecentEvent[]; daily: DayRow[]; hourly: HourRow[];
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

type MetricKey = "sessions" | "page_views" | "cart_adds" | "orders";
const METRICS: { key: MetricKey; label: string }[] = [
  { key: "sessions", label: "Sessions" },
  { key: "page_views", label: "Page views" },
  { key: "cart_adds", label: "Cart adds" },
  { key: "orders", label: "Orders" },
];
// Utilization colour: green <70, amber 70-85, red >85.
const barColor = (pctVal: number | null) =>
  pctVal === null ? colors.textMuted : pctVal < 70 ? colors.success : pctVal <= 85 ? "#d97706" : colors.danger;
const fmtUptime = (secs: number | null) => {
  if (secs === null) return "—";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h` : `${Math.floor(secs / 60)}m`;
};

export default function AdminAnalytics() {
  const router = useRouter();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<MetricKey>("sessions");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    const tok = await getAdminToken();
    if (!tok) { router.replace("/admin"); return; }
    setLoading(true); setError(null);
    const r = await adminApi.get<Summary>(`/admin/analytics/summary?days=${days}`);
    if (r.ok) setData(r.data);
    else if (r.status === 401) { router.replace("/admin"); return; }
    else setError(r.error || "Could not load analytics");
    setLoading(false);
  }, [days, router]);

  const loadHealth = useCallback(async (quiet = false) => {
    const tok = await getAdminToken();
    if (!tok) { router.replace("/admin"); return; }
    if (!quiet) setHealthError(null);
    const r = await adminApi.get<Health>("/admin/system/health");
    if (r.ok) setHealth(r.data);
    else if (r.status === 401) { router.replace("/admin"); return; }
    else if (!quiet) setHealthError(r.error || "Could not load system health");
  }, [router]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => {
    loadHealth();
    const t = setInterval(() => { loadHealth(true); }, 30000);
    return () => clearInterval(t);
  }, [loadHealth]);

  // Chart points: hourly bars for Today, daily bars otherwise (oldest first).
  const chartPoints = data
    ? days === 1 && data.hourly && data.hourly.length > 0
      ? data.hourly.map((h) => ({ label: h.hour, sessions: h.sessions, page_views: h.page_views, cart_adds: h.cart_adds, orders: h.orders }))
      : data.daily.map((d) => ({ label: d.date.slice(5), sessions: d.sessions, page_views: d.page_views, cart_adds: d.cart_adds, orders: d.orders }))
    : [];
  const maxAdds = data ? data.top_items.reduce((m, t) => Math.max(m, t.adds), 0) : 0;

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
        <TouchableOpacity testID="analytics-refresh" onPress={() => { loadSummary(); loadHealth(); }} style={[styles.switchBtn, styles.refreshBtn]}>
          <Ionicons name="refresh-outline" size={14} color={colors.text} />
          <Text style={styles.switchText}>Refresh</Text>
        </TouchableOpacity>
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

          <View style={styles.section} testID="analytics-health">
            <Text style={styles.sectionTitle}>System health (AWS box)</Text>
            <Text style={styles.healthNote}>Read from the host itself — CPU, memory, disk and load of the box this site runs on. Auto-refreshes every 30s; load averages are 1 / 5 / 15 min.</Text>
            {healthError ? (
              <Text style={{ color: colors.danger }}>{healthError}</Text>
            ) : health ? (
              <>
                {health.error ? <Text style={{ color: colors.danger, fontSize: 12 }}>{health.error}</Text> : null}
                <HealthRow testID="analytics-health-cpu" label="CPU" pctVal={health.cpu_percent} detail={health.cpu_percent === null ? "—" : `${health.cpu_percent}%`} />
                <HealthRow testID="analytics-health-mem" label="Memory" pctVal={health.mem_percent} detail={health.mem_used_mb === null || health.mem_total_mb === null ? "—" : `${health.mem_used_mb} / ${health.mem_total_mb} MB`} />
                <HealthRow testID="analytics-health-disk" label="Disk" pctVal={health.disk_percent} detail={health.disk_used_gb === null || health.disk_total_gb === null ? "—" : `${health.disk_used_gb} / ${health.disk_total_gb} GB`} />
                <HealthRow testID="analytics-health-load" label={`Load${health.cpu_count ? ` (${health.cpu_count} cores)` : ""}`} pctVal={health.load_1 === null || !health.cpu_count ? null : Math.min(100, (health.load_1 / health.cpu_count) * 100)} detail={health.load_1 === null ? "—" : `${health.load_1} / ${health.load_5} / ${health.load_15}`} />
                <Text style={styles.healthNote}>Host uptime: {fmtUptime(health.uptime_seconds)}</Text>
              </>
            ) : (
              <ActivityIndicator color={colors.primary} />
            )}
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

          <View style={styles.section} testID="analytics-daily-chart">
            <Text style={styles.sectionTitle}>{days === 1 ? "Today by hour" : "Daily"}</Text>
            <View style={styles.switchRow}>
              {METRICS.map((m) => (
                <TouchableOpacity key={m.key} testID={`analytics-chart-metric-${m.key}`} onPress={() => setMetric(m.key)} style={[styles.switchBtn, metric === m.key && styles.switchBtnOn]}>
                  <Text style={[styles.switchText, metric === m.key && styles.switchTextOn]}>{m.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <BarChart points={chartPoints} metric={metric} />
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Funnel</Text>
            <FunnelChart data={data} />
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Top added items</Text>
            <ScrollView horizontal>
              <View>
                <View style={[styles.row, styles.headerRow]}>
                  {["Item", "Adds", "Qty", "vs top"].map((h) => (
                    <Text key={h} style={[styles.cell, styles.headerCell, h === "Item" ? styles.wideCell : null, h === "vs top" ? { width: 130 } : null]}>{h}</Text>
                  ))}
                </View>
                {data.top_items.map((t) => (
                  <View key={t.item_id} testID={`analytics-top-row-${t.item_id}`} style={styles.row}>
                    <Text style={[styles.cell, styles.wideCell]} numberOfLines={1}>{t.item_name}</Text>
                    <Text style={styles.cell}>{t.adds}</Text>
                    <Text style={styles.cell}>{t.qty}</Text>
                    <View style={[styles.cell, { width: 130 }]}>
                      <View style={{ height: 8, borderRadius: 4, backgroundColor: colors.primary, width: maxAdds > 0 ? Math.max(4, Math.round((t.adds / maxAdds) * 120)) : 0 }} />
                    </View>
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

type ChartPoint = { label: string; sessions: number; page_views: number; cart_adds: number; orders: number };

/** Plain-View bar chart (no chart library): one flexbox bar per day/hour,
 * height proportional to the max value in view. Fixed 22px bars inside a
 * horizontal ScrollView so 30 days stay swipeable. */
function BarChart({ points, metric }: { points: ChartPoint[]; metric: MetricKey }) {
  const max = points.reduce((m, p) => Math.max(m, p[metric]), 0);
  if (points.length === 0) return <Text style={styles.emptyText}>No data yet in this range.</Text>;
  return (
    <View>
      <Text style={styles.chartPeak}>{max > 0 ? `Peak: ${max}` : "No activity yet in this range."}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={styles.chartRow}>
          {points.map((p) => {
            const v = p[metric];
            const h = max > 0 ? Math.max(2, Math.round((v / max) * 140)) : 2;
            return (
              <View key={p.label} testID={`analytics-bar-${p.label}`} style={styles.chartCol}>
                <Text style={styles.chartVal}>{v}</Text>
                <View style={[styles.chartBar, { height: h }]} />
                <Text style={styles.chartLabel}>{p.label}</Text>
              </View>
            );
          })}
        </View>
      </ScrollView>
    </View>
  );
}

/** Funnel as horizontal bars: width vs the largest stage, % of sessions. */
function FunnelChart({ data }: { data: Summary }) {
  const stages = [
    { key: "sessions", label: "Sessions", value: data.sessions, color: "#6d28d9", testID: "analytics-funnel-sessions" },
    { key: "cart_views", label: "Cart views", value: data.cart_views, color: colors.primary, testID: "analytics-funnel-cart_views" },
    { key: "checkout_starts", label: "Checkout starts", value: data.checkout_starts, color: "#0284c7", testID: "analytics-funnel-checkout_starts" },
    { key: "orders", label: "Orders", value: data.orders, color: colors.success, testID: "analytics-funnel-orders" },
  ];
  const max = Math.max(1, ...stages.map((s) => s.value));
  return (
    <View style={{ gap: spacing.sm }}>
      {stages.map((s) => (
        <View key={s.key} testID={s.testID} style={styles.funnelRow}>
          <Text style={styles.funnelLabel}>{s.label}</Text>
          <View style={styles.funnelTrack}>
            <View style={[styles.funnelFill, { width: `${s.value > 0 ? Math.max(2, (s.value / max) * 100) : 0}%`, backgroundColor: s.color }]} />
          </View>
          <Text style={styles.funnelVal}>{s.value} ({pct(s.value, data.sessions)})</Text>
        </View>
      ))}
    </View>
  );
}

function HealthRow({ testID, label, pctVal, detail }: { testID: string; label: string; pctVal: number | null; detail: string }) {
  const w = pctVal === null ? 0 : Math.max(0, Math.min(100, pctVal));
  return (
    <View testID={testID} style={styles.healthRow}>
      <Text style={styles.healthLabel}>{label}</Text>
      <View style={styles.healthTrack}>
        <View style={[styles.healthFill, { width: `${w}%`, backgroundColor: barColor(pctVal) }]} />
      </View>
      <Text style={styles.healthDetail}>{detail}</Text>
    </View>
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
  refreshBtn: { flexDirection: "row", alignItems: "center", gap: 6 },
  healthNote: { color: colors.textMuted, fontSize: 12, lineHeight: 17 },
  healthRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  healthLabel: { width: 90, fontSize: 13, fontWeight: "700", color: colors.text },
  healthTrack: { flex: 1, height: 12, borderRadius: 6, backgroundColor: "#E5E7EB", overflow: "hidden" },
  healthFill: { height: 12, borderRadius: 6 },
  healthDetail: { width: 150, fontSize: 12, color: colors.text, textAlign: "right" },
  chartPeak: { color: colors.textMuted, fontSize: 12, marginBottom: spacing.sm },
  chartRow: { flexDirection: "row", alignItems: "flex-end", gap: 8, paddingTop: spacing.sm, paddingBottom: 2 },
  chartCol: { width: 22, alignItems: "center", gap: 4 },
  chartVal: { fontSize: 10, fontWeight: "700", color: colors.text },
  chartBar: { width: 22, borderRadius: 4, backgroundColor: colors.primary },
  chartLabel: { fontSize: 9, color: colors.textMuted, textAlign: "center" },
  funnelRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  funnelLabel: { width: 110, fontSize: 13, fontWeight: "700", color: colors.text },
  funnelTrack: { flex: 1, height: 16, borderRadius: 8, backgroundColor: "#E5E7EB", overflow: "hidden" },
  funnelFill: { height: 16, borderRadius: 8 },
  funnelVal: { width: 110, fontSize: 12, color: colors.text, textAlign: "right" },
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
