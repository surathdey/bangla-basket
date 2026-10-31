import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, shadows } from "@/src/theme";
import { centsToCAD } from "@/src/utils/format";
import { EmailAuthModal } from "@/src/components/EmailAuthModal";

type Coupon = { code: string; value: number; discount_type: string; description: string; expiry?: string | null; expired?: boolean; used?: boolean; personal?: boolean };
type Order = { order_id: string; total_cents: number; status: string; created_at: string; points_awarded?: number; items_snapshot?: any[]; referral_code?: string; referral_discount_cents?: number };
type Ledger = { delta: number; type: string; note: string; ts: string };

export default function ShopAccount() {
  const { user, loading, signIn, signOut, refresh } = useAuth();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [history, setHistory] = useState<Ledger[]>([]);
  const [busy, setBusy] = useState(true);
  const [emailOpen, setEmailOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyReferralCode = async () => {
    const code = user?.referral_code || "";
    if (!code) return;
    try {
      const nav = (typeof navigator !== "undefined" ? (navigator as any) : null);
      if (nav?.clipboard?.writeText) {
        await nav.clipboard.writeText(code);
      } else if (typeof document !== "undefined") {
        const ta = document.createElement("textarea");
        ta.value = code;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      } else {
        return;
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  const load = useCallback(async () => {
    setBusy(true);
    await refresh();
    const [c, o, h] = await Promise.all([
      api.get<{ coupons: Coupon[] }>("/me/coupons"),
      api.get<Order[]>("/orders"),
      api.get<{ entries: Ledger[] }>("/me/points-history"),
    ]);
    if (c.ok) setCoupons(c.data.coupons || []);
    if (o.ok) setOrders(o.data || []);
    if (h.ok) setHistory(h.data.entries || []);
    setBusy(false);
  }, [refresh]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) return <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>;

  const loggedIn = user && user.role !== "guest";
  if (!loggedIn) {
    return (
      <View style={[styles.center, { padding: spacing.xl }]}>
        <Ionicons name="person-circle-outline" size={56} color={colors.textMuted} />
        <Text style={styles.emptyTitle}>You're not signed in</Text>
        <Text style={styles.emptyHint}>Sign in to see your referral code, coupons and orders.</Text>
        <TouchableOpacity testID="account-google-login" style={styles.primaryBtn} onPress={() => signIn()}><Text style={styles.primaryBtnText}>Continue with Google</Text></TouchableOpacity>
        <TouchableOpacity testID="account-email-login" style={styles.secondaryBtn} onPress={() => setEmailOpen(true)}><Text style={styles.secondaryBtnText}>Login with Email</Text></TouchableOpacity>
        <TouchableOpacity style={styles.primaryBtn} onPress={() => router.push("/shop")}><Text style={styles.primaryBtnText}>Back to shop</Text></TouchableOpacity>
        <EmailAuthModal visible={emailOpen} onClose={() => setEmailOpen(false)} onSuccess={() => { setEmailOpen(false); load(); }} />
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.background }} contentContainerStyle={{ paddingTop: insets.top + 12, paddingBottom: 60, alignItems: "center" }}>
      <View style={styles.wrap}>
        <View style={styles.topRow}>
          <TouchableOpacity onPress={() => router.push("/shop")} style={styles.backBtn}><Ionicons name="arrow-back" size={20} color={colors.text} /><Text style={styles.backText}>Shop</Text></TouchableOpacity>
          <TouchableOpacity testID="account-logout" onPress={async () => { await signOut(); router.replace("/shop"); }} style={styles.logoutBtn}><Ionicons name="log-out-outline" size={18} color={colors.danger} /><Text style={styles.logoutText}>Logout</Text></TouchableOpacity>
        </View>

        {/* Profile + points */}
        <View style={styles.profileCard}>
          <Ionicons name="person-circle" size={48} color={colors.primary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{user!.name || user!.email.split("@")[0]}</Text>
            <Text style={styles.email}>{user!.email}</Text>
          </View>
          <View style={styles.pointsBadge}>
            <Text style={styles.pointsNum}>{user!.loyalty_points}</Text>
            <Text style={styles.pointsLabel}>points</Text>
          </View>
        </View>

        {/* Refer a friend */}
        <Text style={styles.section}>Refer a friend</Text>
        <View style={styles.referCard} testID="account-referral">
          <Text style={styles.referDesc}>Share your code — your friend gets 10% off groceries, and you get a 10% grocery coupon when their order is confirmed. One reward per friend.</Text>
          {(() => {
            const used = orders.find(o => (o.referral_discount_cents || 0) > 0);
            return used ? (
              <Text style={styles.referUsed} testID="account-referral-used">
                ✓ Referral code {used.referral_code || ""} already applied — it can't be used again.
              </Text>
            ) : null;
          })()}
          {user!.referral_code ? (
            <View style={styles.referCodeRow}>
              <Text style={styles.referCode} testID="account-referral-code">{user!.referral_code}</Text>
              <TouchableOpacity testID="account-referral-copy" style={styles.copyBtn} onPress={copyReferralCode}>
                <Ionicons name={copied ? "checkmark" : "copy-outline"} size={16} color="#fff" />
                <Text style={styles.copyBtnText}>{copied ? "Copied!" : "Copy"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <Text style={styles.muted}>Your referral code will appear here after you sign in again.</Text>
          )}
        </View>

        {/* Weekly meal streak */}
        <Text style={styles.section}>Weekly meal streak</Text>
        <View style={styles.streakCard} testID="account-streak">
          <Text style={styles.streakText}>
            {(user!.weekly_meal_streak || 0) === 0
              ? "0 of 4 weekly meals — order 4 weekly meals and your 5th is 50% off."
              : `${Math.min(user!.weekly_meal_streak || 0, 4)} of 4 weekly meals — ${Math.max(0, 4 - (user!.weekly_meal_streak || 0))} more and your 5th is 50% off.`}
          </Text>
        </View>

        {/* Saved address */}
        <Text style={styles.section}>Saved delivery address</Text>
        {user!.default_address ? (
          <View style={styles.card}>
            <Text style={styles.addrLine}>{user!.default_address.line1}{user!.default_address.line2 ? `, ${user!.default_address.line2}` : ""}</Text>
            <Text style={styles.addrSub}>{user!.default_address.city}, {user!.default_address.province} {user!.default_address.postal_code}</Text>
            <TouchableOpacity testID="remove-address" style={styles.linkRow} onPress={async () => { await api.del("/me/address"); await load(); }}>
              <Ionicons name="trash-outline" size={15} color={colors.danger} /><Text style={styles.linkDanger}>Remove</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <Text style={styles.muted}>No saved address yet — your address is saved automatically when you place an order.</Text>
        )}

        {/* My coupons */}
        <Text style={styles.section}>My coupons</Text>
        {coupons.length === 0 ? <Text style={styles.muted}>No coupons available right now.</Text> :
          coupons.map(c => (
            <View key={c.code} style={[styles.couponCard, (c.expired || c.used) && { opacity: 0.5 }]} testID={`coupon-${c.code}`}>
              <View style={styles.couponLeft}>
                <Text style={styles.couponPct}>{c.discount_type === "percent" ? `${c.value}%` : centsToCAD(c.value)}</Text>
                <Text style={styles.couponOff}>OFF</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.couponCode}>{c.code}{c.personal ? "  ·  Yours" : ""}</Text>
                <Text style={styles.couponDesc} numberOfLines={2}>{c.description}</Text>
                {(c.expired || c.used) && <Text style={styles.couponState}>{c.used ? "Coupon applied" : "Expired"}</Text>}
              </View>
            </View>
          ))}

        {/* Order history */}
        <Text style={styles.section}>Order history</Text>
        {busy && orders.length === 0 ? <ActivityIndicator color={colors.primary} style={{ marginTop: 10 }} /> :
          orders.length === 0 ? <Text style={styles.muted}>No orders yet.</Text> :
          orders.map(o => (
            <TouchableOpacity key={o.order_id} style={styles.orderCard} testID={`order-${o.order_id}`} onPress={() => router.push(`/shop/order/${o.order_id}`)}>
              <View style={{ flex: 1 }}>
                <Text style={styles.orderId}>#{o.order_id.slice(-6).toUpperCase()}</Text>
                <Text style={styles.orderMeta}>{new Date(o.created_at).toLocaleDateString()} · {o.status}{o.points_awarded ? ` · +${o.points_awarded} pts` : ""}</Text>
              </View>
              <Text style={styles.orderTotal}>{centsToCAD(o.total_cents)}</Text>
              <TouchableOpacity testID={`reorder-${o.order_id}`} style={styles.reorderBtn} onPress={() => router.push(`/shop/order/${o.order_id}`)}>
                <Ionicons name="refresh" size={14} color={colors.primary} /><Text style={styles.reorderText}>Reorder</Text>
              </TouchableOpacity>
            </TouchableOpacity>
          ))}

        {/* Points history */}
        {history.length > 0 && <>
          <Text style={styles.section}>Points history</Text>
          {history.map((h, i) => (
            <View key={i} style={styles.ledgerRow}>
              <Text style={styles.ledgerNote} numberOfLines={1}>{h.note}</Text>
              <Text style={[styles.ledgerDelta, { color: h.delta >= 0 ? colors.primary : colors.danger }]}>{h.delta >= 0 ? "+" : ""}{h.delta}</Text>
            </View>
          ))}
        </>}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background, gap: 10 },
  emptyTitle: { fontSize: 18, fontWeight: "800", color: colors.text },
  emptyHint: { fontSize: 14, color: colors.textMuted, textAlign: "center" },
  wrap: { width: "100%", maxWidth: 760, paddingHorizontal: spacing.lg, gap: spacing.sm },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  backBtn: { flexDirection: "row", alignItems: "center", gap: 6 },
  backText: { fontSize: 15, fontWeight: "700", color: colors.text },
  logoutBtn: { flexDirection: "row", alignItems: "center", gap: 6 },
  logoutText: { fontSize: 14, fontWeight: "700", color: colors.danger },
  profileCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, ...shadows.soft },
  name: { fontSize: 18, fontWeight: "800", color: colors.text },
  email: { fontSize: 13, color: colors.textMuted },
  pointsBadge: { alignItems: "center", backgroundColor: colors.surfaceAlt, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 8 },
  pointsNum: { fontSize: 20, fontWeight: "900", color: colors.primary },
  pointsLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  section: { fontSize: 15, fontWeight: "800", color: colors.text, marginTop: spacing.lg, marginBottom: 4 },
  muted: { fontSize: 13, color: colors.textMuted },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, gap: 4 },
  addrLine: { fontSize: 14, fontWeight: "700", color: colors.text },
  addrSub: { fontSize: 13, color: colors.textMuted },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 6 },
  linkDanger: { color: colors.danger, fontWeight: "700", fontSize: 13 },
  couponCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  couponLeft: { alignItems: "center", backgroundColor: colors.primary, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 8, minWidth: 64 },
  couponPct: { color: "#fff", fontSize: 18, fontWeight: "900" },
  couponOff: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  couponCode: { fontSize: 15, fontWeight: "800", color: colors.text },
  couponDesc: { fontSize: 12.5, color: colors.textMuted },
  couponState: { fontSize: 11, fontWeight: "800", color: colors.danger, marginTop: 2 },
  orderCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  orderId: { fontSize: 14, fontWeight: "800", color: colors.text },
  orderMeta: { fontSize: 12, color: colors.textMuted },
  orderTotal: { fontSize: 14, fontWeight: "800", color: colors.text },
  reorderBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 6 },
  reorderText: { color: colors.primary, fontWeight: "800", fontSize: 12 },
  ledgerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  ledgerNote: { fontSize: 13, color: colors.text, flex: 1 },
  ledgerDelta: { fontSize: 14, fontWeight: "800" },
  primaryBtn: { backgroundColor: colors.primary, borderRadius: radius.pill, paddingHorizontal: 24, height: 48, alignItems: "center", justifyContent: "center", marginTop: 10 },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 15 },
  secondaryBtn: { backgroundColor: colors.surfaceAlt, borderRadius: radius.pill, paddingHorizontal: 24, height: 48, alignItems: "center", justifyContent: "center", marginTop: 10, borderWidth: 1, borderColor: colors.border },
  secondaryBtnText: { color: colors.text, fontWeight: "800", fontSize: 15 },
  referCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, gap: 10 },
  referDesc: { fontSize: 13.5, color: colors.textMuted, lineHeight: 19 },
  referUsed: { fontSize: 13.5, color: colors.text, fontWeight: "700", lineHeight: 19 },
  streakCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  streakText: { fontSize: 13.5, color: colors.text, fontWeight: "700", lineHeight: 19 },
  referCodeRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, backgroundColor: colors.surfaceAlt, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10 },
  referCode: { fontSize: 20, fontWeight: "900", letterSpacing: 2, color: colors.text },
  copyBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, borderRadius: radius.pill, paddingHorizontal: 16, height: 40 },
  copyBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
