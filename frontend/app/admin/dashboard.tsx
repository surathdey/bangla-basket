import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity, ScrollView, Linking } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useRouter } from "expo-router";
import AdminShell from "@/src/components/AdminShell";
import { adminApi, getAdminToken } from "@/src/adminApi";
import { getBackendUrl } from "@/src/utils/backendUrl";
import { colors, spacing, radius, shadows } from "@/src/theme";

type Stats = { total_orders: number; delivered: number; active: number; users: number; revenue_cents: number; };

type OrderRow = {
  order_id: string; status: string; payment_status: string; payment_method: string;
  total_cents: number; subtotal_cents: number; delivery_fee_cents: number; discount_cents: number;
  tax_cents?: number; tax_label?: string;
  coupon_code?: string | null; referral_code?: string | null; referral_discount_cents?: number;
  points_redeemed_cents?: number; points_redeemed?: number;
  special_instructions?: string;
  created_at: string;
  slot?: { date: string; window: string };
  address?: { line1: string; line2?: string; city: string; postal_code: string; name?: string };
  items_snapshot?: {
    name: string; quantity: number; unit_price_cents: number; line_total_cents: number;
    kind: string; cut_preference?: string; package_selection_names?: string[];
  }[];
  customer_name?: string;
  user_summary?: { name?: string; email?: string; phone?: string };
};

type CustomerRow = {
  user_id: string; name?: string; email?: string; phone?: string;
  total_orders: number; total_spent_cents: number; loyalty_points: number; last_order_date?: string;
};

type ViewSel =
  | { kind: "orders"; title: string; filter: "all" | "active" | "delivered" | "revenue" }
  | { kind: "customers"; title: string };

const ACTIVE_STATUSES = ["preparing", "out_for_delivery"];
const STATUS_COLORS: Record<string, string> = {
  new: "#6d28d9", confirmed: colors.accent, preparing: colors.secondary, packed: "#0284c7",
  out_for_delivery: colors.primary, delivered: colors.success, pending_payment: "#B45309", cancelled: colors.danger,
};

const money = (c: number) => `CA$${((c || 0) / 100).toFixed(2)}`;
const fmtDate = (iso?: string) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? String(iso).slice(0, 10) : d.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" });
};
const shortId = (id: string) => `#${String(id || "").slice(-6).toUpperCase()}`;
const custName = (o: OrderRow) => o.customer_name || o.user_summary?.name || o.address?.name || "Guest";
const csvCell = (v: any) => `"${String(v ?? "").replace(/"/g, '""')}"`;
const downloadCsv = (filename: string, csv: string) => {
  try {
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 500);
  } catch { /* non-web: export is web-only */ }
};

export default function AdminDashboard() {
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<ViewSel | null>(null);
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [customers, setCustomers] = useState<CustomerRow[] | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [selOrder, setSelOrder] = useState<OrderRow | null>(null);
  const [selCustomer, setSelCustomer] = useState<CustomerRow | null>(null);
  const [custOrders, setCustOrders] = useState<OrderRow[] | null>(null);

  useEffect(() => {
    (async () => {
      const tok = await getAdminToken();
      if (!tok) { router.replace("/admin"); return; }
      const r = await adminApi.get<Stats>("/admin/stats");
      if (r.ok) setStats(r.data);
      else if (r.status === 401) router.replace("/admin");
      setLoading(false);
    })();
  }, [router]);

  const openView = async (v: ViewSel) => {
    setView(v); setSelOrder(null); setSelCustomer(null); setCustOrders(null);
    if (v.kind === "orders" && orders === null) {
      setTableLoading(true);
      const r = await adminApi.get<OrderRow[]>("/admin/orders");
      if (r.status === 401) { router.replace("/admin"); return; }
      if (r.ok) setOrders(Array.isArray(r.data) ? r.data : []);
      setTableLoading(false);
    }
    if (v.kind === "customers" && customers === null) {
      setTableLoading(true);
      const r = await adminApi.get<CustomerRow[]>("/admin/customers");
      if (r.status === 401) { router.replace("/admin"); return; }
      if (r.ok) setCustomers(Array.isArray(r.data) ? r.data : []);
      setTableLoading(false);
    }
  };

  const viewOrders = useMemo(() => {
    if (!orders || view?.kind !== "orders") return [];
    // Match the backend's own counts: pending-payment orders are not counted
    // in total_orders / revenue, so they stay out of every drill-down table.
    const counted = orders.filter(o => o.status !== "pending_payment");
    if (view.filter === "active") return counted.filter(o => ACTIVE_STATUSES.includes(o.status));
    if (view.filter === "delivered") return counted.filter(o => o.status === "delivered");
    return [...counted].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  }, [orders, view]);

  const openCustomer = async (c: CustomerRow) => {
    setSelCustomer(c); setSelOrder(null); setCustOrders(null);
    const r = await adminApi.get<any>(`/admin/customers/${c.user_id}`);
    if (r.ok) setCustOrders(Array.isArray(r.data?.orders) ? r.data.orders : []);
  };

  const exportOrdersCsv = () => {
    const rows = viewOrders;
    const header = ["Order", "Date", "Customer", "Email", "Phone", "Items", "Item count", "Subtotal", "Delivery fee", "Coupon code", "Coupon discount", "Referral code", "Referral discount", "Points redeemed", "Tax", "Total", "Payment method", "Payment status", "Status", "City", "Postal code", "Slot date", "Slot window", "Notes"];
    const lines = rows.map(o => [
      shortId(o.order_id), fmtDate(o.created_at), custName(o), o.user_summary?.email || "", o.user_summary?.phone || "",
      (o.items_snapshot || []).map(it => `${it.quantity}x ${it.name}`).join("; "),
      (o.items_snapshot || []).reduce((s, it) => s + (it.quantity || 0), 0),
      money(o.subtotal_cents), money(o.delivery_fee_cents), o.coupon_code || "", money(o.discount_cents),
      o.referral_code || "", money(o.referral_discount_cents || 0), o.points_redeemed || 0,
      money(o.tax_cents || 0), money(o.total_cents), o.payment_method, o.payment_status, o.status,
      o.address?.city || "", o.address?.postal_code || "", o.slot?.date || "", o.slot?.window || "",
      o.special_instructions || "",
    ].map(csvCell).join(","));
    downloadCsv(`bangla-basket-orders-${new Date().toISOString().slice(0, 10)}.csv`, [header.map(csvCell).join(","), ...lines].join("\n"));
  };

  const exportCustomersCsv = () => {
    const rows = customers || [];
    const header = ["Customer", "Email", "Phone", "Orders", "Total spent", "Loyalty points", "Last order"];
    const lines = rows.map(c => [c.name || "", c.email || "", c.phone || "", c.total_orders, money(c.total_spent_cents), c.loyalty_points, c.last_order_date || ""].map(csvCell).join(","));
    downloadCsv(`bangla-basket-customers-${new Date().toISOString().slice(0, 10)}.csv`, [header.map(csvCell).join(","), ...lines].join("\n"));
  };

  return (
    <AdminShell title="Overview">
      {loading ? (
        <ActivityIndicator color={colors.primary} size="large" />
      ) : stats ? (
        <>
          <View style={styles.grid}>
            <Stat testID="stat-revenue" icon="cash-outline" label="GROSS REVENUE" value={money(stats.revenue_cents)} color={colors.success}
              hint={`${stats.total_orders} orders counted`} active={view?.kind === "orders" && view.filter === "revenue"}
              onPress={() => openView({ kind: "orders", title: "Revenue detail — all counted orders", filter: "revenue" })} />
            <Stat testID="stat-orders" icon="bag-handle-outline" label="ALL ORDERS" value={String(stats.total_orders)} color={colors.primary}
              hint="Tap to see every order" active={view?.kind === "orders" && view.filter === "all"}
              onPress={() => openView({ kind: "orders", title: "All orders", filter: "all" })} />
            <Stat testID="stat-active" icon="flame-outline" label="ACTIVE NOW" value={String(stats.active)} color={colors.secondary}
              hint="Preparing + on the way" active={view?.kind === "orders" && view.filter === "active"}
              onPress={() => openView({ kind: "orders", title: "Active now — preparing + on the way", filter: "active" })} />
            <Stat testID="stat-delivered" icon="checkmark-done-outline" label="DELIVERED" value={String(stats.delivered)} color={colors.accent}
              hint="Tap to see delivered orders" active={view?.kind === "orders" && view.filter === "delivered"}
              onPress={() => openView({ kind: "orders", title: "Delivered orders", filter: "delivered" })} />
            <Stat testID="stat-users" icon="people-outline" label="CUSTOMERS" value={String(stats.users)} color="#6d28d9"
              hint="Tap to see every customer" active={view?.kind === "customers"}
              onPress={() => openView({ kind: "customers", title: "All customers" })} />
          </View>

          {view && (
            <View style={styles.detail} testID="dash-detail">
              <View style={styles.detailHead}>
                <Text style={styles.detailTitle}>{view.title}</Text>
                <View style={styles.detailActions}>
                  <TouchableOpacity testID="dash-export" style={styles.exportBtn}
                    onPress={() => (view.kind === "orders" ? exportOrdersCsv() : exportCustomersCsv())}>
                    <Ionicons name="download-outline" size={16} color="#fff" />
                    <Text style={styles.exportBtnText}>Export CSV</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => { setView(null); setSelOrder(null); setSelCustomer(null); }} style={styles.closeBtn}>
                    <Text style={styles.closeBtnText}>✕ Close</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {tableLoading ? (
                <ActivityIndicator color={colors.primary} size="large" style={{ marginVertical: 24 }} />
              ) : view.kind === "orders" ? (
                <>
                  <Text style={styles.countText} testID="dash-count">{viewOrders.length} orders · Pending-payment orders are not counted in these totals.</Text>
                  {view.filter === "revenue" && (
                    <Text style={styles.revenueSum}>Total revenue: {money(viewOrders.reduce((s, o) => s + (o.total_cents || 0), 0))}</Text>
                  )}
                  <ScrollView horizontal testID="dash-table">
                    <View>
                      <View style={[styles.row, styles.headerRow]}>
                        {["Date", "Order", "Customer", "Items", "Subtotal", "Delivery", "Coupon", "Discount", "Tax", "Total", "Pay", "Status"].map(h => (
                          <Text key={h} style={[styles.cell, styles.headerCell, h === "Customer" ? styles.wideCell : null]}>{h}</Text>
                        ))}
                      </View>
                      {viewOrders.map(o => (
                        <TouchableOpacity key={o.order_id} testID={`dash-order-row-${o.order_id}`}
                          style={[styles.row, selOrder?.order_id === o.order_id && styles.selRow]}
                          onPress={() => setSelOrder(o)}>
                          <Text style={styles.cell}>{fmtDate(o.created_at)}</Text>
                          <Text style={styles.cell}>{shortId(o.order_id)}</Text>
                          <Text style={[styles.cell, styles.wideCell]}>{custName(o)}</Text>
                          <Text style={styles.cell}>{(o.items_snapshot || []).reduce((s, it) => s + (it.quantity || 0), 0)}</Text>
                          <Text style={styles.cell}>{money(o.subtotal_cents)}</Text>
                          <Text style={styles.cell}>{money(o.delivery_fee_cents)}</Text>
                          <Text style={styles.cell}>{o.coupon_code || "—"}</Text>
                          <Text style={styles.cell}>{money(o.discount_cents)}</Text>
                          <Text style={styles.cell}>{money(o.tax_cents || 0)}</Text>
                          <Text style={[styles.cell, styles.boldCell]}>{money(o.total_cents)}</Text>
                          <Text style={styles.cell}>{o.payment_method}</Text>
                          <Text style={[styles.cell, { color: STATUS_COLORS[o.status] || colors.textMuted }]}>{o.status}</Text>
                        </TouchableOpacity>
                      ))}
                      {viewOrders.length === 0 && <Text style={styles.emptyText}>No orders in this view yet.</Text>}
                    </View>
                  </ScrollView>
                  {selOrder && <OrderDetail order={selOrder} />}
                </>
              ) : (
                <>
                  <Text style={styles.countText} testID="dash-count">{(customers || []).length} customers</Text>
                  <ScrollView horizontal testID="dash-table">
                    <View>
                      <View style={[styles.row, styles.headerRow]}>
                        {["Customer", "Email", "Phone", "Orders", "Total spent", "Points", "Last order"].map(h => (
                          <Text key={h} style={[styles.cell, styles.headerCell, h === "Customer" || h === "Email" ? styles.wideCell : null]}>{h}</Text>
                        ))}
                      </View>
                      {(customers || []).map(c => (
                        <TouchableOpacity key={c.user_id} testID={`dash-customer-row-${c.user_id}`}
                          style={[styles.row, selCustomer?.user_id === c.user_id && styles.selRow]}
                          onPress={() => openCustomer(c)}>
                          <Text style={[styles.cell, styles.wideCell]}>{c.name || "—"}</Text>
                          <Text style={[styles.cell, styles.wideCell]}>{c.email || "no email"}</Text>
                          <Text style={styles.cell}>{c.phone || "—"}</Text>
                          <Text style={styles.cell}>{c.total_orders}</Text>
                          <Text style={[styles.cell, styles.boldCell]}>{money(c.total_spent_cents)}</Text>
                          <Text style={styles.cell}>{c.loyalty_points}</Text>
                          <Text style={styles.cell}>{c.last_order_date ? fmtDate(c.last_order_date) : "No orders yet"}</Text>
                        </TouchableOpacity>
                      ))}
                      {(customers || []).length === 0 && <Text style={styles.emptyText}>No customers yet.</Text>}
                    </View>
                  </ScrollView>
                  {selCustomer && (
                    <View style={styles.subDetail} testID="dash-customer-detail">
                      <Text style={styles.subTitle}>{selCustomer.name || "Customer"} — {selCustomer.total_orders} orders · {money(selCustomer.total_spent_cents)} total</Text>
                      <Text style={styles.subText}>{selCustomer.email || "no email"} · {selCustomer.phone || "no phone"} · {selCustomer.loyalty_points} loyalty points</Text>
                      {custOrders === null ? (
                        <ActivityIndicator color={colors.primary} style={{ marginVertical: 12 }} />
                      ) : custOrders.length === 0 ? (
                        <Text style={styles.emptyText}>This customer has no orders yet.</Text>
                      ) : custOrders.map(o => (
                        <TouchableOpacity key={o.order_id} testID={`dash-cust-order-${o.order_id}`} style={styles.miniRow} onPress={() => setSelOrder(o)}>
                          <Text style={styles.miniText}>{fmtDate(o.created_at)} · {shortId(o.order_id)} · {money(o.total_cents)} · {o.status}</Text>
                          <Text style={styles.miniHint}>Tap for full order detail ↓</Text>
                        </TouchableOpacity>
                      ))}
                      {selOrder && <OrderDetail order={selOrder} />}
                    </View>
                  )}
                </>
              )}
            </View>
          )}

          <View style={styles.tipBox} testID="admin-tip">
            <Ionicons name="sparkles" size={18} color={colors.secondary} />
            <Text style={styles.tipText}>
              Tap any number above to drill into it — every order, every customer, full detail, right here. Export the table to CSV any time.
            </Text>
          </View>
        </>
      ) : (
        <Text style={{ color: colors.textMuted }}>No data yet.</Text>
      )}
    </AdminShell>
  );
}

function OrderDetail({ order: o }: { order: OrderRow }) {
  return (
    <View style={styles.subDetail} testID="dash-order-detail">
      <Text style={styles.subTitle}>Order {shortId(o.order_id)} — {fmtDate(o.created_at)}</Text>
      <Text style={styles.subText}>
        {custName(o)}{o.user_summary?.email ? ` · ${o.user_summary.email}` : ""}{o.user_summary?.phone ? ` · ${o.user_summary.phone}` : ""}
      </Text>
      <Text style={styles.subText}>
        {o.address ? `${o.address.line1 || ""}${o.address.line2 ? `, ${o.address.line2}` : ""}, ${o.address.city || ""} ${o.address.postal_code || ""}` : "No address on file"}
        {o.slot ? ` · Slot: ${o.slot.date} (${o.slot.window})` : ""}
      </Text>
      <Text style={styles.subText}>Status: {o.status} · Payment: {o.payment_method} ({o.payment_status})</Text>
      {(o.items_snapshot || []).map((it, i) => (
        <Text key={i} style={styles.itemLine}>
          • {it.name} × {it.quantity} — {money(it.line_total_cents)}
          {it.cut_preference ? ` (Cut: ${it.cut_preference})` : ""}
          {it.package_selection_names?.length ? ` [${it.package_selection_names.join(", ")}]` : ""}
        </Text>
      ))}
      <Text style={styles.amountLine}>Subtotal {money(o.subtotal_cents)} · Delivery {money(o.delivery_fee_cents)}</Text>
      <Text style={styles.amountLine}>
        Coupon {o.coupon_code ? `${o.coupon_code} (−${money(o.discount_cents)})` : "none"}
        {o.referral_code ? ` · Referral ${o.referral_code} (−${money(o.referral_discount_cents || 0)})` : ""}
        {(o.points_redeemed || 0) > 0 ? ` · Points redeemed ${o.points_redeemed} (−${money(o.points_redeemed_cents || 0)})` : ""}
      </Text>
      <Text style={styles.amountLine}>Tax ({o.tax_label || "HST"}) {money(o.tax_cents || 0)} · <Text style={{ fontWeight: "800" }}>Total {money(o.total_cents)}</Text></Text>
      {o.special_instructions ? <Text style={styles.subText}>Customer notes: {o.special_instructions}</Text> : null}
      <TouchableOpacity testID={`dash-invoice-${o.order_id}`} style={styles.invoiceBtn}
        onPress={() => Linking.openURL(`${getBackendUrl()}/api/invoice/${o.order_id}`)}>
        <Text style={styles.invoiceBtnText}>View / print invoice</Text>
      </TouchableOpacity>
    </View>
  );
}

function Stat({ icon, label, value, color, testID, hint, active, onPress }: any) {
  return (
    <TouchableOpacity testID={testID} onPress={onPress} style={[styles.statCard, { borderLeftColor: color }, active && { borderColor: color, backgroundColor: "#F4F8FF" }]}>
      <View style={styles.statHead}>
        <Text style={styles.statLabel}>{label}</Text>
        <Ionicons name={icon} size={20} color={color} />
      </View>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      <Text style={styles.statHint}>{hint} ›</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
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
  tipBox: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: "#FFF7E6", borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: "#FCD9A5", marginTop: spacing.md },
  tipText: { flex: 1, color: "#7C4A03", fontSize: 13, lineHeight: 19 },
  detail: { marginTop: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, ...shadows.soft, gap: spacing.md },
  detailHead: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: spacing.md },
  detailTitle: { fontSize: 18, fontWeight: "800", color: colors.text },
  detailActions: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  exportBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, paddingVertical: 8, paddingHorizontal: 14, borderRadius: radius.md },
  exportBtnText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  closeBtn: { paddingVertical: 8, paddingHorizontal: 10 },
  closeBtnText: { color: colors.textMuted, fontWeight: "700", fontSize: 13 },
  countText: { color: colors.textMuted, fontSize: 12 },
  revenueSum: { fontSize: 16, fontWeight: "800", color: colors.success },
  row: { flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: 8 },
  headerRow: { backgroundColor: "#F1F5F9", borderRadius: radius.sm },
  cell: { width: 110, paddingHorizontal: 6, fontSize: 12, color: colors.text },
  wideCell: { width: 170 },
  headerCell: { fontWeight: "800", color: colors.textMuted },
  boldCell: { fontWeight: "800" },
  selRow: { backgroundColor: "#EEF4FF" },
  emptyText: { color: colors.textMuted, paddingVertical: 16, fontSize: 13 },
  subDetail: { backgroundColor: "#F8FAFC", borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, gap: 4, marginTop: spacing.sm },
  subTitle: { fontSize: 15, fontWeight: "800", color: colors.text },
  subText: { fontSize: 13, color: colors.textMuted, lineHeight: 18 },
  itemLine: { fontSize: 13, color: colors.text, lineHeight: 18 },
  amountLine: { fontSize: 13, color: colors.text },
  miniRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  miniText: { fontSize: 13, color: colors.text },
  miniHint: { fontSize: 11, color: colors.textMuted },
  invoiceBtn: { alignSelf: "flex-start", backgroundColor: colors.primary, paddingVertical: 8, paddingHorizontal: 14, borderRadius: radius.md, marginTop: 6 },
  invoiceBtnText: { color: "#fff", fontWeight: "700", fontSize: 13 },
});
